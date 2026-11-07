"""#731：手机版中途读屏失败要有人话收场，且不再改「插电常亮」（#728 之后亮屏由 App 自己保证）。"""
import contextlib
import io
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import chan_fast as chan
import events
import fast
import run
from backups import Backups
from fixtures import Clock, FakeProc, FakeRunner, fake_phone, job_stub, phone_mock
from gui import app

ITEMS = [("com.a", "promo", "营销通知"), ("com.b", "news", "资讯推送"), ("com.c", "deal", "优惠活动")]
DATA = {(pk, cid): (label, 3, False) for pk, cid, label in ITEMS}


def reader(value="0", commands=None):
    """只回答 `settings get` 的假读屏：记下每条命令，验证有没有人偷偷写设置。"""
    def shell(cmd, timeout=None):
        if commands is not None:
            commands.append(cmd)
        return types.SimpleNamespace(output=value + "\n")
    return types.SimpleNamespace(shell=shell)


class KeepAwakeTests(unittest.TestCase):
    def call(self, on_phone, value="0"):
        commands = []
        with patch.object(chan, "ON_PHONE", on_phone), contextlib.redirect_stdout(io.StringIO()) as out:
            old = chan.keep_awake(reader(value, commands))
        return old, commands, out.getvalue()

    def test_phone_never_writes_the_setting(self):
        old, commands, printed = self.call(True)
        self.assertEqual(commands, ["settings get global stay_on_while_plugged_in"])
        self.assertEqual(old, "0")
        self.assertEqual(printed, "")

    def test_phone_returns_the_old_value_like_the_desktop(self):
        """手机版照桌面版的口径给原值：调用方拿到的还是那个数字字符串。"""
        old, _, _ = self.call(True, "15")
        self.assertEqual(old, "15")

    def test_desktop_still_turns_it_on(self):
        """旧树也绿，守的是不回退：桌面版照旧写 7。"""
        _, commands, _ = self.call(False)
        self.assertIn("settings put global stay_on_while_plugged_in 7", commands)


class BatchRestoreTests(unittest.TestCase):
    """批尾的「改回原值」同样不能在手机版写出去：手机版根本没改过。"""

    def run_off(self, on_phone):
        commands = []
        phone = phone_mock(wait_unlocked=Mock(return_value=True))
        with patch.object(chan, "load", return_value=ITEMS), \
                patch.object(chan, "parse", return_value=(DATA, {})) as parse, \
                patch.object(chan, "ShellPhone", return_value=reader("0", commands)), \
                patch.object(chan, "Phone", return_value=phone) as make_phone, \
                patch.object(chan, "toggle", return_value=chan.Outcome(chan.DONE)) as toggle, \
                patch.object(chan, "ON_PHONE", on_phone), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):      # 复查时仍是 ON：这一步本来就算失败
                chan.run(["-s", "test", "off", "x.tsv"])
        parse.assert_called()
        make_phone.assert_called_once()
        self.assertEqual(toggle.call_count, len(ITEMS))
        return commands

    def test_phone_batch_leaves_the_setting_alone(self):
        commands = self.run_off(True)
        self.assertEqual([c for c in commands if "stay_on" in c],
                         ["settings get global stay_on_while_plugged_in"])

    def test_desktop_batch_turns_it_on_and_back(self):
        """旧树也绿，守的是不回退：桌面版照旧「批开头打开 → 批尾改回」。"""
        commands = self.run_off(False)
        self.assertEqual([c for c in commands if "stay_on" in c],
                         ["settings get global stay_on_while_plugged_in",
                          "settings put global stay_on_while_plugged_in 7",
                          "settings get global stay_on_while_plugged_in",
                          "settings put global stay_on_while_plugged_in 0"])


class RecipeStayOnTests(unittest.TestCase):
    """机型脚本这一路（run.py recipe）原来也是开头写 7、finally 改回。"""

    def recipe(self, on_phone):
        commands = []
        with patch.object(sys, "argv", ["run.py", "-s", "test", "recipe"]), \
                patch.object(run, "info", return_value={"brand": "Xiaomi", "model": "M", "build": "OS4.0"}), \
                patch.object(run, "recipe_for", return_value=("recipe.py", None)), \
                patch.object(run, "recipe_meta", return_value={"build": "OS4.0"}), \
                patch.object(run, "build_ok", return_value=True), \
                patch.object(run, "wait_unlocked", return_value=True), \
                patch.object(run, "sh", side_effect=lambda s, c, *a, **k: commands.append(c) or "15"), \
                patch.object(run, "py", return_value=0), \
                patch.object(run, "ON_PHONE", on_phone):
            self.assertEqual(run.main(), 0)
        return [c for c in commands if "stay_on" in c]

    def test_phone_recipe_leaves_the_setting_alone(self):
        self.assertEqual(self.recipe(True), [])

    def test_desktop_recipe_turns_it_on_and_back(self):
        """旧树也绿，守的是不回退：桌面版照旧开头写 7、finally 改回原值。"""
        self.assertEqual(self.recipe(False), ["settings get global stay_on_while_plugged_in",
                                              "settings put global stay_on_while_plugged_in 7",
                                              "settings put global stay_on_while_plugged_in 15"])


