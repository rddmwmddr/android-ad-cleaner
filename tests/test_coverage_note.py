"""结果页验证档位提示的唯一定义（#1188）：说不说一条判据，两个宿主只说同一件事、措辞按宿主分。

判据吃「这次真跑过脚本那一行」与 `recipe_coverage`；措辞在 `tool/host.py`。桌面侧随
`Dispatcher.poll()` 的快照下发（宿主传 `False`），手机版随 `view.poll()`（宿主传 `True`）；
网页只按字段决定说不说。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import coverage_note  # noqa: E402
import host  # noqa: E402
import verify_ledger  # noqa: E402


def run(coverage="部分", **row):
    """一次跑过机型脚本的结果页快照。

    成功行照引擎的原样不写 `skipped`（`step_result()` 只在跳过时才带它）：拿显式 False 去喂，
    `not r.get("skipped")` 被改成 `is False` 也照样绿。"""
    done = {"title": "关闭各 App 里的广告开关", "kind": "recipe", "rc": 0, **row}
    return {"results": [done], "cancel": False, "recipe_coverage": coverage}


def note(r, on_phone=False):
    return coverage_note.note(r, on_phone=on_phone)


class VerdictTests(unittest.TestCase):
    def test_partial_coverage_adds_a_line(self):
        text = note(run("部分"))
        self.assertIn("只在一部分步骤上做过真机验证", text)
        for word in ("tier", "evidence", "部分验证"):
            self.assertNotIn(word, text, "文案不能露出内部取值名")

    def test_full_coverage_adds_nothing(self):
        self.assertEqual(note(run("全部")), "")

    def test_a_script_with_no_ledger_entry_says_so(self):
        self.assertIn("没有真机验证记录", note(run("未记录")))

    def test_an_unknown_or_missing_tier_says_nothing(self):
        for value in ("", "以后的第四档", None):
            with self.subTest(coverage=value):
                self.assertEqual(note(run(value)), "")

    def test_a_snapshot_without_the_tier_says_nothing(self):
        # 旧载荷 / 没勾脚本时快照里就没有这个字段：结果页照常显示，不炸、也不猜深浅
        r = run()
        del r["recipe_coverage"]
        self.assertEqual(note(r), "")

    def test_a_skipped_recipe_step_means_no_line(self):
        # 没勾脚本 / 这台机没有专用脚本：那一行是「跳过」，拿别的步的结论说脚本的事会误导
        self.assertEqual(note(run("部分", skipped=True)), "")

    def test_a_run_that_never_touched_the_script_has_no_line(self):
        r = {"results": [{"title": "关闭营销通知", "kind": "channels", "rc": 0}],
             "cancel": False, "recipe_coverage": "未记录"}
        self.assertEqual(note(r), "")


class HostWordingTests(unittest.TestCase):
    """判据相同、措辞分叉：桌面版引导回 App 里核对，手机版不劝人去一个已经待着的地方。"""

    def test_the_phone_does_not_tell_you_to_check_in_the_app(self):
        for tier in ("部分", "未记录"):
            with self.subTest(tier=tier):
                self.assertNotIn("App", note(run(tier), on_phone=True))

    def test_the_desktop_points_back_into_the_app(self):
        for tier in ("部分", "未记录"):
            with self.subTest(tier=tier):
                self.assertIn("在 App 里", note(run(tier), on_phone=False))

    def test_the_caller_decides_the_host_not_the_environment(self):
        # 桌面用户 shell 里碰巧导出 AAC_HOST=phone 不该把桌面结果页说成手机版措辞（#747）
        with patch.object(host, "ON_PHONE", True):
            self.assertIn("在 App 里", note(run("部分"), on_phone=False))
        with patch.object(host, "ON_PHONE", False):
            self.assertNotIn("App", note(run("部分"), on_phone=True))

    def test_every_tier_but_full_has_its_own_line(self):
        """档位词表两处：`verify_ledger.TIERS` 是单一来源，这里只做映射（两个宿主同一张表）。
        台账加一档时这条会红，提醒「新档在结果页说不说」要想一遍，而不是静默不显示（#1130）。"""
        self.assertEqual(set(host.coverage_notes(True)) | {"全部"}, set(verify_ledger.TIERS))
        self.assertEqual(set(host.coverage_notes(True)), set(host.coverage_notes(False)))


if __name__ == "__main__":
    unittest.main()
