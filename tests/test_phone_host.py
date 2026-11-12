"""手机版宿主的说法（#729）：没有电脑和数据线，插电常亮也不是手机版的防锁屏办法（#728）。

说法按宿主分叉，控制流只有一个例外（手机版不写插电常亮，ADR-0019）；两组用例都在这里。

末尾是 #747（跟进 #729）：手机版界面上残留的桌面说法——诊断里的「点击被拒」、点击被拒的整句
与 `check` 那一行都按宿主取词，桌面版逐字不变；boot() 对模块常量的覆盖在 PhoneBootTests 里。
"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import ast
import contextlib
import importlib
import io
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import chan_fast as chan
import run
import troubleshooting
from backups import Backups
from phone import screen as phone_screen
from fixtures import FakeProc, FakeRunner, job_stub, phone_mock, phone_stub

PHONE_LINK_LOST = "和手机的调试连接断开了，这一步没有执行。回到本 App 点「重新开始」。"


def reload_for(host):
    """按宿主重新导入 host → troubleshooting：两者的常量都在导入时定死。

    adb_link 不在这里重载：它会把 `DeviceLost` / `LinkBroken` 的类对象换掉，同进程里别的用例
    拿着的旧实例就不再 `isinstance`（`tests/test_adb_link.py` 在模块级存了一份）。它的常量改用子进程取。
    """
    env = {k: v for k, v in os.environ.items() if k != "AAC_HOST"}
    if host:
        env["AAC_HOST"] = host
    with patch.dict(os.environ, env, clear=True):
        import host as host_mod
        importlib.reload(host_mod)
        return importlib.reload(troubleshooting)


def tearDownModule():
    reload_for(None)


class WordingTests(unittest.TestCase):
    def reload(self, host):
        return reload_for(host)

    def tearDown(self):
        self.reload(None)

    def test_phone_host_drops_computer_and_cable(self):
        t = self.reload("phone")
        self.assertTrue(t.ON_PHONE)
        self.assertEqual(t.CLICKER, "本 App")
        self.assertIn("USB 调试（安全设置）", t.XIAOMI_INPUT)
        for word in ("电脑", "数据线"):
            self.assertNotIn(word, t.XIAOMI_INPUT)
        self.assertNotIn("数据线", t.UI_INSTALL_FAILED)

    def test_desktop_wording_is_unchanged(self):
        """旧树也绿，守的是不回退：桌面版的 XIAOMI_INPUT 与 CLICKER 逐字不变。"""
        t = self.reload(None)
        self.assertFalse(t.ON_PHONE)
        self.assertEqual(t.CLICKER, "电脑")
        self.assertIn("不开它，电脑能读屏幕", t.XIAOMI_INPUT)
        self.assertIn("拔掉数据线重新插上", t.XIAOMI_INPUT)
        self.assertIn("请拔插数据线", t.UI_INSTALL_FAILED)

    def test_engine_click_message_follows_the_host(self):
        # 点击原语在观测基座里取整句常量（ADR-0033）；手机版每次执行前清掉 tool/ 模块再导入，用新进程模拟
        code = ("import sys; sys.path.insert(0, 'tool'); "
                "from phone import screen; print(screen.TAPPED)")
        env = dict(os.environ, AAC_HOST="phone", PYTHONIOENCODING="utf-8")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "本 App 发出的点击", out.stderr[-800:])


class DisconnectHintTests(unittest.TestCase):
    """断线排查说明也按宿主取词：手机版没有电脑、数据线，也没有 USB 授权框。"""

    def tearDown(self):
        reload_for(None)

    def constants(self, host):
        # 常量在导入时定死：用新进程模拟手机版的重新导入，别在进程内 reload（见 reload_for 的说明）
        code = ("import sys; sys.path.insert(0, 'tool'); import adb_link; "
                "print(adb_link.HINT); print('>>>'); print(adb_link.REPEAT)")
        env = {k: v for k, v in os.environ.items() if k != "AAC_HOST"}
        if host:
            env["AAC_HOST"] = host
        env["PYTHONIOENCODING"] = "utf-8"
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        hint, repeat = out.stdout.split(">>>")
        return hint, repeat.strip()

    def test_phone_hint_points_at_the_app_not_the_computer(self):
        hint, repeat = self.constants("phone")
        for word in ("电脑", "数据线", "USB"):
            self.assertNotIn(word, hint)
        self.assertIn("Shizuku", hint)
        self.assertNotIn("电脑", repeat)

    def test_desktop_hint_is_unchanged(self):
        """旧树也绿，守的是不回退：桌面版的断线排查说明逐字不变。"""
        hint, repeat = self.constants(None)
        self.assertIn("退出电脑上的手机助手类软件", hint)
        self.assertIn("换原装或可传数据的线", hint)
        self.assertEqual(repeat, "手机和电脑的 adb 连接已断开，本段跳过；原因和排查办法见第一次报错")


class KeepAwakeTests(unittest.TestCase):
    def reader(self, value="0", writes=None):
        # 写不进去：读回来始终是原值（vivo 经无线调试，put 被静默忽略）
        def shell(cmd):
            if writes is not None and " put " in cmd:
                writes.append(cmd)
            return types.SimpleNamespace(output=value + "\n")
        return types.SimpleNamespace(shell=shell)

    def run_keep_awake(self, on_phone, value="0", writes=None):
        out = io.StringIO()
        with patch.object(chan, "ON_PHONE", on_phone), contextlib.redirect_stdout(out):
            old = chan.keep_awake(self.reader(value, writes))
        return old, out.getvalue()

    def test_wider_value_counts_as_on(self):
        # 「保持唤醒」写的是 15（多一个底座位），比 7 宽：不写、不报没设上，收尾按 15 改回
        writes = []
        old, printed = self.run_keep_awake(False, "15", writes)
        self.assertEqual((old, printed, writes), ("15", "", []))

    def test_partial_value_is_not_enough(self):
        old, printed = self.run_keep_awake(False, "3")       # 只有交流和 USB，无线充电时会息屏
        self.assertIn("插电常亮没有设上", printed)

    def test_phone_does_not_blame_the_cable(self):
        old, printed = self.run_keep_awake(True)
        self.assertEqual(old, "0")
        self.assertEqual(printed, "")

    def test_desktop_still_warns(self):
        old, printed = self.run_keep_awake(False)
        self.assertEqual(old, "0")
        self.assertIn("插电常亮没有设上", printed)


class LinkLostTests(unittest.TestCase):
    def skipped_tails(self, text):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory, runner=FakeRunner(
                spawns=[FakeProc('#aac:event {"kind": "link_lost"}\n' + adb_link.HINT + "\n", rc=1)]))
            api.job = job_stub()
            with patch.object(app, "adb_present", return_value=False), patch.object(app, "LINK_LOST", text):
                api._work([app.Task("关闭营销通知", "run.py", ["-s", "test", "x"]),
                           app.Task("收尾", "run.py", ["-s", "test", "finish"], always_run=True)])
            return [r["tail"] for r in api.job.results if r.get("skipped")], "\n".join(api.job.lines)

    def test_skipped_steps_use_the_host_wording(self):
        tails, lines = self.skipped_tails(PHONE_LINK_LOST)
        self.assertEqual(tails, [[PHONE_LINK_LOST]])
        self.assertNotIn("手机和电脑已断开", lines)

    def test_desktop_default_is_unchanged(self):
        self.assertEqual(app.LINK_LOST, "手机和电脑已断开，这一步没有执行。重新连接手机后点「重试」。")


class PhoneBootTests(unittest.TestCase):
    """boot() 要在导入 gui/app.py 之前设宿主标记，并换掉断开文案。"""

    def test_boot_sets_host_and_link_lost(self):
        # 解析 boot() 只此一处：新增的模块常量覆盖也挂在这里（#747）
        path = ROOT / "android/app/src/main/python/aac_android/main.py"
        boot = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                    if isinstance(n, ast.FunctionDef) and n.name == "boot")
        env_set = link_lost = tap_refused = engine_host = None
        for node in ast.walk(boot):
            if not isinstance(node, ast.Assign):
                continue
            target = node.targets[0]
            if (isinstance(target, ast.Subscript) and ast.unparse(target) == "os.environ['AAC_HOST']"
                    and isinstance(node.value, ast.Constant)):
                env_set = (node.lineno, node.value.value)
            if not isinstance(target, ast.Attribute):
                continue
            name = ast.unparse(target)
            if name == "app.LINK_LOST":
                link_lost = node.value.value
            elif name == "app.TAP_REFUSED":        # #747：诊断里的「点击被拒」那一栏
                tap_refused = node.value.value
            elif name == "app.ENGINE_HOST":        # #747：child_env() 只认它，不认继承来的 AAC_HOST
                engine_host = node.value.value
        imports_app = min(n.lineno for n in ast.walk(boot)
                          if isinstance(n, ast.Import) and any(a.name == "app" for a in n.names))
        self.assertEqual(env_set[1], "phone")
        self.assertLess(env_set[0], imports_app)
        self.assertEqual(link_lost, PHONE_LINK_LOST)
        # 断线判 failed，结果页那个按钮叫「重新开始」；「再做一次」只在 outcome == Ok 分支（ui/RunScreens.kt）
        self.assertIn("重新开始", link_lost)
        self.assertNotIn("再做一次", link_lost)
        self.assertEqual(tap_refused, "；本 App 的点击被拒（未开 USB 调试安全设置）")
        self.assertEqual(engine_host, "phone")


# ---------- 来源 tests/test_reader_failure_731.py ----------
#   #731：手机版中途读屏失败要有人话收场，且不再改「插电常亮」（#728 之后亮屏由 App 自己保证）。


ITEMS_731 = [("com.a", "promo", "营销通知"), ("com.b", "news", "资讯推送"), ("com.c", "deal", "优惠活动")]
DATA_731 = {(pk, cid): (label, 3, False) for pk, cid, label in ITEMS_731}


def reader_731(value="0", commands=None):
    """只回答 `settings get` 的假读屏：记下每条命令，验证有没有人偷偷写设置。"""
    def shell(cmd, timeout=None):
        if commands is not None:
            commands.append(cmd)
        return types.SimpleNamespace(output=value + "\n")
    return types.SimpleNamespace(shell=shell)


class StayOnWriteTests(unittest.TestCase):
    def call(self, on_phone, value="0"):
        commands = []
        with patch.object(chan, "ON_PHONE", on_phone), contextlib.redirect_stdout(io.StringIO()) as out:
            old = chan.keep_awake(reader_731(value, commands))
        return old, commands, out.getvalue()

    def test_phone_never_writes_the_setting(self):
        old, commands, printed = self.call(True)
        self.assertEqual(commands, ["settings get global stay_on_while_plugged_in"])
        self.assertEqual(old, "0")
        self.assertEqual(printed, "")

    def test_phone_returns_the_old_value_like_the_desktop(self):
        """手机版照桌面版的口径给原值：调用方拿到的还是那个数字字符串。"""
        old, _, _ = self.call(True, "15")
        self.assertEqual(old, "15")

    def test_desktop_still_turns_it_on(self):
        """旧树也绿，守的是不回退：桌面版照旧写 7。"""
        _, commands, _ = self.call(False)
        self.assertIn("settings put global stay_on_while_plugged_in 7", commands)


class BatchRestoreTests(unittest.TestCase):
    """批尾的「改回原值」同样不能在手机版写出去：手机版根本没改过。"""

    def run_off(self, on_phone):
        commands = []
        phone = phone_mock(wait_unlocked=Mock(return_value=True))
        with patch.object(chan, "load", return_value=ITEMS_731), \
                patch.object(chan, "parse", return_value=(DATA_731, {})) as parse, \
                patch.object(chan, "ShellPhone", return_value=reader_731("0", commands)), \
                patch.object(chan, "Phone", return_value=phone) as make_phone, \
                patch.object(chan, "toggle", return_value=chan.Outcome(chan.DONE)) as toggle, \
                patch.object(chan, "ON_PHONE", on_phone), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):      # 复查时仍是 ON：这一步本来就算失败
                chan.run(["-s", "test", "off", "x.tsv"])
        parse.assert_called()
        make_phone.assert_called_once()
        self.assertEqual(toggle.call_count, len(ITEMS_731))
        return commands

    def test_phone_batch_leaves_the_setting_alone(self):
        commands = self.run_off(True)
        self.assertEqual([c for c in commands if "stay_on" in c],
                         ["settings get global stay_on_while_plugged_in"])

    def test_desktop_batch_turns_it_on_and_back(self):
        """旧树也绿，守的是不回退：桌面版照旧「批开头打开 → 批尾改回」。"""
        commands = self.run_off(False)
        self.assertEqual([c for c in commands if "stay_on" in c],
                         ["settings get global stay_on_while_plugged_in",
                          "settings put global stay_on_while_plugged_in 7",
                          "settings get global stay_on_while_plugged_in",
                          "settings put global stay_on_while_plugged_in 0"])


class RecipeStayOnTests(unittest.TestCase):
    """机型脚本这一路（run.py recipe）原来也是开头写 7、finally 改回。"""

    def recipe(self, on_phone):
        commands = []
        with patch.object(sys, "argv", ["run.py", "-s", "test", "recipe"]), \
                patch.object(run, "info", return_value={"brand": "Xiaomi", "model": "M", "build": "OS4.0"}), \
                patch.object(run, "recipe_for", return_value=("recipe.py", None)), \
                patch.object(run, "recipe_meta", return_value={"build": "OS4.0"}), \
                patch.object(run, "build_ok", return_value=True), \
                patch.object(run, "wait_unlocked", return_value=True), \
                patch.object(run, "sh", side_effect=lambda s, c, *a, **k: commands.append(c) or "15"), \
                patch.object(run, "py", return_value=0), \
                patch.object(run, "ON_PHONE", on_phone):
            self.assertEqual(run.main(), 0)
        return [c for c in commands if "stay_on" in c]

    def test_phone_recipe_leaves_the_setting_alone(self):
        self.assertEqual(self.recipe(True), [])

    def test_desktop_recipe_turns_it_on_and_back(self):
        """旧树也绿，守的是不回退：桌面版照旧开头写 7、finally 改回原值。"""
        self.assertEqual(self.recipe(False), ["settings get global stay_on_while_plugged_in",
                                              "settings put global stay_on_while_plugged_in 7",
                                              "settings put global stay_on_while_plugged_in 15"])


class FinishStayOnTests(unittest.TestCase):
    """收尾这一步在手机版也没有「改回插电常亮」这回事。"""

    def finish(self, on_phone):
        commands = []
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            snap = Backups(root).create("M")
            Path(snap, "stay_on.txt").write_text("15", encoding="utf-8")
            with patch.object(run, "BACKUPS", root), \
                    patch.object(run, "info", return_value={"model": "M"}), \
                    patch.object(run, "sh", side_effect=lambda s, c, *a, **k: commands.append(c) or "0"), \
                    patch.object(run, "ON_PHONE", on_phone), \
                    contextlib.redirect_stdout(out):
                run.cmd_finish("test", [])
        return commands, out.getvalue()

    def test_phone_finish_says_nothing_about_it(self):
        commands, printed = self.finish(True)
        self.assertEqual([c for c in commands if "stay_on" in c], [])
        self.assertNotIn("插电常亮", printed)
        self.assertIn("input keyevent HOME", commands)      # 收尾其余动作照旧

    def test_desktop_finish_still_puts_the_snapshot_value_back(self):
        """旧树也绿，守的是不回退：桌面版照旧按快照改回并说一句。"""
        commands, printed = self.finish(False)
        self.assertEqual([c for c in commands if "stay_on" in c],
                         ["settings put global stay_on_while_plugged_in 15"])
        self.assertIn("插电常亮已改回 15", printed)


# ---------- #747：手机版界面上残留的桌面说法 ----------
DESKTOP_REFUSED = "；电脑点击被拒（未开 USB 调试安全设置）"
PHONE_REFUSED = "；本 App 的点击被拒（未开 USB 调试安全设置）"
PHONE_CLICK = "本 App 发出的点击"


class DiagnosticsWordingTests(unittest.TestCase):
    """手机版 Compose 会把整段诊断复制与上报，里面不能有「电脑」。"""

    def report(self, refused):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            api.last_status = {"info": {"brand": "Xiaomi", "name": "Xiaomi 13", "model": "M154FF",
                                        "os": "OS3.0.308.0", "build": "OS3.0.308.0", "android": "16"},
                               "input_blocked": True}
            with patch.object(app, "TAP_REFUSED", refused), \
                 patch.object(app, "other_adb", return_value=[]), \
                 patch.object(app, "usb_phones", return_value=[]):
                return api.diagnostics()

    def test_phone_report_does_not_blame_the_computer(self):
        report = self.report(PHONE_REFUSED)
        self.assertIn(PHONE_REFUSED, report)
        self.assertNotIn("电脑点击", report)

    def test_desktop_report_is_unchanged(self):
        """旧树也绿，守的是不回退：桌面版的这一行逐字不变。"""
        self.assertEqual(app.TAP_REFUSED, DESKTOP_REFUSED)
        self.assertIn("锁屏：否" + DESKTOP_REFUSED, self.report(app.TAP_REFUSED))


class ClickerTests(unittest.TestCase):
    """`{CLICKER}点击` 在手机版会拼成「本 App点击」，宿主常量直接给出整句。"""

    def host_constant(self, name, host):
        # 常量在导入时定死：手机版每次执行前清掉 tool/ 模块再导入，用新进程模拟
        code = f"import sys; sys.path.insert(0, 'tool'); import host; print(host.{name})"
        env = {k: v for k, v in os.environ.items() if k != "AAC_HOST"}
        if host:
            env["AAC_HOST"] = host
        env["PYTHONIOENCODING"] = "utf-8"
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        return out.stdout.strip().splitlines()[-1]

    def test_clicker_phrase_follows_the_host(self):
        self.assertEqual(self.host_constant("CLICK", "phone"), PHONE_CLICK)
        self.assertEqual(self.host_constant("CLICK", None), "电脑点击")
        self.assertEqual(self.host_constant("TAPPED", "phone"), PHONE_CLICK)
        self.assertEqual(self.host_constant("TAPPED", None), "电脑发出的点击")


class BlockedMessageTests(unittest.TestCase):
    """点击被系统拒绝时抛出的整句：手机版不能拼成「本 App发出的点击」。"""

    def message(self, tapped):
        p = phone_stub(W=1000, H=2000)
        p.reader = types.SimpleNamespace(
            window_size=lambda: (1000, 2000),
            shell=lambda command, timeout=None: types.SimpleNamespace(output="INJECT_EVENTS"))
        with patch.object(phone_screen, "TAPPED", tapped), patch.object(phone_screen, "XIAOMI_INPUT", ""):
            with self.assertRaises(RuntimeError) as caught:
                p.click(10, 20)
        return str(caught.exception)

    def test_phone_message_reads_as_a_sentence(self):
        self.assertEqual(self.message(PHONE_CLICK), "系统拒绝了" + PHONE_CLICK + "。")

    def test_desktop_message_is_unchanged(self):
        """旧树也绿，守的是不回退：桌面版的这一句逐字不变。"""
        self.assertEqual(self.message("电脑发出的点击"), "系统拒绝了电脑发出的点击。")


class HostCheckLineTests(unittest.TestCase):
    """`check` 那一行改用宿主常量。"""

    INFO = {"brand": "Xiaomi", "model": "M154FF", "name": "Xiaomi 13",
            "build": "OS3.0.308.0", "os": "OS3.0.308.0", "android": "16"}

    def check(self, click=None):
        out = io.StringIO()
        stubs = [patch.object(run, "info", return_value=dict(self.INFO)),
                 patch.object(run, "recipe_for", return_value=(None, False)),
                 patch.object(run, "locked", return_value=False),
                 patch.object(run, "input_blocked", return_value=True),
                 patch.object(run, "ad_packages", return_value=[]),
                 patch.object(run, "quickapps", return_value=[]),
                 patch.object(run, "NEVER", set()), patch.object(run, "sh", return_value=""),
                 patch.object(sys, "argv", ["run.py", "-s", "test", "check"])]
        if click:
            stubs.append(patch.object(troubleshooting, "CLICK", click))
        with contextlib.ExitStack() as stack:
            for stub in stubs:
                stack.enter_context(stub)
            stack.enter_context(contextlib.redirect_stdout(out))
            run.main()
        return out.getvalue()

    def test_phone_line_reads_as_a_sentence(self):
        self.assertIn(PHONE_CLICK + "：被系统拒绝。", self.check(PHONE_CLICK))

    def test_desktop_line_is_unchanged(self):
        """旧树也绿，守的是不回退：桌面版的这一行逐字不变。"""
        self.assertIn("电脑点击：被系统拒绝。" + troubleshooting.XIAOMI_INPUT, self.check())


if __name__ == "__main__":
    unittest.main()
