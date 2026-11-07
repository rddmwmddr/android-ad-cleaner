"""「等到认得出」：超时、稳定、变化、受阻四个判据；外加等机主解锁。

不用手机、不真睡：采样器是假的，时钟也是假的。期望值都写成采样序列里能直接读出来的
事实（第几次采样认出、在几秒时认出、一共采样几次），不是把算法的算式重算一遍。
"""
import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import events
import wait

LOCKED_TEXT = "  ! 手机锁屏了：请解锁手机并保持亮屏，解锁后自动继续（最多等 90 秒）"


class Clock:
    """until() 的 now/sleep 替身：sleep 推进时间。"""

    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


class ReadingClock(Clock):
    """每次读时间也前进的钟（测试里 itertools.count 那种）：多读一次时间，时间轴就快一倍。"""

    def now(self):
        self.t += 0.2
        return self.t


def samples(values, clock):
    """按顺序吐出给定的采样值，并记下每次被采样时的时刻。"""
    queue = list(values)
    sample = lambda: (sample.seen_at.append(clock.t), queue.pop(0) if queue else values[-1])[1]
    sample.seen_at = []
    return sample


class RecognizedTests(unittest.TestCase):
    def test_returns_the_value_as_soon_as_a_sample_is_truthy(self):
        clock = Clock()
        sample = samples(["page"], clock)
        self.assertEqual(wait.until(sample, timeout=1.0, now=clock.now, sleep=clock.sleep), "page")
        self.assertEqual(sample.seen_at, [0.0])
        self.assertEqual(clock.slept, [])          # 认出来了就不要再睡

    def test_falsy_samples_are_not_the_page(self):
        # 跳页动画里的空树、空列表都不算页面画好了
        clock = Clock()
        sample = samples([None, "", [], "page"], clock)
        self.assertEqual(wait.until(sample, timeout=2.0, poll=0.1, now=clock.now, sleep=clock.sleep), "page")
        self.assertEqual(len(sample.seen_at), 4)


class TimeoutTests(unittest.TestCase):
    def test_gives_up_after_the_budget_without_reading_past_it(self):
        # 1 秒预算、每 0.25 秒采样一次：最后一次采样在 0.75 秒，1.0 秒时不再采样
        clock = Clock()
        sample = samples([None], clock)
        self.assertIsNone(wait.until(sample, timeout=1.0, poll=0.25, now=clock.now, sleep=clock.sleep))
        self.assertEqual(sample.seen_at, [0.0, 0.25, 0.5, 0.75])

    def test_reads_the_clock_once_per_round(self):
        # 采样次数由预算决定，不能被「读了几次时钟」带跑
        clock = ReadingClock()                     # 每读一次前进 0.2 秒
        sample = samples([None], clock)
        self.assertIsNone(wait.until(sample, timeout=1.0, poll=0, now=clock.now, sleep=clock.sleep))
        self.assertEqual(len(sample.seen_at), 4)   # 多读一次时间就只剩 1~2 次


class TriesTests(unittest.TestCase):
    def test_budget_can_be_counted_in_samples(self):
        # wait_page / off 原来数的是轮次：慢机型上一轮读屏更久，就该多给它时间，而不是按秒砍短
        clock = Clock()
        sample = samples([None], clock)
        self.assertIsNone(wait.until(sample, tries=5, poll=0.2, now=clock.now, sleep=clock.sleep))
        self.assertEqual(len(sample.seen_at), 5)

    def test_tries_terminates_even_when_sleep_does_not_advance_the_clock(self):
        # 测试把 sleep 换成 no-op 时，次数预算不依赖时钟
        sample = samples([None], Clock())
        self.assertIsNone(wait.until(sample, tries=3, poll=0.2, now=lambda: 0.0, sleep=lambda s: None))
        self.assertEqual(len(sample.seen_at), 3)

    def test_needs_a_budget(self):
        with self.assertRaises(ValueError):
            wait.until(lambda: "page")


