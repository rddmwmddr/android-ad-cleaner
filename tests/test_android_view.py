"""手机版界面的判断（aac_android/view.py）：结果怎么说、什么时候挡住开始、反馈网址怎么截。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))

from aac_android import view  # noqa: E402


class FakeApi:
    def __init__(self, status=None, run=None):
        self._status, self._run = status or {}, run or {}
        self.opened, self.copied = [], []

    def status(self, serial):
        return self._status

    def poll(self, since):
        return self._run

    def open_url(self, url):
        self.opened.append(url)

    def copy_text(self, text):
        self.copied.append(text)
        return True


def status(**over):
    base = {"info": {"name": "Phone X", "brand": "OPPO", "model": "PX1", "os": "16"},
            "steps": ["桌面", "浏览器"], "recipe": "oppo/PX1", "recipe_ok": True, "recipe_ref": False,
            "quickapps": [], "ads": []}
    return {**base, **over}


class SummarizeTest(unittest.TestCase):
    def test_shared_cases_with_web_client(self):
        """tests/summary_cases.json 是两处 summarize() 的共同口径：网页版用例断言同一批串。"""
        cases = json.loads((ROOT / "tests" / "summary_cases.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(view.summarize({"tail": case["tail"]}), case["want"])

    def test_known_lines(self):
        cases = [(["机型脚本跑完：关了 12 个，34 秒"], "关了 12 个开关"),
                 (["拨了 5 个", "仍开着: 1 个"], "关了 5 个渠道，复查仍开着 1 个"),
                 (["拨了 5 个"], "关了 5 个渠道"),
                 (["快照已存"], "已保存")]
        for tail, want in cases:
            self.assertEqual(view.summarize({"tail": tail}), want)

    def test_quickapp_counts_lines(self):
        tail = ["  快应用 com.a 已关闭", "  快应用 com.b 已关闭", "快应用组件已关闭（保留项除外）。请按常用入口核对效果；恢复：quickapp on"]
        self.assertEqual(view.summarize({"tail": tail}), "2 个组件已关闭")

    def test_falls_back_to_last_line(self):
        self.assertEqual(view.summarize({"tail": ["甲", "乙", ""]}), "乙")
        self.assertEqual(view.summarize({"tail": []}), "")


class OutcomeTest(unittest.TestCase):
    def test_all_ok(self):
        self.assertEqual(view.outcome({"results": [{"rc": 0}], "cancel": False}), "ok")

    def test_stopped_is_not_failure(self):
        run = {"results": [{"rc": 1, "stopped": True}], "cancel": True}
        self.assertEqual(view.outcome(run), "stopped")
        self.assertEqual(view.outcome({"results": [], "cancel": True}), "stopped")

    def test_real_failure(self):
        self.assertEqual(view.outcome({"results": [{"rc": 1}], "cancel": False}), "failed")

    def test_poll_adds_summary_and_outcome(self):
        run = view.poll(FakeApi(run={"results": [{"rc": 0, "tail": ["快照已存"]}], "cancel": False}))
        self.assertEqual(run["results"][0]["summary"], "已保存")
        self.assertEqual(run["outcome"], "ok")

    def test_poll_passes_the_retry_count_through_untouched(self):
        # 旧树也绿：守的是回退——可重试判定只在 gui/app.py 的 retryable 里定义一次，
        # 手机版不许在 view.py 另算一份，只能把后台给的数字原样透传（#638）。
        run = view.poll(FakeApi(run={"results": [{"rc": 1, "tail": []}], "cancel": False, "retry": 1}))
        self.assertEqual(run["retry"], 1)
        # 没有这个字段的载荷不炸：Compose 侧 optInt 取到 0，结果页不出按钮
        self.assertIsNone(view.poll(FakeApi(run={"results": [], "cancel": True})).get("retry"))


class StallWatchTest(unittest.TestCase):
    def setUp(self):
        self.t = 0
        self.watch = view.StallWatch(now=lambda: self.t)

    def at(self, t, **run):
        self.t = t
        return self.watch.update({"running": True, "idx": 2, "next": 10, **run})

    def test_quiet_below_the_threshold_says_nothing(self):
        self.at(0)
        self.assertEqual(self.at(view.StallWatch.AFTER - 1), 0)

    def test_quiet_past_the_threshold_reports_seconds(self):
        self.at(0)
        self.assertEqual(self.at(view.StallWatch.AFTER), view.StallWatch.AFTER)
        self.assertEqual(self.at(95), 95)

    def test_new_log_line_resets(self):
        self.at(0)
        self.at(90)
        self.assertEqual(self.at(91, next=11), 0)
        self.assertEqual(self.at(91 + view.StallWatch.AFTER - 1, next=11), 0)

    def test_new_step_resets(self):
        self.at(0)
        self.at(90)
        self.assertEqual(self.at(91, idx=3), 0)

    def test_paused_is_not_a_stall(self):
        self.at(0)
        self.assertEqual(self.at(200, paused=True), 0)
        self.assertEqual(self.at(201), 0)              # 刚继续，重新计时

    def test_pausing_that_never_takes_effect_is_a_stall(self):
        # 点了暂停但还没到安全位置：脚本仍在跑，一直不生效就是卡住了
        self.at(0, pause=True)
        self.assertEqual(self.at(100, pause=True), 100)

    def test_finished_run_is_not_a_stall(self):
        self.at(0)
        self.assertEqual(self.at(500, running=False), 0)

    def test_poll_reports_the_stall(self):
        watch, view.WATCH = view.WATCH, self.watch
        self.addCleanup(setattr, view, "WATCH", watch)
        run = {"running": True, "idx": 1, "next": 3, "results": [], "cancel": False}
        view.poll(FakeApi(run=run))
        self.t = 100
        self.assertEqual(view.poll(FakeApi(run=run))["stalled"], 100)


class DetectTest(unittest.TestCase):
    def detect(self, **over):
        return view.detect(FakeApi(status(**over)), "s")

    def test_ready_phone_is_not_blocked(self):
        d = self.detect()
        self.assertFalse(d["blocked"])
        self.assertEqual(d["warnings"], [])
        self.assertEqual(d["recipe_label"], "按机型脚本自动关")
        self.assertEqual(d["manual_url"], "")

    def test_error_passes_through(self):
        self.assertEqual(view.detect(FakeApi({"error": "连不上"}), "s"), {"error": "连不上"})

    def test_locked_and_input_blocked_stop_the_run(self):
        self.assertTrue(self.detect(locked=True)["blocked"])
        self.assertTrue(self.detect(input_blocked=True)["blocked"])

    def test_open_fold_blocks_only_when_a_recipe_would_run(self):
        self.assertTrue(self.detect(fold_open=True)["blocked"])
        d = self.detect(fold_open=True, steps=[], recipe=None)
        self.assertFalse(d["blocked"])
        self.assertEqual(d["warnings"],
                         ["这是展开的折叠屏。营销通知、快应用、广告组件不受影响，可以继续。"])

    def test_warnings_say_what_to_do(self):
        self.assertEqual(self.detect(locked=True)["warnings"],
                         ["手机锁屏了。请解锁手机并保持亮屏，然后点「重新检测」。"])
        blocked = self.detect(input_blocked=True)["warnings"]
        self.assertIn("USB 调试（安全设置）", blocked[0])
        self.assertIn("不开它，自动关开关和营销通知都会失败。", blocked[0])
        self.assertNotIn("锁屏", blocked[0])      # #728 之后由本 App 自己的屏幕锁兜着
        self.assertIn("合上手机用外屏", self.detect(fold_open=True)["warnings"][0])

    def test_no_recipe_points_to_the_brand_checklist(self):
        d = self.detect(steps=[], recipe=None)
        self.assertIsNone(d["recipe_label"])
        self.assertEqual(d["manual_name"], "OPPO / ColorOS")
        self.assertIn("OPPO-ColorOS.md", d["manual_url"])

    def test_reference_recipe_runs_in_safe_mode(self):
        d = self.detect(recipe="oppo/PX9", recipe_ref=True, recipe_ok=False)
        self.assertTrue(d["ref"])
        self.assertIn("PX9", d["recipe_label"])
        self.assertIn("安全模式", d["recipe_note"])
        self.assertIn("不做整页全关", d["recipe_note"])
        self.assertIn("「防止 / 限制广告跟踪」这类保护开关会打开", d["recipe_note"])
        self.assertTrue(d["manual_url"])

    def test_version_mismatch_is_stated(self):
        d = self.detect(recipe_ok=False, recipe_build="15")
        self.assertIn("脚本按 15 录，这台是 16", d["recipe_note"])

    def test_quickapp_and_ads_only_list_what_is_still_on(self):
        d = self.detect(quickapps=[{"name": "A", "closed": True}, {"name": "B"}, {"name": "C", "keep": True}],
                        ads=[{"pkg": "com.opos.ads"}, {"pkg": "x.y", "suspended": True}])
        self.assertEqual(d["quickapps"], ["B"])
        self.assertIn("保留", d["quickapp_note"])
        self.assertIn("hap://", d["quickapp_note"])
        self.assertIn("vivo 优先使用快应用服务开关", d["quickapp_note"])
        self.assertEqual(d["ads"], [{"pkg": "com.opos.ads", "name": "OPPO 广告服务"}])
        d = self.detect(quickapps=[{"name": "A", "closed": True}], ads=[{"pkg": "x", "suspended": True}])
        self.assertEqual((d["quickapp_state"], d["ads_state"]), ("已关闭", "已挂起"))
        d = self.detect(quickapps=[{"name": "A", "closed": True}, {"name": "C", "keep": True}])
        self.assertEqual(d["quickapp_state"], "已关闭（保留 1 个系统组件）")
        d = self.detect()
        self.assertEqual((d["quickapp_state"], d["ads_state"]), ("没有检测到", "没有已知的"))

    def test_xiaomi_ad_component_says_partial_success_is_reported(self):
        d = self.detect(ads=[{"pkg": "com.miui.systemAdSolution"}])
        self.assertIn("会报告部分完成", d["ads"][0]["name"])


class BrandGuideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        docs = Path(self.tmp.name, "docs")
        docs.mkdir()
        docs.joinpath("brand-taps.json").write_text(
            (ROOT / "docs" / "手机版教程" / "brand-taps.json").read_text(encoding="utf-8"), encoding="utf-8")
        old, view.BASE = view.BASE, self.tmp.name
        self.addCleanup(setattr, view, "BASE", old)

    def test_every_brand_finds_its_row(self):
        want = {"Xiaomi": "OS 版本", "Redmi": "OS 版本", "vivo": "软件版本号", "iQOO": "软件版本号",
                "OPPO": "版本号", "OnePlus": "版本号", "realme": "版本号", "HONOR": "版本号"}
        for brand, word in want.items():
            self.assertIn(word, view.brand_guide(None, brand)["tap"], brand)

    def test_xiaomi_family_flag(self):
        self.assertTrue(view.brand_guide(None, "Redmi")["xiaomi"])
        self.assertFalse(view.brand_guide(None, "vivo")["xiaomi"])

    def test_unknown_brand_or_missing_file_still_answers(self):
        self.assertIn("版本号", view.brand_guide(None, "Nokia")["tap"])
        view.BASE = "/nonexistent"
        self.assertIn("版本号", view.brand_guide(None, "vivo")["tap"])


class SetupGuideTest(unittest.TestCase):
    """首次设置三步：页面与通知栏都从这一份取（#646）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        docs = Path(self.tmp.name, "docs")
        docs.mkdir()
        docs.joinpath("brand-taps.json").write_text(
            (ROOT / "docs" / "手机版教程" / "brand-taps.json").read_text(encoding="utf-8"), encoding="utf-8")
        old, view.BASE = view.BASE, self.tmp.name
        self.addCleanup(setattr, view, "BASE", old)

    def guide(self, brand="OPPO"):
        return view.setup_guide(None, brand)

    def test_states_map_to_three_ordered_steps(self):
        g = self.guide()
        self.assertEqual(g["at"], {"need_dev": 0, "need_wifi": 1, "need_pair": 2})
        self.assertEqual([s["key"] for s in g["steps"]], ["about", "dev", "pair"])
        self.assertEqual([s["title"] for s in g["steps"]], ["打开开发者选项", "打开无线调试", "授权本 App"])
        self.assertEqual([s["action"] for s in g["steps"]], ["打开「关于手机」", "打开开发者选项", "开始授权"])
        self.assertIn("setup_guide", view.EXPORTS)

    def test_every_step_carries_the_fields_the_client_parses(self):
        for step in self.guide()["steps"]:
            self.assertEqual(set(step), {"key", "title", "lines", "note", "action", "notice"})
            self.assertTrue(step["lines"])

    def test_notice_carries_the_step_and_what_to_do_next(self):
        steps = self.guide()["steps"]
        self.assertEqual([s["notice"]["title"] for s in steps[:2]],
                         ["第 1 步，共 3 步：打开开发者选项", "第 2 步，共 3 步：打开无线调试"])
        # 通知里别再补一层「在「关于手机」里」：tap 自带完整路径，各品牌入口还不一样
        self.assertTrue(steps[0]["notice"]["text"].startswith("连点"))
        self.assertIn("版本号", steps[0]["notice"]["text"])
        self.assertIn("回到「肉呆去广告」", steps[1]["notice"]["text"])
        self.assertIsNone(steps[2]["notice"])     # 配对阶段的通知由 PairingService 负责

    def test_brand_changes_the_path_and_the_xiaomi_extra_step(self):
        xiaomi = self.guide("Redmi")["steps"]
        self.assertIn("OS 版本", xiaomi[0]["lines"][1])
        self.assertIn("OS 版本", xiaomi[0]["notice"]["text"])
        self.assertIn("USB 调试（安全设置）", "".join(xiaomi[1]["lines"]))
        self.assertIn("USB 调试（安全设置）", xiaomi[1]["notice"]["text"])
        self.assertIn("输入配对码配对设备", "".join(xiaomi[2]["lines"]))
        vivo = self.guide("vivo")["steps"]
        self.assertIn("软件版本号", vivo[0]["lines"][1])
        self.assertNotIn("USB 调试（安全设置）", "".join(vivo[1]["lines"]))
        self.assertNotIn("USB 调试（安全设置）", vivo[1]["notice"]["text"])


