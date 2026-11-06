"""发送进度类渠道（WhatsApp「发送影音内容」）不进营销候选：名字带「内容」曾被默认勾选。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))

import channel_policy  # noqa: E402


class SendProgressTest(unittest.TestCase):
    def test_send_progress_is_excluded(self):
        for name in ("发送影音内容", "發送影音內容"):
            self.assertTrue(channel_policy.classify(name).scan_excluded, name)

    def test_marketing_content_still_listed(self):
        self.assertFalse(channel_policy.classify("内容资讯").scan_excluded)


if __name__ == "__main__":
    unittest.main()
