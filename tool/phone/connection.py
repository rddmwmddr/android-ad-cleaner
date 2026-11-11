"""连接与生命周期：设备、串号、断线、锁屏等待、日志开关（ADR-0033）。

门面 `Phone` 只持有它并转发；观测基座 `Screen` 构造时注入它。这里不做观测，也不认识 `Phone`。
"""
import contextlib
import os
import time

import adbutils
import uiautomator2 as u2

import adb_link
import events
import wait
from reader import Reader
from troubleshooting import (TAPPED, UI_INSTALL_FAILED, UI_RECOVERY, XIAOMI_INPUT,
                             accessibility_summary, input_blocked)
from ui_session import connect


def pause_point():
    """客户端点了「暂停」（创建 AAC_PAUSE_FILE）就在这里等，点「继续」（删掉文件）再往下走；暂停过返回 True。
    只放在安全的位置：机型脚本每段开始前（段首的锁屏检查）、营销通知每个渠道开始前。
    暂停期间不读屏、不点击；继续后重新读页面，不用暂停前的坐标。"""
    path = os.environ.get("AAC_PAUSE_FILE")
    if not path or not os.path.exists(path):
        return False
    print("⏸ 已暂停：现在可以操作手机。操作完回到桌面、保持解锁，再点「继续」", flush=True)
    events.emit("paused")
    while os.path.exists(path):
        time.sleep(0.5)
    print("▶ 继续执行", flush=True)
    events.emit("resumed")
    return True


def _shell_transport(shell):
    """读屏库的 shell 当传输。断线只有它认得出来（异常类型加错误串），判定留在这一层。"""
    def send(command, timeout=None):
        try:
            return shell(command) if timeout is None else shell(command, timeout=timeout)
        except Exception as e:
            # 「shell output invalid … b''」：命令没有任何回应，连接正在断开（错误日志 10-27）。
            if adb_link.lib_gone(str(e)) or (isinstance(e, u2.exceptions.AdbShellError) and "output invalid" in str(e)):
                raise adb_link.LinkBroken(e) from e
            raise
    return send


def reader_failure(serial, error):
    """读屏连不上、或连上后的第一次读屏失败：屏没了与读屏服务坏了是两回事，两处共用这一份翻译（#928）。"""
    if adb_link.screen_gone(error):     # 屏已经没了不是读屏服务坏了：别把用户指去关别的客户端（#674）
        return RuntimeError(f"{adb_link.SCREEN_GONE_CONNECT}\n原始异常：{type(error).__name__}: {error}")
    return RuntimeError("手机读屏服务（UiAutomation）启动失败，本次未点击开关。"
                        f"\n{accessibility_summary(serial)}\n{UI_RECOVERY}\n"
                        f"原始异常：{type(error).__name__}: {error}")


