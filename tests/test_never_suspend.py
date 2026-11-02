"""NEVER 保护集：挂了会坏功能的包，`run.py suspend` 必须整批拒绝、不能落一条命令到手机上。

`NEVER` 只在 `run.py suspend` 这一条路上生效；绕过它直接 `pm suspend` 不受保护。
所以这里的断言要盯住两件事：包里在不在集合里，以及拒绝时有没有真的去执行。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run


class NeverSetTests(unittest.TestCase):
    def test_install_chain_package_is_protected(self):
        """com.oplus.appdetail 冻结后第三方安装永久卡在「正在安装」（RMX3700 实测）。"""
        self.assertIn("com.oplus.appdetail", run.NEVER)

    def test_protected_packages_stay_protected(self):
        for package in ["com.heytap.quicksearchbox", "com.coloros.assistantscreen",
                        "com.android.systemui", "com.vivo.systemuiplugin",
                        "com.heytap.market", "com.xiaomi.market", "com.hihonor.appmarket"]:
            self.assertIn(package, run.NEVER)


class SuspendRefusalTests(unittest.TestCase):
    def suspend(self, *packages):
        err = io.StringIO()
        with patch.object(sys, "argv", ["run.py", "-s", "test", "suspend", *packages]), \
             patch.object(run, "adb"), \
             patch.object(run, "sh_all") as shell, \
             contextlib.redirect_stderr(err), \
             contextlib.redirect_stdout(io.StringIO()):
            code = run.main()
        return code, err.getvalue(), shell

    def test_refusal_does_not_touch_the_phone(self):
        code, message, shell = self.suspend("com.oplus.appdetail")
        self.assertEqual(code, 1)
        self.assertIn("com.oplus.appdetail", message)
        shell.assert_not_called()

    def test_one_protected_package_blocks_the_whole_batch(self):
        """混着广告包一起提交时，广告包也不能挂：整批拒绝，不在手机上留半截改动。"""
        code, message, shell = self.suspend("com.opos.ads", "com.oplus.appdetail")
        self.assertEqual(code, 1)
        self.assertIn("com.oplus.appdetail", message)
        shell.assert_not_called()


class CheckReportsFrozenTests(unittest.TestCase):
    """`check` 要说出「这些功能包被别处冻了」，否则跑机型脚本只会看到「没找到入口」。"""

    def run_check(self, frozen):
        phone = {"brand": "realme", "model": "RMX3700", "name": "真我GT Neo5 SE",
                 "build": "RMX3700_16.0.5.1300(CN01)", "os": "", "android": "16"}
        out = io.StringIO()
        with patch.object(sys, "argv", ["run.py", "-s", "test", "check"]), \
             patch.object(run, "adb"), \
             patch.object(run, "info", return_value=phone), \
             patch.object(run, "recipe_for", return_value=(None, False)), \
             patch.object(run, "locked", return_value=False), \
             patch.object(run, "input_blocked", return_value=False), \
             patch.object(run, "ad_packages", return_value=[]), \
             patch.object(run, "suspended", side_effect=lambda serial, pkg: pkg in frozen), \
             patch.object(run, "quickapps", return_value=[]), \
             patch.object(run, "sh", return_value="0"), \
             contextlib.redirect_stdout(out):
            code = run.main()
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_frozen_function_package_is_reported(self):
        text = self.run_check({"com.heytap.quicksearchbox"})
        self.assertIn("被挂起的功能包", text)
        self.assertIn("com.heytap.quicksearchbox", text)
        self.assertIn("unsuspend", text)

    def test_nothing_frozen_prints_nothing_extra(self):
        self.assertNotIn("被挂起的功能包", self.run_check(set()))


if __name__ == "__main__":
    unittest.main()
