"""客户端只认引擎事件（ADR-0004）：事件行不进日志、不上报；人话本身不再改变状态。"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import io
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from fixtures import job_stub
from gui import app

PREFIX = "#aac:event "


def event(kind):
    return PREFIX + json.dumps({"kind": kind})


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.api = app.Api(self._dir.name)
        self.api.job = job_stub()

    def tearDown(self):
        self._dir.cleanup()

    def fake(self, output, rc=1):
        p = Mock(stdout=io.StringIO(output))
        p.wait.return_value = rc
        return p


class LogTests(Base):
    def test_event_lines_never_reach_the_log_or_the_report(self):
        self.api._log(event("paused"))
        self.api._log(event("link_lost"))
        self.api._log("普通人话")
        self.assertEqual(self.api.job.lines, ["普通人话"])
        self.assertNotIn("aac:event", json.dumps(self.api.report_payload(), ensure_ascii=False))

    def test_paused_then_resumed_follow_the_engine(self):
        with patch.object(app, "chime") as chime:
            self.api._log(event("paused"))
            self.assertTrue(self.api.job.paused)
            self.assertEqual(chime.call_count, 1)
            self.api._log(event("resumed"))
            self.assertFalse(self.api.job.paused)
            self.assertEqual(chime.call_count, 1)          # 继续不响

    def test_locked_rings_the_phone_owner(self):
        with patch.object(app, "chime") as chime:
            self.api._log(event("locked"))
        self.assertEqual(chime.call_count, 1)

    def test_the_human_sentence_alone_no_longer_changes_state(self):
        self.api._log("⏸ 已暂停：现在可以操作手机。")
        self.api._log("  ! 手机锁屏了：请解锁手机并保持亮屏，解锁后自动继续（最多等 90 秒）")
        self.assertFalse(self.api.job.paused)
        self.assertIn("⏸ 已暂停：现在可以操作手机。", self.api.job.lines)

    def test_a_broken_event_line_is_dropped_without_changing_state(self):
        self.api._log(PREFIX + "{not json")
        self.assertEqual(self.api.job.lines, [])
        self.assertFalse(self.api.job.paused)
        self.assertEqual(self.api.job.step_events, set())

    def test_unknown_kind_is_ignored(self):
        self.api._log(PREFIX + json.dumps({"kind": "mystery"}))
        self.assertEqual(self.api.job.lines, [])
        self.assertEqual(self.api.job.step_events, set())


class StepPauseTests(Base):
    def test_step_boundary_pause_rings_the_phone_free(self):
        started = []

        def proc(cmd, **kw):
            if not started:
                started.append(True)
                self.api.pause()                   # 第一步执行中点了暂停：暂停点不在这一步里
            return self.fake("", 0)
        with patch.object(app, "chime") as chime, \
             patch.object(app.subprocess, "Popen", side_effect=proc), \
             patch.object(app.time, "sleep", side_effect=lambda _s: self.api.resume()):
            self.api._work([app.Task("存改动前的快照", "run.py", ["-s", "t", "backup"]),
                            app.Task("收尾", "run.py", ["-s", "t", "finish"])])
        self.assertEqual(chime.call_count, 2)      # 暂停生效一次，执行结束一次

    def test_only_the_job_path_turns_events_on(self):
        with patch.dict(os.environ, {"AAC_EVENTS": "1"}):
            self.assertNotIn("AAC_EVENTS", app.child_env(None, "/tmp/backups"))
        seen = {}

        def proc(cmd, **kw):
            seen.update(kw["env"])
            return self.fake("", 0)
        with patch.object(app.subprocess, "Popen", side_effect=proc):
            self.api._work([app.Task("收尾", "run.py", ["-s", "t", "finish"])])
        self.assertEqual(seen.get("AAC_EVENTS"), "1")


class SkipTests(Base):
    def test_busy_skips_later_ui_steps_but_still_runs_cleanup(self):
        with patch.object(app.subprocess, "Popen", side_effect=[
                self.fake(event("ui_busy") + "\nUIAUTOMATION_BUSY：已占用\n"), self.fake("", 0)]) as popen:
            self.api._work([app.Task("广告开关", "run.py", [], uses_ui=True),
                            app.Task("通知", "chan_fast.py", uses_ui=True),
                            app.Task("收尾", "run.py")])
        self.assertEqual(popen.call_count, 2)
        self.assertTrue(self.api.job.results[1]["skipped"])
        self.assertEqual(self.api.job.results[2]["rc"], 0)

    def test_event_lines_stay_out_of_the_step_tail(self):
        # 前端 summarize() 在认不出模式时直接显示 tail 最后一行
        with patch.object(app.subprocess, "Popen", side_effect=[self.fake("人话\n" + event("ui_busy") + "\n")]):
            self.api._work([app.Task("广告开关", "run.py", [], uses_ui=True)])
        self.assertEqual(self.api.job.results[0]["tail"], ["人话"])

    def test_confirmed_disconnect_skips_the_rest_when_the_phone_is_really_gone(self):
        with patch.object(app, "adb_present", return_value=False), \
             patch.object(app.subprocess, "Popen", side_effect=[
                 self.fake(event("link_lost") + "\n手机和电脑的 adb 连接断开了\n")]) as popen:
            self.api._work([app.Task("广告开关", "run.py"), app.Task("收尾", "run.py")])
        self.assertEqual(popen.call_count, 1)
        self.assertTrue(self.api.job.results[1]["skipped"])
        self.assertEqual(self.api.last_error["operation"], "广告开关")
        self.assertIn("adb 连接断开了", self.api.last_error["detail"])

    def test_busy_text_without_an_event_skips_nothing(self):
        # 旧实现按文案判占用；事件制下同样的句子不该再改变后续步骤
        with patch.object(app.subprocess, "Popen", side_effect=[
                self.fake("UIAUTOMATION_BUSY：手机读屏服务已被占用\n"), self.fake("", 0)]) as popen:
            self.api._work([app.Task("广告开关", "run.py", [], uses_ui=True),
                            app.Task("通知", "chan_fast.py", uses_ui=True)])
        self.assertEqual(popen.call_count, 2)
        self.assertNotIn("skipped", self.api.job.results[1])

    def test_disconnect_text_without_an_event_skips_nothing(self):
        with patch.object(app, "adb_present", return_value=False), \
             patch.object(app.subprocess, "Popen", side_effect=[
                 self.fake("手机和电脑的 adb 连接断开了，本步骤没有完成。\n"), self.fake("", 0)]) as popen:
            self.api._work([app.Task("广告开关", "run.py"), app.Task("收尾", "run.py")])
        self.assertEqual(popen.call_count, 2)
        self.assertNotIn("skipped", self.api.job.results[1])

    def test_phone_back_on_the_bus_means_no_suppression(self):
        with patch.object(app, "adb_present", return_value=True), \
             patch.object(app.subprocess, "Popen", side_effect=[
                 self.fake(event("link_lost")), self.fake("", 0)]) as popen:
            self.api._work([app.Task("广告开关", "run.py"), app.Task("收尾", "run.py")])
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(self.api.job.results[1]["rc"], 0)


if __name__ == "__main__":
    unittest.main()