class Connection:
    """一台手机：读屏 adapter、断线判定、锁屏等待与日志开关。

    构造签名里的唯一注入点是 `reader=`：读屏替身从那里下传一层（ADR-0033）。
    """

    def __init__(self, serial, log=True, reader: Reader | None = None):
        self.log = log
        self.pause_at_lock_check = True     # 机型脚本每段开头都查锁屏：这里就是段与段之间，可以暂停
        if log:
            print("正在连接手机读屏服务……", flush=True)
        try:
            self.reader = reader if reader is not None else connect(serial)
        except u2.exceptions.AccessibilityServiceAlreadyRegisteredError as e:
            events.emit("ui_busy")
            raise RuntimeError("UIAUTOMATION_BUSY：手机读屏服务已被占用，本次未点击开关。"
                               "已清理本次失败的启动并重试一次，仍无法连接。"
                               "请退出旧版客户端，只保留一个客户端。\n"
                               f"{accessibility_summary(serial)}\n{UI_RECOVERY}\n"
                               f"原始异常：{type(e).__name__}: {e}") from e
        except u2.exceptions.UiAutomationError as e:
            raise reader_failure(serial, e) from e
        except (u2.exceptions.AdbShellError, adbutils.AdbError) as e:
            # 读屏服务文件传不进手机（adb push 返回 FAIL）或命令无回应：多半是连接中途断了（错误日志 10-27）。
            if not adb_link.present(serial):
                raise adb_link.lost(f"{type(e).__name__}: {e}") from e
            raise RuntimeError(UI_INSTALL_FAILED + f"\n原始异常：{type(e).__name__}: {str(e)[:200]}") from e
        self._shell = self.reader.shell
        self.link = adb_link.Connection(serial, transport=_shell_transport(self._shell), lost_on_retry=False)
        self.reader.shell = self._resilient_shell
        with self.guarded():
            self.reader.settings["operation_delay"] = (0, 0)

    @contextlib.contextmanager
    def guarded(self):
        """连上之后的构造期读屏动作：坏了就按三种结局翻译，且一定把读屏关掉再抛。

        断线 / 读屏慢一次 / 读屏服务起不来 —— 翻译只在 `failure()` 一份；
        `Screen` 构造时读屏宽高也走这里，别在那里另抄一段 `except`。
        """
        try:
            yield
        except u2.exceptions.UiAutomationError as e:
            raise self.failure(e) from e
        except BaseException:
            self.reader.close()
            raise

    def failure(self, error):
        """连接建好之后读屏坏了：断线 / 读屏慢一次 / 读屏服务起不来，三种结局的翻译只在这里一份（#731）。"""
        self.reader.close()
        lost = adb_link.lost_from(error, self.link.serial)    # 命令服务断开这一族仍是断线，别包成读屏服务起不来
        if lost is not None:
            return lost
        slow = adb_link.read_failed(error)          # 读屏慢一次只是这一步没成
        if slow:
            return RuntimeError(slow)
        return reader_failure(self.link.serial, error)

    def check_input(self):
        """小米没开「USB 调试（安全设置）」时能读不能点：先探一下，别跑几分钟全是「没找到」。"""
        with self.guarded():
            if input_blocked(self.reader.shell("input keyevent 0").output):
                raise RuntimeError(f"INPUT_BLOCKED：系统拒绝了{TAPPED}，本次未点击开关。\n" + XIAOMI_INPUT)

    @property
    def serial(self):
        """串号归这里：每条命令都要带 -s，不存在「手机对象认一台、命令发给另一台」。"""
        return self.link.serial

    @serial.setter
    def serial(self, value):
        self.link.serial = value

    @property
    def lost(self):
        """本轮是否已确认断线。"""
        return self.link.lost

    @lost.setter
    def lost(self, value):
        if value:
            self.link.mark_lost()

    def _resilient_shell(self, *args, **kwargs):
        """手机短暂掉线（另一个 adb 服务重启、接口抖动）等它回来重试一次；仍不在就整段停下。"""
        return self.link.shell(*args, **kwargs)

    def check_alive(self):
        """本轮已确认断线：本段立刻停下，不再读屏、不再逐段重试（#293）。
        排查说明由第一次报错给出，后面的段只报这一句。"""
        self.link.check_alive()

    def _u2(self, fn, *a, **k):
        """u2 直连的调用（dump_hierarchy、window_size、app_stop）不走 shell；
        连接级异常也在这里记下断线，否则后面的段会一遍遍重复同样的失败（#293）。"""
        self.check_alive()
        try:
            return fn(*a, **k)
        except Exception as e:
            if adb_link.lib_gone(str(e)):
                self.lost = True
            raise

    def close(self):
        self.reader.close()

    def say(self, *a):
        if self.log:
            print(*a, flush=True)

    def locked(self):
        if self.pause_at_lock_check and pause_point():
            return not self.wait_unlocked()      # 暂停时机主可能锁了屏：亮屏等他解锁
        out = self.reader.shell(adb_link.KEYGUARD_CMD).output
        if adb_link.focus_window(out) == "NotificationShade" and not adb_link.LOCK_FIELD.search(out):
            # 可能只是通知栏被拉下来了：收起后再看；锁屏界面收不起来，焦点仍是 NotificationShade
            self.reader.shell("cmd statusbar collapse")
            time.sleep(0.4)
            out = self.reader.shell(adb_link.KEYGUARD_CMD).output
        return adb_link.keyguard_showing(out)

    def wait_unlocked(self, timeout=wait.UNLOCK_TIMEOUT):
        """锁屏时点亮屏幕，等机主解锁。文案、节奏与事件在 wait.wait_unlocked（#709）。"""
        return wait.wait_unlocked(self.locked, lambda: self.reader.shell(adb_link.WAKEUP),
                                  timeout, now=time.time, sleep=time.sleep)
