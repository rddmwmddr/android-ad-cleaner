"""引擎事件的词表与解析（ADR-0004）：六个 kind、固定前缀、默认不发、坏行当没有，
写出的每一行中文原样可读并立即送达客户端。"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import events

# 冻结的期望词表：只遍历 events.KINDS 的话，删掉一个词连样例一起消失，用例照样绿。
FROZEN_KINDS = ("paused", "resumed", "locked", "ui_busy", "link_lost", "failed_steps")


def emit(kind, on, **data):
    out = io.StringIO()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AAC_EVENTS", None)
        if on:
            os.environ["AAC_EVENTS"] = "1"
        with redirect_stdout(out):
            events.emit(kind, **data)
    return out.getvalue()


class FlushCountingStdout(io.StringIO):
    """数 flush 次数：客户端按行读子进程的管道，`print(..., flush=True)` 是唯一让它立刻看见的手段。"""

    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


class EmitTests(unittest.TestCase):
    def test_silent_unless_the_client_asked_for_events(self):
        self.assertEqual(emit("paused", on=False), "")
        self.assertEqual(emit("paused", on=True), '#aac:event {"kind": "paused"}\n')

    def test_the_vocabulary_is_still_the_same_six(self):
        self.assertEqual(events.KINDS, FROZEN_KINDS)

    def test_every_kind_round_trips_through_parse(self):
        for kind in FROZEN_KINDS:
            line = emit(kind, on=True)
            self.assertEqual(events.parse(line.strip()), kind, kind)

    def test_a_kind_outside_the_vocabulary_is_a_programming_error(self):
        with self.assertRaises(ValueError) as caught:
            emit("paused_maybe", on=True)
        self.assertEqual(str(caught.exception), "未定义的事件：paused_maybe")

    def test_a_payload_rides_in_the_same_json_object(self):
        line = emit("failed_steps", on=True, steps=["桌面", "商店"])
        # 逐字钉住：载荷里的中文不转成 \uXXXX，客户端与上报日志直接读这一行。
        self.assertEqual(line, '#aac:event {"kind": "failed_steps", "steps": ["桌面", "商店"]}\n')
        self.assertEqual(events.parse(line.strip()), "failed_steps")
        self.assertEqual(events.parse_data(line.strip())["steps"], ["桌面", "商店"])

    def test_no_payload_keeps_the_line_byte_for_byte(self):
        # 旧树也绿：守的是给 emit() 加关键字载荷之后，没载荷的那几行不许变一个字节。
        self.assertEqual(emit("link_lost", on=True), '#aac:event {"kind": "link_lost"}\n')

    def test_an_event_line_is_flushed_as_soon_as_it_is_written(self):
        # 引擎的 stdout 接的是客户端的管道：不 flush 的话暂停 / 断线要等缓冲写满才送到。
        out = FlushCountingStdout()
        with patch.dict(os.environ, {"AAC_EVENTS": "1"}), redirect_stdout(out):
            events.emit("paused")
        self.assertEqual(out.flushes, 1)


class ParseTests(unittest.TestCase):
    def test_human_lines_are_not_events(self):
        lines = [
            "⏸ 已暂停：现在可以操作手机。操作完回到桌面、保持解锁，再点「继续」",
            "▶ 继续执行",
            "  ! 手机锁屏了：请解锁手机并保持亮屏，解锁后自动继续（最多等 90 秒）",
            "UIAUTOMATION_BUSY：手机读屏服务已被占用，本次未点击开关。",
            "手机和电脑的 adb 连接断开了，本步骤没有完成。请逐项排查后重试：",
            "  #aac:event 出现在行中间也不算",
            "",
        ]
        for line in lines:
            self.assertFalse(events.is_event(line), line)
            self.assertIsNone(events.parse(line), line)

    def test_broken_or_unknown_event_lines_mean_no_event(self):
        for line in ('#aac:event ', '#aac:event {', '#aac:event "paused"', '#aac:event {"kind": "mystery"}',
                     '#aac:event {"other": "paused"}', '#aac:event {"kind": "mystery", "steps": ["甲"]}'):
            self.assertTrue(events.is_event(line), line)
            self.assertIsNone(events.parse(line), line)
            self.assertIsNone(events.parse_data(line), line)


class PayloadTests(unittest.TestCase):
    def test_each_payload_line_is_flushed_as_soon_as_it_is_written(self):
        out = FlushCountingStdout()
        with patch.dict(os.environ, {"AAC_EVENTS": "1"}), redirect_stdout(out):
            events.payload("骨架 v1\n0 FrameLayout 0,0,100,100")
        self.assertEqual(out.flushes, 2)

    def test_a_line_that_is_not_a_payload_comes_back_untouched(self):
        # 不是载荷行（事件行、人话）一律原样交回，不能按前缀长度截掉一段。
        for line in ('#aac:event {"kind": "paused"}', "普通人话"):
            self.assertEqual(events.strip_payload(line), line, line)


if __name__ == "__main__":
    unittest.main()
