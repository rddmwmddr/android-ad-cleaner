"""读屏失败的排查提示；辅助检查仅读取设置，不停用其他服务。"""
import os
import re
import subprocess

import adb_link
# 显式转发：调用点与单测仍从本模块取（沿用 #729 的做法，整句常量按 #747 加）
from host import (CLICK as CLICK, CLICKER as CLICKER, ON_PHONE as ON_PHONE,
                  TAPPED as TAPPED)


UI_RECOVERY = (
    "读屏连接失败时，请检查 GKD、自动记账、Appium 等是否正在自动操作手机。"
    "用户反馈暂停 GKD 和自动记账后可继续，但尚不能确定具体占用者或模式。"
    "请只暂停你确认可暂停的自动化 / Shizuku 读屏功能，必要时由本人暂时关闭对应 App 的无障碍服务；"
    "保留你依赖的屏幕阅读器和辅助服务，不要一键关闭全部无障碍。"
    "保持手机解锁，再点「检查读屏连接」；仍失败可手动重启手机并复制完整诊断。"
    "完成后按需恢复暂停的工具。"
)


XIAOMI_INPUT = (
    "小米 / Redmi / POCO 还要在「开发者选项」里打开「USB 调试（安全设置）」（需插 SIM 卡、登录小米账号）。"
    "不开它，本 App 能读屏幕，但点不动、改不了设置，会出现大量「没找到」「点击后渠道状态未改变」。"
    "打开时手机弹出风险提示，要等倒计时结束点「确定」。已经打开了仍被拒：重启手机后再试。"
) if ON_PHONE else (
    "小米 / Redmi / POCO 还要在「开发者选项」里打开「USB 调试（安全设置）」（需插 SIM 卡、登录小米账号）。"
    "不开它，电脑能读屏幕，但点不动、改不了设置，会出现大量「没找到」「点击后渠道状态未改变」和中途锁屏。"
    "打开时手机弹出风险提示，要等倒计时结束点「确定」。已经打开了仍被拒：拔掉数据线重新插上；还不行就重启手机"
    "（#217 #245 #251 #257 #266：多位用户打开后仍被拒，有人重启后恢复）。"
)


# 读屏服务装不上：桌面版是 adb push 失败，手机版是本 App 自己的 shell 通道传不了文件（#729）。
UI_INSTALL_FAILED = (
    "读屏服务没能启动（本 App 的调试通道传不了文件），本次未点击开关。"
    "回到本 App 首页重新连一次调试后重试；仍失败请重启手机。"
) if ON_PHONE else (
    "读屏服务没能装到手机上（adb 传文件失败），本次未点击开关。"
    "请拔插数据线、退出电脑上的手机助手类软件后重试；仍失败请重启手机。"
)


def input_blocked(output):
    """小米未开「USB 调试（安全设置）」时，adb 注入点击被拒：INJECT_EVENTS。"""
    return isinstance(output, str) and "INJECT_EVENTS" in output


def is_ui_connection_error(detail):
    return any(marker in detail for marker in (
        "UIAUTOMATION_BUSY", "AccessibilityServiceAlreadyRegisteredError",
        "LaunchUiAutomationError", "UiAutomationNotConnectedError",
        "UiAutomationService", "手机读屏服务（UiAutomation）启动失败",
    ))


def accessibility_summary(serial, adb=None):
    """有界只读检查；仅返回总开关和数量，应用 / 服务标识不进入诊断。"""
    try:
        adb = adb or adb_link.adb_path()
        if not adb:
            return "未找到可用于只读检查的 adb；仍可按下方步骤排查。"
        result = subprocess.run(
            [adb, "-s", serial, "shell",
             "settings get secure accessibility_enabled; settings get secure enabled_accessibility_services"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        lines = result.stdout.strip().splitlines()
        if result.returncode or len(lines) != 2 or lines[0].strip() not in {"0", "1"}:
            return "未能读取无障碍服务状态；仍可按下方步骤排查。"
        configured = lines[1].strip()
        services = set() if configured in {"", "null"} else set(configured.split(":"))
        if any(not re.fullmatch(r"[\w.]+/[\w.$]+", value) for value in services):
            return "未能识别无障碍服务状态；仍可按下方步骤排查。"
        if lines[0].strip() == "0":
            status = "无障碍总开关为关闭"
        else:
            status = f"无障碍总开关已开启，配置了 {len(services)} 项服务"
        return f"只读检查：{status}。此信息不能证明谁占用读屏，也不能排除独立的自动化 / Shizuku 会话。"
    except (OSError, subprocess.TimeoutExpired):
        return "无障碍状态读取超时或失败；仍可按下方步骤排查。"
