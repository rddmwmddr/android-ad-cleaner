"""渠道批处理的策略：清单 → 队列、两趟的门槛、重试挑行、收尾复查豁免。

被搬的是 `chan_fast.run()` 里「哪些结局进第二遍、重试轮到谁、复查哪些豁免」这几条判断：
以前只能跑一整批看输出，现在喂纯数据就能逐条证明。不读屏、不点击、不连手机
（`ChannelDecideGuards` 守着这一层不 import 引擎）。

点击与 adb 往返仍在 `chan_fast`；这一份只钉判断本身。`scan` / `off` / `on` 的对外逐字行为由
`tests/test_chan_cli_baseline.py` 的对拍基线守。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import channel_batch as batch

A = ("com.shop", "promo", "活动优惠")
B = ("com.news", "news", "热点资讯")
SPOT = ("com.photo", "spot", "找机位通知")


def listing(*channels, app_off=()):
    """(包名, 渠道 ID, 渠道名, importance, 已删除) → 到达决策吃的那份通知清单。"""
    rows = {(pk, cid): (name, imp, deleted) for pk, cid, name, imp, deleted in channels}
    return batch.channel_list_of(rows, {pk: True for pk in app_off})


ON_A = (*A, 3, False)
ON_B = (*B, 3, False)
OFF_A = (*A, 0, False)
OFF_B = (*B, 0, False)


def outcomes(planned):
    """每一项的结局（`None` 表示要打开手机去拨）。"""
    return [(row.pk, None if row.queued else row.outcome.kind) for row in planned]


class QueueTests(unittest.TestCase):
    def test_channels_in_the_target_direction_are_queued_and_nothing_else_is(self):
        planned = batch.plan_queue([A, B], listing(ON_A, ON_B), False)
        self.assertEqual([row.item for row in planned if row.queued], [A, B])
        self.assertEqual(outcomes(planned), [(A[0], None), (B[0], None)])

    def test_already_in_the_target_state_is_already_and_never_queued(self):
        self.assertEqual(outcomes(batch.plan_queue([A], listing(OFF_A), False)),
                         [(A[0], batch.ALREADY)])
        self.assertEqual(outcomes(batch.plan_queue([A], listing(ON_A), True)),
                         [(A[0], batch.ALREADY)])

    def test_restoring_queues_the_channels_that_are_still_off(self):
        planned = batch.plan_queue([A, B], listing(OFF_A, ON_B), True)
        self.assertEqual([row.item for row in planned if row.queued], [A])
        self.assertEqual(outcomes(planned)[1], (B[0], batch.ALREADY))

    def test_protected_wins_over_the_state_and_only_in_the_closing_direction(self):
        on = batch.plan_queue([SPOT], listing((*SPOT, 3, False)), False)[0]
        self.assertEqual((on.outcome.kind, on.outcome.detail), (batch.PROTECTED, "当前状态 ON"))
        restoring = batch.plan_queue([SPOT], listing((*SPOT, 0, False)), True)[0]
        self.assertTrue(restoring.queued)

    def test_missing_deleted_and_app_off_are_prefiltered_as_their_own_outcomes(self):
        cases = {
            batch.NO_CHANNEL: listing(),
            batch.DELETED: listing((*A, 3, True)),
            batch.APP_OFF: listing(ON_A, app_off=[A[0]]),
        }
        for kind, read in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(outcomes(batch.plan_queue([A], read, False)), [(A[0], kind)])

    def test_order_follows_the_item_list(self):
        planned = batch.plan_queue([B, A], listing(ON_A, ON_B), False)
        self.assertEqual([row.pk for row in planned], [B[0], A[0]])


class SecondPassTests(unittest.TestCase):
    def test_a_halted_batch_or_one_that_never_started_does_not_retry(self):
        self.assertFalse(batch.second_pass(halted=True, started=True, retry=[A], reached=1))
        self.assertFalse(batch.second_pass(halted=False, started=False, retry=[A], reached=1))

    def test_nothing_to_retry_means_no_second_pass(self):
        self.assertFalse(batch.second_pass(halted=False, started=True, retry=[], reached=5))

    def test_more_than_the_retry_cap_is_dropped(self):
        many = [A] * batch.RETRY_MAX
        self.assertEqual(len(many), batch.RETRY_MAX)
        self.assertTrue(batch.second_pass(halted=False, started=True, retry=many, reached=1))
        self.assertFalse(batch.second_pass(halted=False, started=True, retry=many + [A], reached=1))

    def test_without_any_reached_channel_only_a_small_retry_survives(self):
        three = [A, B, SPOT]
        self.assertFalse(batch.second_pass(halted=False, started=True, retry=three, reached=0))
        self.assertTrue(batch.second_pass(halted=False, started=True, retry=three, reached=1))
        self.assertTrue(batch.second_pass(halted=False, started=True, retry=three[:2], reached=0))


class PickRetryTests(unittest.TestCase):
    def test_channels_that_got_closed_meanwhile_are_confirmed_and_the_rest_requeued(self):
        plan = batch.pick_retry([A, B], listing(OFF_A, ON_B), False)
        self.assertEqual([row.item for row in plan.confirmed], [A])
        self.assertEqual(plan.confirmed[0].outcome.kind, batch.CONFIRMED_LATER)
        self.assertEqual([row.item for row in plan.queue], [B])

    def test_the_restoring_direction_confirms_channels_that_are_now_on(self):
        plan = batch.pick_retry([A, B], listing(ON_A, OFF_B), True)
        self.assertEqual([row.item for row in plan.confirmed], [A])
        self.assertEqual([row.item for row in plan.queue], [B])

    def test_a_channel_that_all_came_back_leaves_an_empty_queue(self):
        plan = batch.pick_retry([A], listing(OFF_A), False)
        self.assertEqual(plan.queue, tuple())


class AccountTests(unittest.TestCase):
    def test_the_credit_of_every_kind_comes_from_the_rules_table(self):
        for kind in batch.KINDS:
            got = batch.account(batch.Outcome(kind), False)
            row = batch.RULES[kind]
            with self.subTest(kind=kind):
                self.assertEqual(got.failure, row["fail_close"])
                self.assertEqual((got.retry, got.toggled, got.exempt),
                                 (row["retry"], row["toggled"], row["exempt"]))

    def test_deleted_or_app_off_only_fails_the_restoring_direction(self):
        for kind in (batch.DELETED, batch.APP_OFF):
            with self.subTest(kind=kind):
                self.assertFalse(batch.account(batch.Outcome(kind), False).failure)
                self.assertTrue(batch.account(batch.Outcome(kind), True).failure)

    def test_the_retry_set_is_the_same_as_the_rules_predicate(self):
        retried = {kind for kind in batch.KINDS if batch.account(batch.Outcome(kind), False).retry}
        self.assertEqual(retried, {batch.NOT_CONFIRMED, batch.APP_STATE_UNKNOWN, batch.UNCHANGED})


class RecheckTests(unittest.TestCase):
    def test_a_channel_that_is_still_on_is_counted_unless_exempted_or_protected(self):
        read = listing(ON_A)
        self.assertTrue(batch.recheck_row(read, *A, frozenset()).still_open)
        self.assertFalse(batch.recheck_row(read, *A, {(A[0], A[1])}).still_open)
        self.assertFalse(batch.recheck_row(listing((*SPOT, 3, False)), *SPOT, frozenset()).still_open)

    def test_a_closed_channel_is_not_still_open_but_keeps_its_state(self):
        row = batch.recheck_row(listing(OFF_A), *A, frozenset())
        self.assertEqual((row.state, row.still_open), ("off", False))

    def test_protected_is_reported_even_when_the_channel_is_on(self):
        row = batch.recheck_row(listing((*SPOT, 3, False)), *SPOT, frozenset())
        self.assertEqual((row.state, row.protected), ("ON", True))


class StateTests(unittest.TestCase):
    def test_every_state_reading_maps_to_the_same_outcome_as_before(self):
        read = listing(ON_A, (B[0], B[1], B[2], 3, True), app_off=["com.offapp"])
        self.assertEqual(batch.state(read, A[0], A[1]), "ON")
        self.assertEqual(batch.state(listing(OFF_A), A[0], A[1]), "off")
        self.assertEqual(batch.state(read, B[0], B[1]), "del")
        self.assertEqual(batch.state(listing(("com.offapp", "promo", "活动推荐", 3, False),
                                             app_off=["com.offapp"]), "com.offapp", "promo"), "app")
        self.assertEqual(batch.state(read, "com.gone", "promo"), "--")

    def test_kind_of_state_covers_the_three_absent_record_states(self):
        self.assertEqual(batch.kind_of_state("--"), batch.NO_CHANNEL)
        self.assertEqual(batch.kind_of_state("del"), batch.DELETED)
        self.assertEqual(batch.kind_of_state("app"), batch.APP_OFF)


if __name__ == "__main__":
    unittest.main()
