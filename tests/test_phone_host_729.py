"""手机版宿主的说法（#729）：没有电脑和数据线，插电常亮也不是手机版的防锁屏办法（#728）。"""
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
from unittest.mock import patch

from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import chan_fast as chan
import troubleshooting
from fixtures import FakeProc, FakeRunner, job_stub

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
        # fast.py 在导入时取整句常量；手机版每次执行前清掉 tool/ 模块再导入，用新进程模拟
        code = "import sys; sys.path.insert(0, 'tool'); import fast; print(fast.TAPPED)"
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
                           app.Task("收尾", "run.py", ["-s", "test", "finish"])])
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


if __name__ == "__main__":
    unittest.main()