class FinishStayOnTests(unittest.TestCase):
    """收尾这一步在手机版也没有「改回插电常亮」这回事。"""

    def finish(self, on_phone):
        commands = []
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            snap = Backups(root).create("M")
            Path(snap, "stay_on.txt").write_text("15", encoding="utf-8")
            with patch.object(run, "BACKUPS", root), \
                    patch.object(run, "info", return_value={"model": "M"}), \
                    patch.object(run, "sh", side_effect=lambda s, c, *a, **k: commands.append(c) or "0"), \
                    patch.object(run, "ON_PHONE", on_phone), \
                    contextlib.redirect_stdout(out):
                run.cmd_finish("test", [])
        return commands, out.getvalue()

    def test_phone_finish_says_nothing_about_it(self):
        commands, printed = self.finish(True)
        self.assertEqual([c for c in commands if "stay_on" in c], [])
        self.assertNotIn("插电常亮", printed)
        self.assertIn("input keyevent HOME", commands)      # 收尾其余动作照旧

    def test_desktop_finish_still_puts_the_snapshot_value_back(self):
        """旧树也绿，守的是不回退：桌面版照旧按快照改回并说一句。"""
        commands, printed = self.finish(False)
        self.assertEqual([c for c in commands if "stay_on" in c],
                         ["settings put global stay_on_while_plugged_in 15"])
        self.assertIn("插电常亮已改回 15", printed)


class ClassifyTests(unittest.TestCase):
    """两种失败的界线：通道没了是断线，慢一次只是这一步没成。"""

    def test_command_service_gone_counts_as_a_disconnect(self):
        for message in ("命令服务断开", "命令服务已断开", "命令服务不可用：java.io.IOException"):
            self.assertTrue(adb_link.lib_gone(message), message)

    def test_a_slow_read_is_not_a_disconnect(self):
        self.assertFalse(adb_link.lib_gone("读屏请求超时（30 秒）"))

    def test_a_slow_read_gets_one_sentence(self):
        self.assertEqual(adb_link.read_failed("读屏请求超时（30 秒）"), "这一步没有完成：读屏请求超时（30 秒）")
        self.assertIsNone(adb_link.read_failed("命令服务断开"))

    def test_phone_takes_the_message_as_evidence(self):
        """手机版的 get-state 由同一个 bridge 回答：它会说「还在」，不能推翻消息里的断开（#731）。"""
        with patch.object(adb_link, "ON_PHONE", True), patch.object(adb_link, "present", return_value=True):
            self.assertIsInstance(adb_link.lost_from(ValueError("命令服务断开"), "test"), adb_link.DeviceLost)

    def test_desktop_still_asks_the_device_list(self):
        """桌面版照旧要双向确认：手机还在列表里就不算断开（#293）。"""
        with patch.object(adb_link, "ON_PHONE", False), patch.object(adb_link, "present", return_value=True):
            self.assertIsNone(adb_link.lost_from(ValueError("device 'test' not found"), "test"))


class ToggleFailureTests(unittest.TestCase):
    def toggle(self, error):
        """跑一次 toggle，返回 (结局, 事件, 异常)：异常照原样交出来，事件已经记下。"""
        p = fake_phone()
        out, result, raised = io.StringIO(), None, None
        with patch.object(chan, "parse", side_effect=error), \
                patch.object(adb_link, "present", return_value=False), \
                patch.dict(os.environ, {"AAC_EVENTS": "1"}), contextlib.redirect_stdout(out):
            try:
                result = chan.toggle(p, "com.a", "promo", False, "营销通知")
            except Exception as e:
                raised = e
        lines = out.getvalue().splitlines()
        return result, [events.parse(line) for line in lines if events.is_event(line)], raised

    def test_command_service_gone_stops_the_batch_as_a_disconnect(self):
        _, sent, raised = self.toggle(fast.u2.exceptions.UiAutomationError("命令服务断开"))
        self.assertIsInstance(raised, adb_link.DeviceLost)
        self.assertEqual(sent, ["link_lost"])

    def test_a_slow_read_is_one_channel_failing(self):
        result, sent, raised = self.toggle(fast.u2.exceptions.UiAutomationError("读屏请求超时（30 秒）"))
        self.assertIsNone(raised)
        self.assertEqual(result.kind, chan.ERROR)
        self.assertIn("读屏请求超时", result.detail)
        self.assertEqual(sent, [])          # 慢一次不是断线：不发 link_lost


