"""#459 前台服务的常驻通知渠道：dump 行带 mFgServiceShown=true 时不进扫描清单。

字段属于 NotificationChannel，不属于 NotificationRecord：AOSP 由
getFieldsString() 打在 PackagePreferences: 段那行 NotificationChannel{...} 上，
也就是 parse() 已经在逐行解析的行。粘性——渠道发过一次前台服务通知就永久为
true，之后转成纯营销仍会被排除，这条代价已确认接受（见 ADR-0006 增补）。
"""
import contextlib
import io
import os
os.environ.setdefault("AAC_NO_SOUND", "1")
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fixtures import fake_adb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan

PACKAGE = "com.freeme.cloud.launcher.recommendationservice"
CHANNEL_ID = "necessary_splash_start_channel"


def channel_line(cid, name, importance=3, deleted="false", fg=None, field="mFgServiceShown"):
    # 真机行的字段顺序：mImportance → … → 前台服务标记 → … → mDeleted。
    mark = "" if fg is None else f", {field}={fg}"
    return (f"NotificationChannel{{mId='{cid}', mName={name}, mDescription=null,"
            f" mImportance={importance}{mark}, mBypassDnd=false, mDeleted={deleted}}}")


def dump(*lines):
    return ("PackagePreferences:\n"
            f"      AppSettings: {PACKAGE} importance=DEFAULT\n"
            + "".join(f"        {line}\n" for line in lines))


class ScanTests(unittest.TestCase):
    def setUp(self):
        fake_adb(self)

    def scan(self, output):
        result = SimpleNamespace(returncode=0, stdout=output, stderr="")
        with patch.object(subprocess, "run", return_value=result), \
             patch.object(chan, "app_labels", return_value={}) as labels, \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "scan"]), \
             contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            chan.main()
        labels.assert_called_once()
        return out.getvalue(), err.getvalue()

    def test_foreground_service_channel_is_not_listed(self):
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务", fg="true")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)
        self.assertNotIn(CHANNEL_ID, err)

    def test_line_without_the_field_keeps_current_behavior(self):
        # OEM 剥掉字段时退回现状：照常列入清单，stderr 不多行
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务")))
        self.assertEqual(out, f"{PACKAGE}\t{CHANNEL_ID}\t应用推荐服务\n")
        self.assertEqual(err, "")

    def test_field_false_does_not_exclude(self):
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务", fg="false")))
        self.assertEqual(out, f"{PACKAGE}\t{CHANNEL_ID}\t应用推荐服务\n")
        self.assertEqual(err, "")

    def test_foreground_service_outranks_ad_network_hit(self):
        # 同一渠道同时命中广告网络：按前台服务排除，只计一次
        out, err = self.scan(dump(channel_line("TencentAdNetCH1", "频道", fg="true")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)
        self.assertIn("另有 1 个", err)
        self.assertEqual(err.count("另有"), 1)

    def test_android14_renamed_field_is_recognised(self):
        # Android 14 起框架把字段改名，语义与粘性不变；只认老名字会让这条排除在新系统上静默失效
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务", fg="true",
                                               field="mUserVisibleTaskShown")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)

    def test_foreground_service_is_counted_before_truncated_id(self):
        out, err = self.scan(dump(channel_line("com.se...", "活动优惠", fg="true")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)
        self.assertNotIn("缩略", err)

    def test_foreground_service_is_counted_before_system_locked(self):
        locked = ("PackagePreferences:\n"
                  f"      AppSettings: {PACKAGE} importance=DEFAULT fixedImportance=true\n"
                  "        " + channel_line(CHANNEL_ID, "活动优惠", fg="true")
                  .replace("mBypassDnd=false", "mBypassDnd=false, mBlockableSystem=false") + "\n")
        out, err = self.scan(locked)
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)
        self.assertNotIn("系统锁定", err)

    def test_channel_that_would_not_be_listed_is_not_counted(self):
        # 服务类渠道本来就不进清单，不该算进「前台服务渠道」的数字
        out, err = self.scan(dump(channel_line(CHANNEL_ID, "应用推荐服务", fg="true"),
                                  channel_line("system_channel", "系统消息", fg="true")))
        self.assertEqual(out, "")
        self.assertIn("另有 1 个前台服务渠道未列入清单", err)


class ClassifyTests(unittest.TestCase):
    def test_default_judgement_is_unchanged(self):
        default = chan.classify("活动优惠", "promo")
        self.assertFalse(default.foreground_service)
        self.assertTrue(default.marketing_candidate)

    def test_foreground_service_keeps_the_marketing_signal(self):
        # 排除由调用方合成（同 scan_excluded / truncated 的写法），判定本身不抹掉营销信号
        judgement = chan.classify("活动优惠", "promo", foreground_service=True)
        self.assertTrue(judgement.foreground_service)
        self.assertTrue(judgement.marketing_candidate)


if __name__ == "__main__":
    unittest.main()