class FeedbackTest(unittest.TestCase):
    def query(self, url):
        return parse_qs(urlsplit(url).query)

    def test_short_goes_entirely_in_the_url(self):
        url, clip = view.feedback_url("idea", "希望支持平板\n第二行", "诊断")
        q = self.query(url)
        self.assertEqual(clip, "")
        self.assertEqual(q["template"], ["feature_request.md"])
        self.assertEqual(q["title"], ["[建议] 希望支持平板"])
        self.assertIn("诊断", q["body"][0])

    def test_no_diag_no_section(self):
        url, _ = view.feedback_url("bug", "卡住了", "")
        self.assertNotIn("诊断信息", self.query(url)["body"][0])

    def test_long_diag_keeps_a_summary_and_copies_the_rest(self):
        log = "\n".join(f"第 {i} 行日志" for i in range(600))
        diag = f"手机：PX1\n<details>\n```text\n{log}\n```\n</details>"
        url, clip = view.feedback_url("bug", "卡住了", diag)
        body = self.query(url)["body"][0]
        self.assertLessEqual(len(url), view.URL_LIMIT)
        self.assertIn("手机：PX1", body)
        self.assertIn("第 599 行日志", body)
        self.assertIn("第 0 行日志", clip)

    def test_huge_summary_falls_back_to_paste_hint(self):
        url, clip = view.feedback_url("bug", "卡住了", "头" * 9000)
        self.assertLessEqual(len(url), view.URL_LIMIT)
        self.assertIn("请在这里粘贴", self.query(url)["body"][0])
        self.assertTrue(clip)

    def test_send_copies_only_when_trimmed(self):
        api = FakeApi()
        self.assertEqual(view.send_feedback(api, "bug", "短", ""), {"trimmed": False})
        self.assertEqual((len(api.opened), api.copied), (1, []))
        self.assertEqual(view.send_feedback(api, "bug", "长", "头" * 9000), {"trimmed": True})
        self.assertEqual(len(api.copied), 1)


class BrandTapsShapeTest(unittest.TestCase):
    """品牌键冻结在这里：从实现自己的表派生样例，删键会连样例一起消失。"""

    FROZEN = {"xiaomi": "小米", "redmi": "小米", "poco": "小米", "vivo": "vivo", "iqoo": "vivo",
              "oppo": "OPPO", "oneplus": "OPPO", "realme": "OPPO", "honor": "荣耀", "huawei": "荣耀"}

    def test_brand_keys_are_the_frozen_table(self):
        self.assertEqual(view.BRAND_KEYS, self.FROZEN)

    def test_every_brand_key_matches_a_row(self):
        rows = json.loads((ROOT / "docs" / "手机版教程" / "brand-taps.json").read_text(encoding="utf-8"))["rows"]
        for word in set(view.BRAND_KEYS.values()):
            self.assertTrue(any(word in r["brand"] for r in rows), word)


if __name__ == "__main__":
    unittest.main()