class ChangedTests(unittest.TestCase):
    def test_given_value_must_differ_from_the_previous_page(self):
        clock = Clock()
        sample = samples(["old page", "old page", "new page"], clock)
        got = wait.until(sample, timeout=2.0, poll=0.1, changed_from="old page",
                         now=clock.now, sleep=clock.sleep)
        self.assertEqual(got, "new page")
        self.assertEqual(len(sample.seen_at), 3)   # 前两次都是原来那一页，不算


class StableTests(unittest.TestCase):
    def test_value_must_hold_still_for_the_stable_window(self):
        # 0.2 秒的稳定窗口：0.0 认出 a、0.2 变成 b，b 要停到 0.4 才算站稳
        clock = Clock()
        sample = samples(["a", "a", "b", "b", "b"], clock)
        self.assertEqual(wait.until(sample, timeout=2.0, poll=0.1, stable=0.2,
                                    now=clock.now, sleep=clock.sleep), "b")
        self.assertEqual(sample.seen_at[-1], 0.4)

    def test_page_that_keeps_redrawing_never_settles(self):
        clock = Clock()
        sample = samples(["a", "b", "c", "d", "e"], clock)
        self.assertIsNone(wait.until(sample, timeout=0.45, poll=0.1, stable=0.2,
                                     now=clock.now, sleep=clock.sleep))

    def test_without_a_stable_window_a_redrawing_page_counts_at_once(self):
        # stable=0 时不要求前后相同，否则 tap_icon / setting 那几段全都等不到
        clock = Clock()
        sample = samples(["a", "b", "c"], clock)
        self.assertEqual(wait.until(sample, timeout=1.0, poll=0.1, stable=0.0,
                                    now=clock.now, sleep=clock.sleep), "a")


class StableSampleCountTests(unittest.TestCase):
    def test_slow_rounds_still_need_three_identical_samples(self):
        # 一轮读屏自己就超过 0.4 秒时，光看时间窗口只凭两次采样就认页；same=3 要求连续三次
        clock = Clock()
        sample = samples(["sw", "sw", "sw"], clock)
        got = wait.until(sample, timeout=10.0, poll=0.5, stable=0.4, same=3,
                         now=clock.now, sleep=clock.sleep)
        self.assertEqual(got, "sw")
        self.assertEqual(len(sample.seen_at), 3)   # 第二次时已过了 0.4 秒，但只有两次相同


class ChangedAndStableTests(unittest.TestCase):
    def test_page_must_change_and_then_hold_still(self):
        # settle 的实际配置：既要换掉原来那一页，又要站稳
        clock = Clock()
        sample = samples(["old page", "new page", "new page", "new page"], clock)
        got = wait.until(sample, timeout=2.0, poll=0.1, stable=0.2, changed_from="old page",
                         now=clock.now, sleep=clock.sleep)
        self.assertEqual(got, "new page")
        self.assertAlmostEqual(sample.seen_at[-1], 0.3)  # 0.1 首次看到新页，站稳在 0.3


class BlockedTests(unittest.TestCase):
    def test_blocked_can_cut_a_wait_short(self):
        clock = Clock()
        sample = samples([None, None, "page"], clock)
        calls = []

        def blocked():
            calls.append(clock.t)
            return RuntimeError("手机锁屏了") if len(calls) == 3 else None

        with self.assertRaisesRegex(RuntimeError, "手机锁屏了"):
            wait.until(sample, timeout=5.0, poll=0.1, now=clock.now, sleep=clock.sleep, blocked=blocked)
        self.assertEqual(len(sample.seen_at), 2)   # 第三轮还没读屏就停了

    def test_sampler_can_give_up_directly(self):
        clock = Clock()

        def sample():
            raise wait.GiveUp()

        self.assertIsNone(wait.until(sample, timeout=5.0, now=clock.now, sleep=clock.sleep))
        self.assertEqual(clock.slept, [])

    def test_blocked_reason_is_raised_before_the_first_sample(self):
        clock = Clock()
        sample = samples(["page"], clock)
        with self.assertRaisesRegex(RuntimeError, "手机锁屏了"):
            wait.until(sample, timeout=1.0, now=clock.now, sleep=clock.sleep,
                       blocked=lambda: RuntimeError("手机锁屏了"))
        self.assertEqual(sample.seen_at, [])       # 已经知道等不下去，不再读屏

    def test_give_up_returns_none_without_waiting_out_the_budget(self):
        clock = Clock()
        sample = samples([None], clock)
        self.assertIsNone(wait.until(sample, timeout=5.0, now=clock.now, sleep=clock.sleep,
                                     blocked=lambda: wait.GiveUp()))
        self.assertEqual(clock.slept, [])


