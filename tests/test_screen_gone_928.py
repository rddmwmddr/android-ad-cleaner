"""#928：后台屏没了（读屏打到的显示不存在）要有人话收场，不能带着 Python 堆栈退出。"""
import contextlib
import io
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))
import adb_link
import chan_fast as chan
import fast
from phone import connection as phone_connection
from aac_android import screen

NPE_READ = "显示 7 不存在（这块屏已经没了）"
ITEMS = [("com.a", "promo", "营销通知")]
DATA = {(pk, cid): (label, 3, False) for pk, cid, label in ITEMS}


def reader():
    """只回答 `settings get` 的假读屏：这条路上不该有任何写入。"""
    return types.SimpleNamespace(shell=lambda cmd, timeout=None: types.SimpleNamespace(output="0\n"))


class ClassifyTests(unittest.TestCase):
    """屏没了既不是断线，也不是「读屏慢一次」：它有自己的那一句（#928）。"""

    def test_both_wordings_are_the_same_outcome(self):
        for message in (NPE_READ, screen.LOST,
                        "java.lang.IllegalStateException: 显示 7 不存在（这块屏已经没了）"):
            self.assertTrue(adb_link.screen_gone(message).startswith(adb_link.SCREEN_GONE_STEP), message)

    def test_other_read_failures_are_not_screen_gone(self):
        for message in ("读屏请求超时（30 秒）", "命令服务断开", "UiAutomation 被别的无障碍服务占用"):
            self.assertIsNone(adb_link.screen_gone(message), message)

    def test_the_entry_message_carries_the_original_error(self):
        message = adb_link.failure_message(fast.u2.exceptions.UiAutomationError(NPE_READ), "test")
        self.assertTrue(message.startswith(adb_link.SCREEN_GONE_STEP), message)
        self.assertIn(NPE_READ, message)            # 社区上报看这段输出，得能看出是哪块屏

    def test_the_connect_sentence_never_claims_a_switch_was_clicked_mid_run(self):
        """段中途屏消失时前面几段可能已经改过开关，不能说「本次未点击开关」（#928 审查）。"""
        self.assertNotIn("未点击", adb_link.SCREEN_GONE_STEP)
        self.assertIn("未点击", adb_link.SCREEN_GONE_CONNECT)

    def test_a_gone_screen_is_still_not_a_disconnect(self):
        """屏没了通道还在：不能报成断线，后面的段也不该被标成跳过（#731 的口径）。

        旧树也绿，守的是不回退：新加的这一族不能被并进 LIB_GONE。"""
        self.assertFalse(adb_link.lib_gone(NPE_READ))
        self.assertFalse(adb_link.lib_gone(screen.LOST))


class EntryTests(unittest.TestCase):
    """两个脚本入口都只报一句人话：屏没了不该以 Python 堆栈收场。

    与 test_reader_failure_731 的入口用例分开：那边守「慢一次」，这边守「屏没了」。
    """

    def test_chan_fast_exits_with_one_sentence(self):
        out = io.StringIO()
        with patch.object(chan, "run", side_effect=fast.u2.exceptions.UiAutomationError(screen.LOST)), \
                patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "verify", "x.tsv"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                chan.main()
        self.assertTrue(str(caught.exception.code).startswith(f"✗ {adb_link.SCREEN_GONE_STEP}"))
        self.assertNotIn("Traceback", out.getvalue())

    def test_chan_fast_survives_a_gone_screen_raised_from_the_batch(self):
        """真实路径：段中途新建 Phone 时屏已经没了，异常从 run() 里穿到 main() 的收场。"""
        out = io.StringIO()
        gone = fast.u2.exceptions.UiAutomationError(NPE_READ)
        with patch.object(chan, "load", return_value=ITEMS), \
                patch.object(chan, "parse", return_value=(DATA, {})), \
                patch.object(chan, "ShellPhone", return_value=reader()), \
                patch.object(chan, "keep_awake", return_value=None), \
                patch.object(chan, "Phone", side_effect=gone), \
                patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", "x.tsv"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                chan.main()
        self.assertTrue(str(caught.exception.code).startswith(f"✗ {adb_link.SCREEN_GONE_STEP}"))
        self.assertNotIn("Traceback", out.getvalue())

    def test_fast_exits_with_one_sentence(self):
        out = io.StringIO()
        gone = fast.u2.exceptions.UiAutomationError(NPE_READ)
        with patch.object(phone_connection, "connect", side_effect=gone), \
                patch.object(sys, "argv", ["fast.py", "-s", "test", "run", "recipe.py"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                fast.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn(f"✗ {adb_link.SCREEN_GONE_CONNECT}", out.getvalue())
        self.assertNotIn("Traceback", out.getvalue())


if __name__ == "__main__":
    unittest.main()
