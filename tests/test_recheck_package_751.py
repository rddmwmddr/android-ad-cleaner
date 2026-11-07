"""#751 收尾复查的「仍开着」与 verify 逐项行带上包名：同名渠道分属不同 App 时读日志能分清。

结局、计数、退出码与两份汇总行一个字不动 —— 这里只测这两行的取证部分。
"""
import contextlib
import io
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声

from fixtures import fake_adb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan

ITEMS = [("com.a", "promo", "运营消息"), ("com.b", "promo", "运营消息")]
ON = {(pk, cid): (label, 3, False) for pk, cid, label in ITEMS}


def dump():
    return """PackagePreferences:
      AppSettings: com.a importance=DEFAULT
        NotificationChannel{mId='promo', mName=运营消息, mDescription=null, mImportance=3, mDeleted=false}
      AppSettings: com.b importance=DEFAULT
        NotificationChannel{mId='promo', mName=运营消息, mDescription=null, mImportance=3, mDeleted=false}
    """


class RecheckPackageTests(unittest.TestCase):
    def test_still_on_line_names_the_package(self):
        # 0.4.0 上报 e3334810：27 项里 24 行是同一个「运营消息」，事后看不出是哪些 App
        phone = Mock(wait_unlocked=Mock(return_value=True))
        with patch.object(chan, "load", return_value=ITEMS), \
             patch.object(chan, "parse", return_value=(ON, {})), \
             patch.object(chan, "Phone", return_value=phone), \
             patch.object(chan, "keep_awake", return_value=None), \
             patch.object(chan, "appops_mode", return_value="default"), \
             patch.object(chan, "toggle", return_value=chan.Outcome(chan.UNCHANGED, "点击后渠道状态未改变")), \
             patch.object(chan, "pause_point"), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "t", "off", "x.tsv"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as stop:
                chan.main()
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("仍开着：运营消息（com.a）", out.getvalue())
        self.assertIn("仍开着：运营消息（com.b）", out.getvalue())
        self.assertIn("营销渠道仍开着: 2 个", out.getvalue())

    def test_verify_line_names_the_package(self):
        fake_adb(self)
        result = types.SimpleNamespace(returncode=0, stdout=dump(), stderr="")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.a\tpromo\t运营消息\ncom.b\tpromo\t运营消息\n", encoding="utf-8")
            with patch.object(subprocess, "run", return_value=result), \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "t", "verify", str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                chan.main()
        self.assertIn("ON   运营消息（com.a）", out.getvalue())
        self.assertIn("ON   运营消息（com.b）", out.getvalue())
        self.assertIn("营销渠道仍开着: 2 个", out.getvalue())

    def test_verify_line_keeps_the_protected_note_with_the_package(self):
        # 受保护备注并进包名括号，改的就是这一句；受保护的仍不计入「仍开着」
        fake_adb(self)
        body = """PackagePreferences:
      AppSettings: com.a importance=DEFAULT
        NotificationChannel{mId='spot', mName=找机位通知, mDescription=null, mImportance=3, mDeleted=false}
    """
        result = types.SimpleNamespace(returncode=0, stdout=body, stderr="")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.a\tspot\t找机位通知\n", encoding="utf-8")
            with patch.object(subprocess, "run", return_value=result), \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "t", "verify", str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                chan.main()
        self.assertIn("ON   找机位通知（com.a，受保护，不参与营销关闭）", out.getvalue())
        self.assertIn("营销渠道仍开着: 0 个", out.getvalue())


if __name__ == "__main__":
    unittest.main()
