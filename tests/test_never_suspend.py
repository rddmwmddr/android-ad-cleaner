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
             patch.object(run, "sh_all") as shell, \
             contextlib.redirect_stderr(err), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                run.main()
        return raised.exception.code, err.getvalue(), shell

    def test_refusal_does_not_touch_the_phone(self):
        code, _, shell = self.suspend("com.oplus.appdetail")
        # sys.exit(字符串) 的 code 就是那条消息本身（进程退出码 1）：只断言「非 0」+ 点到了包名
        self.assertNotEqual(code, 0)
        self.assertIn("com.oplus.appdetail", str(code))
        shell.assert_not_called()

    def test_one_protected_package_blocks_the_whole_batch(self):
        """混着广告包一起提交时，广告包也不能挂：整批拒绝，不在手机上留半截改动。"""
        code, _, shell = self.suspend("com.opos.ads", "com.oplus.appdetail")
        self.assertNotEqual(code, 0)
        self.assertIn("com.oplus.appdetail", str(code))
        shell.assert_not_called()


if __name__ == "__main__":
    unittest.main()
