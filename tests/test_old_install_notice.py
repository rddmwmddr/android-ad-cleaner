"""免安装版启动时提示旧名安装还在（#872）：文案、每条出路、同一版本只提示一次。

注册表判定本身在 `test_win_preflight.py` 里用注入的 read 测；这里只测客户端怎么把它变成
一次性的界面提示，所以 `old_install_present` 直接换掉。
"""
import tempfile
import unittest
from unittest.mock import patch

from gui import app


class OldInstallNoticeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.api = app.Api(self._tmp.name, adb=None)

    def notice(self, present=True):
        with patch.object(app.winpreflight, "old_install_present", return_value=present):
            return self.api.old_install_notice()

    def test_an_old_install_gets_a_notice(self):
        self.assertTrue(self.notice()["text"])

    def test_the_notice_names_both_ways_out_and_says_backups_survive(self):
        text = self.notice()["text"]
        self.assertIn("安装版", text)
        self.assertIn("卸载", text)
        self.assertIn("备份", text)
        self.assertIn("0.3.2 及更早", text)

    def test_no_old_install_gets_no_notice(self):
        self.assertEqual(self.notice(present=False), {})

    def test_dismissing_stops_the_notice_for_this_version(self):
        self.assertTrue(self.api.dismiss_old_install())
        self.assertEqual(self.notice(), {})

    def test_another_version_asks_once_again(self):
        self.api.dismiss_old_install()
        self.api.data.put_setting("old_install_noticed", "0.3.2")
        self.assertTrue(self.notice()["text"])

    def test_a_registry_that_cannot_be_read_keeps_the_client_usable(self):
        def denied(*_args):
            raise PermissionError("拒绝访问")

        with patch.object(app.winpreflight, "read_value", denied):
            self.assertEqual(self.api.old_install_notice(), {})
        self.assertEqual(self.api.env()["version"], app.VERSION)

    def test_the_marker_lives_in_client_data_not_the_registry(self):
        self.api.dismiss_old_install()
        self.assertEqual(app.ClientData(self._tmp.name).setting("old_install_noticed"), app.VERSION)


if __name__ == "__main__":
    unittest.main()