class BatchContinuesTests(unittest.TestCase):
    """Redmi K80 那台：一个渠道读屏超时，后面的渠道照常跑，整步算失败（#731）。"""

    def run_off(self):
        clock = Clock()
        phone, reads = fake_phone(clock=clock), []

        def parse(target, *a, **k):
            if target is not phone:
                return DATA, {}                     # 通知记录那一读不在这条路上
            reads.append(target)
            if len(reads) == 1:
                raise fast.u2.exceptions.UiAutomationError("读屏请求超时（30 秒）")
            return DATA, {}

        out = io.StringIO()
        with patch.object(chan, "load", return_value=ITEMS), patch.object(chan, "parse", side_effect=parse), \
                patch.object(chan, "ShellPhone", return_value=reader()), \
                patch.object(chan, "Phone", return_value=phone), patch.object(chan, "time", clock), \
                patch.dict(os.environ, {"AAC_EVENTS": "1"}), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                chan.run(["-s", "test", "off", "x.tsv"])
        lines = out.getvalue().splitlines()
        return caught.exception.code, lines, [events.parse(x) for x in lines if events.is_event(x)]

    def test_the_rest_of_the_batch_still_runs(self):
        code, lines, sent = self.run_off()
        printed = "\n".join(lines)
        self.assertEqual(code, 1)                                    # 有渠道没关成，整步算失败
        self.assertIn("这一步没有完成：读屏请求超时（30 秒）", printed)
        self.assertIn("资讯推送", printed)                            # 后面的渠道照常处理
        self.assertIn("优惠活动", printed)
        self.assertNotIn("Traceback", printed)
        self.assertEqual(sent, [])                                   # 慢一次不发 link_lost


class EntryTests(unittest.TestCase):
    """两个脚本入口都只报一句人话：读屏慢一次不该以 Python 堆栈收场（#731）。"""

    def test_chan_fast_exits_with_one_sentence(self):
        out = io.StringIO()
        with patch.object(chan, "run", side_effect=fast.u2.exceptions.UiAutomationError("读屏请求超时（30 秒）")), \
                patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "verify", "x.tsv"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                chan.main()
        self.assertEqual(caught.exception.code, "✗ 这一步没有完成：读屏请求超时（30 秒）")

    def test_fast_exits_with_one_sentence(self):
        out = io.StringIO()
        with patch.object(fast, "Phone", side_effect=fast.u2.exceptions.UiAutomationError("读屏请求超时（30 秒）")), \
                patch.object(sys, "argv", ["fast.py", "-s", "test", "run", "recipe.py"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                fast.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(out.getvalue().strip(), "✗ 这一步没有完成：读屏请求超时（30 秒）")

    def test_an_unexpected_error_still_raises(self):
        """只收读屏这一种：别的异常照旧带着堆栈，不能顺手吞掉（#731）。"""
        with patch.object(chan, "run", side_effect=ValueError("boom")), \
                patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "verify", "x.tsv"]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                chan.main()


class ClientKeepsGoingTests(unittest.TestCase):
    """「后续步骤仍照常执行」的客户端一侧：超时不发 link_lost，后面的步骤不会被标成跳过（#731）。"""

    def test_later_steps_run_after_a_slow_read(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory, runner=FakeRunner(spawns=[
                FakeProc("✗ 这一步没有完成：读屏请求超时（30 秒）\n", rc=1), FakeProc()]))
            api.job = job_stub()
            with patch.object(app, "adb_present", return_value=True):
                api._work([app.Task("关闭营销通知", "run.py", ["-s", "test", "chan-off", "x.tsv"]),
                           app.Task("收尾", "run.py", ["-s", "test", "finish"])])
        self.assertEqual(len(api.runner.spawn_calls), 2)      # 后面那一步照常起
        self.assertEqual(api.job.results[0]["rc"], 1)         # 读屏超时的那一步仍算失败
        self.assertNotIn("skipped", api.job.results[1])


if __name__ == "__main__":
    unittest.main()