class PropagatesTests(unittest.TestCase):
    def test_sampling_errors_are_not_mistaken_for_an_unrecognized_page(self):
        # 断线要冒泡给调用方，不能被当成「页面没认出来」然后等到超时
        clock = Clock()

        def sample():
            raise ConnectionError("adb 断开了")

        with self.assertRaises(ConnectionError):
            wait.until(sample, timeout=1.0, now=clock.now, sleep=clock.sleep)


class UnlockedTests(unittest.TestCase):
    """等机主解锁（#709）：两处调用点只传「锁没锁着」「怎么亮屏」，策略全在这里。"""

    def setUp(self):
        self.clock = Clock()
        self.wakes = []

    def unlock(self, locked, timeout=wait.UNLOCK_TIMEOUT):
        """跑一次等待，返回 (返回值, 人话, 事件列表)；wake 记下自己被叫到的时刻。"""
        out = io.StringIO()
        with patch.dict(os.environ, {"AAC_EVENTS": "1"}, clear=False), contextlib.redirect_stdout(out):
            result = wait.wait_unlocked(locked, lambda: self.wakes.append(self.clock.t),
                                        timeout, now=self.clock.now, sleep=self.clock.sleep)
        lines = out.getvalue().splitlines()
        return (result, "\n".join(l for l in lines if not events.is_event(l)),
                [events.parse(l) for l in lines if events.is_event(l)])

    def states(self, values):
        """按顺序回答「现在还锁着吗」；用完之后一直报最后一个状态。"""
        queue = list(values)
        return lambda: queue.pop(0) if queue else values[-1]

    def test_wakes_and_waits_until_the_owner_unlocks(self):
        result, human, sent = self.unlock(self.states([True, True, False]))
        self.assertTrue(result)
        self.assertEqual(self.wakes, [0.0])                        # 先亮屏，再问锁没锁
        self.assertEqual(human, LOCKED_TEXT)                       # 锁着的时候才报这句
        self.assertEqual(sent, ["locked"])
        self.assertEqual(self.clock.slept, [1, 1, 0.8])            # 两次轮询，解锁后站稳

    def test_never_unlocked_gives_up_and_reports_locked_once(self):
        result, human, sent = self.unlock(lambda: True)
        self.assertFalse(result)
        self.assertEqual(human, LOCKED_TEXT)
        self.assertEqual(sent, ["locked"])                         # 一直不解锁也只发一条事件
        self.assertEqual(self.clock.slept, [1] * wait.UNLOCK_TIMEOUT)   # 每秒问一次，到点不再问

    def test_unlocked_phone_is_not_delayed(self):
        result, human, sent = self.unlock(lambda: False)
        self.assertTrue(result)
        self.assertEqual((human, sent, self.clock.slept), ("", [], []))

    def test_caller_can_give_its_own_budget(self):
        # chan_fast 在渠道之间另等 60 秒：预算由调用点给，轮询节奏不变
        result, human, sent = self.unlock(lambda: True, timeout=60)
        self.assertFalse(result)
        self.assertEqual(len(self.clock.slept), 60)
        self.assertEqual(human, LOCKED_TEXT.replace("90", "60"))


if __name__ == "__main__":
    unittest.main()
