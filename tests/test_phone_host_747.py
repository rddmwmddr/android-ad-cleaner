"""手机版界面上残留的桌面说法（#747，跟进 #729）。

诊断里的「点击被拒」与点击被拒的整句都按宿主取词；桌面版逐字不变。
boot() 对这些模块常量的覆盖在 tests/test_phone_host_729.py 的 PhoneBootTests 里（解析 boot() 只此一处）。
"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import fast
import run
import troubleshooting
from fixtures import phone_stub

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
        p.reader = SimpleNamespace(
            window_size=lambda: (1000, 2000),
            shell=lambda command, timeout=None: SimpleNamespace(output="INJECT_EVENTS"))
        with patch.object(fast, "TAPPED", tapped), patch.object(fast, "XIAOMI_INPUT", ""):
            with self.assertRaises(RuntimeError) as caught:
                p.click(10, 20)
        return str(caught.exception)

    def test_phone_message_reads_as_a_sentence(self):
        self.assertEqual(self.message(PHONE_CLICK), "系统拒绝了" + PHONE_CLICK + "。")

    def test_desktop_message_is_unchanged(self):
        """旧树也绿，守的是不回退：桌面版的这一句逐字不变。"""
        self.assertEqual(self.message("电脑发出的点击"), "系统拒绝了电脑发出的点击。")


class CheckLineTests(unittest.TestCase):
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
