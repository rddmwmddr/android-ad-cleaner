"""手机版界面的判断（aac_android/view.py）：结果怎么说、什么时候挡住开始、反馈网址怎么截。"""
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))
sys.path.insert(0, str(ROOT / "tool"))

from aac_android import view  # noqa: E402


class FakeApi:
    def __init__(self, status=None, run=None):
        self._status, self._run = status or {}, run or {}
        self.opened, self.copied = [], []
        self.serial = None
        self.sinces = []

    def status(self, serial):
        self.serial = serial
        return self._status

    def poll(self, since):
        self.sinces.append(since)
        return self._run

    def open_url(self, url):
        self.opened.append(url)

    def copy_text(self, text):
        self.copied.append(text)
        return True


def status(**over):
    base = {"info": {"name": "Phone X", "brand": "OPPO", "model": "PX1", "os": "16"},
            "steps": ["桌面", "浏览器"], "recipe": "oppo-PX1", "recipe_ok": True, "recipe_ref": False,
            "quickapps": [], "ads": []}
    return {**base, **over}


class SummarizeTest(unittest.TestCase):
    """手机版结果页那一句由 tool/summary.py 给（#1189）：view 只把它贴到每一行，不再自己算。

    口径本身（共享样例集、扣减、机器行）在 `tests/test_summary.py` 跑，这里只验链路。旧树也绿：
    旧的本地实现在同一段 tail 上给出同一句，这条守的是「别把共享实现换回本地一份」。
    """

    def test_poll_rows_carry_the_shared_summary(self):
        run = view.poll(FakeApi(run={"results": [{"rc": 0, "tail": ["拨了 5 个", "仍开着: 1 个"]}],
                                   "cancel": False}))
        self.assertEqual(run["results"][0]["summary"], "关了 5 个渠道，复查仍开着 1 个")


class MachinePrefixTest(unittest.TestCase):
    def test_falls_back_when_the_shared_module_cannot_be_imported(self):
        """工具目录不在搜索路径时（桌面侧只装脚本的假工具目录）取不到共享实现，用兜底记号。"""
        saved = view._summary
        view._summary = None
        self.addCleanup(setattr, view, "_summary", saved)
        with mock.patch.dict(sys.modules, {"summary": None}):
            self.assertEqual(view.machine_prefix(), "#aac:")


class EncodeTest(unittest.TestCase):
    def test_matches_encode_uri_component(self):
        """等同 JS 的 encodeURIComponent：`-_.!~*'()` 与字母数字不编码，其余按 UTF-8 百分号编码。"""
        self.assertEqual(view._encode("a b'()*!~-_.c/中文"), "a%20b'()*!~-_.c%2F%E4%B8%AD%E6%96%87")


class ChunksTest(unittest.TestCase):
    """logcat 单条约 4 KB：按 UTF-8 字节切块，切点落在恰好等于上限时要留在同一块。"""

    def test_splits_on_the_byte_limit(self):
        self.assertEqual(view._chunks("abcdefgh", 4), ["abcd", "efgh"])

    def test_a_char_exactly_on_the_limit_stays_in_the_chunk(self):
        self.assertEqual(view._chunks("abcd", 4), ["abcd"])

    def test_empty_text_has_no_chunks(self):
        self.assertEqual(view._chunks("", 4), [])


class WarningsTest(unittest.TestCase):
    """检测页的每条提示逐字（含大小写），用户照着操作，改一个字都算行为变化。"""

    def test_locked_says_unlock(self):
        self.assertEqual(view._warnings({"locked": True}, False),
                         ["手机锁屏了。请解锁手机并保持亮屏，然后点「重新检测」。"])

    def test_input_blocked_spells_out_the_xiaomi_setting(self):
        self.assertEqual(view._warnings({"input_blocked": True}, False),
                         ["系统拒绝了模拟点按。小米 / Redmi / POCO 要在「开发者选项」里打开「USB 调试（安全设置）」"
                          "（需插 SIM 卡、登录小米账号），等风险提示倒计时结束点「确定」，再重新检测。"
                          "还是不行就重启手机再检测。不开它，自动关开关和营销通知都会失败。"])

    def test_open_fold_blocks_when_a_recipe_would_run(self):
        self.assertEqual(view._warnings({"fold_open": True}, True),
                         ["这是展开的折叠屏。展开后是左右分栏，自动关 App 开关会找错位置。合上手机用外屏，再重新检测。"])

    def test_open_fold_allows_the_rest_when_no_recipe_runs(self):
        self.assertEqual(view._warnings({"fold_open": True}, False),
                         ["这是展开的折叠屏。营销通知、快应用、广告组件不受影响，可以继续。"])

    def test_nothing_to_say(self):
        self.assertEqual(view._warnings({}, False), [])


class RecipeGuideTextTest(unittest.TestCase):
    """检测页机型脚本那一行（标签与说明）的逐字文案与分支。"""

    def recipe(self, **over):
        base = {"info": {"name": "Phone X", "brand": "OPPO", "model": "PX1", "os": "16"},
                "steps": ["桌面"], "recipe": "oppo-PX1", "recipe_ok": True, "recipe_ref": False}
        base.update(over)
        return view._recipe(base, base["info"])

    def test_no_steps_has_no_recipe_line(self):
        self.assertEqual(self.recipe(steps=[], recipe=None), (None, ""))

    def test_own_recipe_runs_everything(self):
        self.assertEqual(self.recipe(),
                         ("按机型脚本自动关",
                          "系统广告、负一屏、搜索、商店、浏览器、主题等 App 里的推荐和广告开关。"
                          "「防止 / 限制广告跟踪」这类保护开关会打开。"))

    def test_reference_recipe_runs_in_safe_mode(self):
        self.assertEqual(self.recipe(recipe="oppo-X", recipe_ref=True, recipe_ok=False),
                         ("试用同品牌参考脚本（oppo-X 录制）",
                          "安全模式：只关脚本里点名的开关，不做整页全关；页面不一样时，找不到入口的步骤会跳过。"
                          "「防止 / 限制广告跟踪」这类保护开关会打开。"))

    def test_reference_without_a_name_drops_the_parenthetical(self):
        self.assertEqual(self.recipe(recipe="", recipe_ref=True)[0], "试用同品牌参考脚本")

    def test_version_mismatch_prefixes_the_safe_mode_note(self):
        self.assertEqual(self.recipe(recipe_ok=False, recipe_build="15")[1],
                         "脚本按 15 录，这台是 16。"
                         "安全模式：只关脚本里点名的开关，不做整页全关；页面不一样时，找不到入口的步骤会跳过。"
                         "「防止 / 限制广告跟踪」这类保护开关会打开。")

    def test_version_falls_back_to_build_when_os_is_missing(self):
        self.assertIn("这台是 16", self.recipe(recipe_ok=False, info={"build": "16"})[1])


class ChecklistTextTest(unittest.TestCase):
    """没有本机脚本时，App 里的开关要照手动清单关。"""

    def test_own_recipe_has_no_manual_checklist(self):
        self.assertEqual(view._checklist({"recipe": "x", "recipe_ref": False}, {}), ("", ""))

    def test_known_brand_links_its_own_file(self):
        name, url = view._checklist({"recipe": None, "recipe_ref": False}, {"brand": "OPPO"})
        self.assertEqual(name, "OPPO / ColorOS")
        self.assertEqual(unquote(url), f"{view.REPO}/blob/main/docs/清单/OPPO-ColorOS.md")

    def test_unknown_brand_goes_to_the_checklist_readme(self):
        name, url = view._checklist({}, {"brand": "Nokia"})
        self.assertEqual(name, "")
        self.assertEqual(unquote(url), f"{view.REPO}/blob/main/docs/清单/README.md")

    def test_missing_brand_goes_to_the_readme(self):
        self.assertEqual(unquote(view._checklist({}, {"brand": ""})[1]),
                         f"{view.REPO}/blob/main/docs/清单/README.md")


class QuickappTextTest(unittest.TestCase):
    """快应用那一栏的名单与说明逐字，四种状态各一条。"""

    def test_nothing_detected(self):
        self.assertEqual(view._quickapp({"quickapps": []}), ([], "", "没有检测到"))

    def test_all_closed_without_kept(self):
        self.assertEqual(view._quickapp({"quickapps": [{"name": "A", "closed": True}]}),
                         ([], "", "已关闭"))

    def test_all_closed_with_a_kept_component(self):
        self.assertEqual(view._quickapp({"quickapps": [{"name": "A", "closed": True},
                                                       {"name": "C", "keep": True}]}),
                         ([], "", "已关闭（保留 1 个系统组件）"))

    def test_still_on_without_kept(self):
        self.assertEqual(view._quickapp({"quickapps": [{"name": "B"}]}),
                         (["B"],
                          "广告常用 hap:// 链接把人跳进快应用。关闭后系统会拦截这类入口；"
                          "vivo 优先使用快应用服务开关，其他支持的机型使用挂起。"
                          "请确认负一屏快递卡片等常用服务不依赖快应用。可还原。",
                          ""))

    def test_recently_used_changes_the_confirmation_sentence(self):
        self.assertEqual(view._quickapp({"quickapps": [{"name": "B", "used": True}]}),
                         (["B"],
                          "广告常用 hap:// 链接把人跳进快应用。关闭后系统会拦截这类入口；"
                          "vivo 优先使用快应用服务开关，其他支持的机型使用挂起。"
                          "检测到近期打开过，确认不是你主动在用。可还原。",
                          ""))

    def test_a_kept_component_changes_the_reason(self):
        self.assertIn("快应用平台会保留（负一屏快递卡片等系统服务依赖它），广告仍可能通过 hap:// 跳进快应用；",
                      view._quickapp({"quickapps": [{"name": "B"}, {"name": "C", "keep": True}]})[1])

    def test_a_quickapp_without_a_name_shows_an_empty_label(self):
        self.assertEqual(view._quickapp({"quickapps": [{}]})[0], [""])


class AdsTextTest(unittest.TestCase):
    """系统广告组件那栏：已知名字、未知兜底、已挂起。"""

    def test_known_component_has_a_name(self):
        self.assertEqual(view._ads({"ads": [{"pkg": "com.opos.ads"}]}),
                         ([{"pkg": "com.opos.ads", "name": "OPPO 广告服务", "default_on": False}], ""))

    def test_unknown_component_falls_back_to_a_generic_name(self):
        self.assertEqual(view._ads({"ads": [{"pkg": "com.unknown.x"}]}),
                         ([{"pkg": "com.unknown.x", "name": "系统广告组件", "default_on": False}], ""))

    def test_suspended_component_is_hidden_and_reported(self):
        self.assertEqual(view._ads({"ads": [{"pkg": "x.y", "suspended": True}]}), ([], "已挂起"))

    def test_none_known(self):
        self.assertEqual(view._ads({"ads": []}), ([], "没有已知的"))


class OutcomeTest(unittest.TestCase):
    def test_all_ok(self):
        self.assertEqual(view.outcome({"results": [{"rc": 0}], "cancel": False}), "ok")

    def test_stopped_is_not_failure(self):
        run = {"results": [{"rc": 1, "stopped": True}], "cancel": True}
        self.assertEqual(view.outcome(run), "stopped")
        self.assertEqual(view.outcome({"results": [], "cancel": True}), "stopped")

    def test_real_failure(self):
        self.assertEqual(view.outcome({"results": [{"rc": 1}], "cancel": False}), "failed")

    def test_cancel_of_an_all_ok_run_is_stopped_not_failed(self):
        """点到停止时已完成的步骤都是 rc=0：仍算「已停止」，不是失败。"""
        self.assertEqual(view.outcome({"results": [{"rc": 0}], "cancel": True}), "stopped")

    def test_poll_and_snapshot_pass_since_through(self):
        api = FakeApi(run={"results": []})
        view.poll(api, 7)
        view._snapshot(api)
        default = FakeApi(run={"results": []})
        view.poll(default)
        self.assertEqual(api.sinces, [7, 0])
        self.assertEqual(default.sinces, [0])

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


class RecipeCoverageTest(unittest.TestCase):
    """机型脚本验到什么程度：只在负面的两档给结果页多一行（沿用 #1124 的档位，#1130）。

    档位是引擎从台账现读、随 `status-json` 到客户端；说不说、怎么说都在 Python 这边，
    Compose 只把这一行画出来。这里验手机版这条通路接上了 `tool/coverage_note.py`；判据本身与
    按宿主分叉的措辞都在 tests/test_coverage_note.py（#1188）。"""

    def snap(self, coverage="部分", **row):
        """一次跑过机型脚本的结果页快照：默认这一行是成功的那一步。

        成功行照引擎的原样不写 `skipped`（`step_result()` 只在跳过时才带它）：拿显式 False 去喂，
        `not r.get("skipped")` 被改成 `is False` 也照样绿。档位照 job 快照原样放在 `recipe_coverage`。"""
        done = {"title": "关闭各 App 里的广告开关", "kind": "recipe", "rc": 0, **row}
        api = FakeApi(run={"results": [done], "cancel": False, "recipe_coverage": coverage})
        return view.poll(api)

    def test_partial_coverage_adds_a_line(self):
        note = self.snap("部分")["coverage_note"]
        self.assertIn("只在一部分步骤上做过真机验证", note)
        self.assertNotIn("App", note, "手机版措辞不说「去 App 里核对」——用户本来就在 App 里")
        for word in ("tier", "evidence", "部分验证"):
            self.assertNotIn(word, note, "文案不能露出内部取值名")

    def test_full_coverage_adds_nothing(self):
        self.assertEqual(self.snap("全部")["coverage_note"], "")

    def test_a_script_with_no_ledger_entry_says_so(self):
        self.assertIn("没有真机验证记录", self.snap("未记录")["coverage_note"])

    def test_an_unknown_or_missing_tier_says_nothing(self):
        for value in ("", "以后的第四档", None):
            with self.subTest(coverage=value):
                self.assertEqual(self.snap(value)["coverage_note"], "")

    def test_a_skipped_recipe_step_means_no_line(self):
        # 没勾脚本 / 这台机没有专用脚本：那一行是「跳过」，拿别的步的结论说脚本的事会误导
        self.assertEqual(self.snap("部分", skipped=True)["coverage_note"], "")

    def test_a_run_that_never_touched_the_script_has_no_line(self):
        run = {"results": [{"title": "关闭营销通知", "kind": "channels", "rc": 0}], "cancel": False,
               "recipe_coverage": "未记录"}
        self.assertEqual(view.poll(FakeApi(run=run))["coverage_note"], "")

    def test_a_snapshot_without_the_tier_says_nothing(self):
        # 旧载荷 / 没勾脚本时快照里就没有这个字段：结果页照常显示，不炸、也不猜深浅
        run = {"results": [{"title": "关闭各 App 里的广告开关", "kind": "recipe", "rc": 0}], "cancel": False}
        self.assertEqual(view.poll(FakeApi(run=run))["coverage_note"], "")


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

    def test_status_is_asked_for_the_given_serial(self):
        api = FakeApi(status())
        view.detect(api, "abc123")
        self.assertEqual(api.serial, "abc123")

    def test_names_the_phone_and_passes_the_model_through(self):
        d = self.detect(info={"name": "Phone X", "brand": "OPPO", "model": "PX1", "os": "16"})
        self.assertEqual((d["name"], d["model"]), ("Phone X", "PX1"))

    def test_missing_name_and_model_fall_back(self):
        d = self.detect(info={"brand": "OPPO"}, steps=[], recipe=None)
        self.assertEqual((d["name"], d["model"]), ("OPPO", ""))

    def test_name_falls_back_to_model_alone_when_brand_is_missing(self):
        d = self.detect(info={"model": "PX1"}, steps=[], recipe=None)
        self.assertEqual((d["name"], d["model"]), ("PX1", "PX1"))

    def test_rich_status_returns_the_whole_view(self):
        d = view.detect(FakeApi(status(
            info={"brand": "XIAOMI", "model": "23127PN0CC", "os": "15"},
            steps=["桌面", "浏览器"], recipe="xiaomi-23127PN0CC", recipe_ref=True, recipe_ok=False,
            recipe_build="14", quickapps=[{"name": "A"}, {"name": "C", "keep": True}],
            ads=[{"pkg": "com.opos.ads"}])), "serial")
        expected = {
            "name": "XIAOMI 23127PN0CC", "model": "23127PN0CC",
            "warnings": [], "blocked": False, "steps": ["桌面", "浏览器"], "ref": True,
            "recipe_label": "试用同品牌参考脚本（xiaomi-23127PN0CC 录制）",
            "recipe_note": "安全模式：只关脚本里点名的开关，不做整页全关；页面不一样时，找不到入口的步骤会跳过。"
                           "「防止 / 限制广告跟踪」这类保护开关会打开。",
            "manual_name": "小米 / HyperOS",
            "manual_url": f"{view.REPO}/blob/main/docs/清单/小米-HyperOS.md",
            "quickapps": ["A"],
            "quickapp_note": "广告常用 hap:// 链接把人跳进快应用。"
                             "快应用平台会保留（负一屏快递卡片等系统服务依赖它），广告仍可能通过 hap:// 跳进快应用；"
                             "vivo 优先使用快应用服务开关，其他支持的机型使用挂起。"
                             "请确认负一屏快递卡片等常用服务不依赖快应用。可还原。",
            "quickapp_state": "",
            "ads": [{"pkg": "com.opos.ads", "name": "OPPO 广告服务", "default_on": False}],
            "ads_state": "",
        }
        self.assertEqual({**d, "manual_url": unquote(d["manual_url"])}, expected)

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

    def test_samsung_huawei_meizu_land_on_their_own_checklist(self):
        """没有专用脚本时，这几家的按钮要落到自己那份清单并写上品牌名（#952、#1293）。"""
        want = {"samsung": ("三星 / One UI", "三星-OneUI.md"),
                "huawei": ("华为 / HarmonyOS", "华为-HarmonyOS.md"),
                "meizu": ("魅族 / Flyme", "魅族-Flyme.md"),
                "coolpad": ("酷派 / FreemeOS", "FreemeOS.md"),
                "5G": ("酷派 / FreemeOS", "FreemeOS.md")}
        for brand, (name, filename) in want.items():
            with self.subTest(brand=brand):
                d = self.detect(steps=[], recipe=None, info={"brand": brand})
                self.assertEqual(d["manual_name"], name)
                self.assertEqual(unquote(d["manual_url"]), f"{view.REPO}/blob/main/docs/清单/{filename}")

    def test_every_checklist_entry_has_a_name_and_a_file(self):
        """旧树也绿，守的是表里每一项都有名字、对应文件也真在仓库里，不回退。"""
        for filename in view.CHECKLIST.values():
            with self.subTest(filename=filename):
                self.assertTrue(view.CHECKLIST_NAME.get(filename))
                self.assertTrue((ROOT / "docs" / "清单" / filename).is_file())

    def test_reference_recipe_runs_in_safe_mode(self):
        d = self.detect(recipe="oppo-PX9", recipe_ref=True, recipe_ok=False)
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
        self.assertEqual(d["ads"], [{"pkg": "com.opos.ads", "name": "OPPO 广告服务", "default_on": False}])
        d = self.detect(quickapps=[{"name": "A", "closed": True}], ads=[{"pkg": "x", "suspended": True}])
        self.assertEqual((d["quickapp_state"], d["ads_state"]), ("已关闭", "已挂起"))
        d = self.detect(quickapps=[{"name": "A", "closed": True}, {"name": "C", "keep": True}])
        self.assertEqual(d["quickapp_state"], "已关闭（保留 1 个系统组件）")
        d = self.detect()
        self.assertEqual((d["quickapp_state"], d["ads_state"]), ("没有检测到", "没有已知的"))

    def test_xiaomi_ad_component_says_partial_success_is_reported(self):
        d = self.detect(ads=[{"pkg": "com.miui.systemAdSolution"}])
        self.assertIn("会报告部分完成", d["ads"][0]["name"])

    def test_default_mark_reaches_the_phone_selection_page(self):
        """#973：预勾与否由 status-json 的 default_on 给，手机版只透传，不在 Kotlin 里再判一次。"""
        d = self.detect(ads=[{"pkg": "com.miui.systemAdSolution", "default_on": True},
                             {"pkg": "com.opos.ads", "default_on": False}])
        self.assertEqual([(a["pkg"], a["default_on"]) for a in d["ads"]],
                         [("com.miui.systemAdSolution", True), ("com.opos.ads", False)])


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

    def test_each_brand_reads_its_own_row(self):
        want = {"Xiaomi": "「关于手机」里的「OS 版本」",
                "vivo": "「关于手机 → 版本信息」里的「软件版本号」",
                "OPPO": "「关于本机 → 版本信息」里的「版本号」",
                "HONOR": "「关于手机」里的「版本号」",
                "Nokia": "「关于手机」里的「版本号」"}
        for brand, tap in want.items():
            with self.subTest(brand=brand):
                self.assertEqual(view.brand_guide(None, brand)["tap"], tap)

    def test_reads_the_single_source_by_exact_path_and_utf8(self):
        """读的是 `docs/brand-taps.json` 且显式 UTF-8，路径与编码都不能靠文件系统兜底。"""
        with mock.patch("builtins.open", wraps=open) as op:
            view.brand_guide(None, "OPPO")
        self.assertEqual(Path(op.call_args.args[0]), Path(self.tmp.name, "docs", "brand-taps.json"))
        # 刻意锁住路径与编码：这是「只在大小写不敏感文件系统 / 只在 mock 注册上等价」的变异的
        # 唯一区分手段，不锁就只能算存活；不锁一般的调用序列。
        self.assertEqual(op.call_args.kwargs.get("encoding"), "utf-8")


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
        self.assertEqual(api.copied[0][:2], "##")

    def test_send_uses_the_kind_and_opens_the_real_url(self):
        api = FakeApi()
        view.send_feedback(api, "idea", "短", "")
        self.assertIn("template=feature_request.md", api.opened[0])

    def test_unknown_kind_falls_back_to_the_bug_template(self):
        q = self.query(view.feedback_url("nope", "卡住了", "")[0])
        self.assertEqual(q["template"], ["bug_report.md"])
        self.assertEqual(q["title"], ["[问题] 卡住了"])

    def test_title_keeps_at_most_sixty_chars_of_the_first_line(self):
        q = self.query(view.feedback_url("bug", "x" * 61, "")[0])
        self.assertEqual(q["title"], ["[问题] " + "x" * 60])

    def test_title_comes_from_the_first_line_only(self):
        """标题只取第一行：按空白切会把它截成第一个词。"""
        q = self.query(view.feedback_url("bug", "a b\nc", "")[0])
        self.assertEqual(q["title"], ["[问题] a b"])

    def test_no_diag_body_has_only_the_description(self):
        self.assertEqual(self.query(view.feedback_url("bug", "卡住了", "")[0])["body"],
                         ["## 描述\n\n卡住了\n"])

    def test_a_url_exactly_at_the_limit_stays_inline(self):
        """网址恰好等于上限时不裁剪：`<=` 与 `<`、`>=` 在这里才分得开。"""
        url, clip = view.feedback_url("bug", "a" * 7283, "")
        self.assertEqual((len(url), clip), (view.URL_LIMIT, ""))

    def test_trimming_keeps_the_last_forty_log_lines(self):
        log = "\n".join(f"第 {i} 行日志" for i in range(600))
        diag = f"手机：PX1\n<details>\n```text\n{log}\n```\n</details>"
        body = self.query(view.feedback_url("bug", "卡住了", diag)[0])["body"][0]
        self.assertIn("第 560 行日志", body)
        self.assertNotIn("第 559 行日志", body)
        self.assertIn("第 560 行日志\n第 561 行日志", body)   # 行间用单个换行连，不夹别的字

    def _trimmed(self, head, lines):
        diag = f"{head}\n<details>\n```text\n" + "\n".join("x" * 50 for _ in range(lines)) + "\n```\n</details>"
        url, clip = view.feedback_url("bug", "卡住了", diag)
        self.assertTrue(clip)
        return self.query(url)["body"][0]

    def test_hitting_the_minimum_keeps_the_brief_hint(self):
        """循环跑到 n=0 时正文取空日志，仍走「已复制到剪贴板」那句，不掉进兜底。"""
        body = self._trimmed("H" * 6906, 5)
        self.assertNotIn("请在这里粘贴", body)
        self.assertTrue(body.rstrip().endswith("可以粘贴在这里）"))
        self.assertNotIn("XXXX", body)

    def test_trimming_stops_with_some_log_left(self):
        self.assertIn("x" * 50, self._trimmed("H" * 6642, 10))

    def test_a_body_exactly_at_the_limit_keeps_the_log(self):
        body = self._trimmed("H" * 6645, 10)
        self.assertIn("x" * 50, body)
        self.assertNotIn("请在这里粘贴", body)

    def test_trimmed_body_keeps_the_head_with_its_spaces(self):
        """诊断头按 `<details>` 切，不按空白切，否则「手机：PX 1」会被截成「手机：PX」。"""
        log = "\n".join(f"L{i}" for i in range(3000))
        diag = f"手机：PX 1\n<details>\n```text\n{log}\n```\n</details>"
        url, clip = view.feedback_url("bug", "卡住了", diag)
        self.assertTrue(clip)
        self.assertIn("手机：PX 1", self.query(url)["body"][0])

    def test_a_long_body_without_a_fence_trims_without_a_placeholder(self):
        """诊断带 <details> 但没有 ```text 围栏时取不到日志：裁剪正文里不能塞占位串（#1430）。"""
        diag = "head\n<details>\n" + "z" * 9000
        url, clip = view.feedback_url("bug", "卡住了", diag)
        self.assertTrue(clip)
        self.assertNotIn("XXXX", self.query(url)["body"][0])


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


class SmokeExportTest(unittest.TestCase):
    """真机冒烟的 debug 导出（#1072）：logd 单条约 4 KB，按字节切、只留每一步的结果。"""

    def test_chunks_fit_the_logcat_limit_in_bytes(self):
        chunks = view._chunks("关闭的渠道" * 2000)
        self.assertGreater(len(chunks), 1, "这份结果要真的被分成多块")
        for chunk in chunks:
            self.assertLessEqual(len(chunk.encode()), view.EXPORT_LIMIT, "中文按字节算才不会超")
        self.assertEqual("".join(chunks), "关闭的渠道" * 2000, "拼回来要一字不差")

    def test_lines_are_left_out_and_chunks_reassemble(self):
        run = {"running": True, "cancel": False, "results": [], "lines": ["一行日志" * 500]}
        out = view.smoke_export(FakeApi(run=run), "ready")
        payload = json.loads("".join(out["chunks"]))
        self.assertEqual(payload["shell"], "ready")
        self.assertNotIn("lines", payload["run"])

    def test_only_the_step_summary_survives(self):
        run = {"running": False, "cancel": False, "results": [
            {"title": "系统广告", "rc": 0, "skipped": False, "stopped": False, "sec": 3,
             "tail": ["机型脚本跑完：关了 12 个，34 秒"], "failed_steps": ["负一屏与搜索"],
             "kind": "steps"}]}
        payload = json.loads("".join(view.smoke_export(FakeApi(run=run), "ready")["chunks"]))
        row = payload["run"]["results"][0]
        self.assertEqual(row["summary"], "关了 12 个开关")
        self.assertEqual(set(row), {"title", "rc", "skipped", "stopped", "sec", "summary"})
        self.assertTrue(payload["finished"])

    def test_finished_needs_results_or_a_cancel(self):
        self.assertFalse(view.smoke_export(FakeApi(run={"running": False, "results": []}))["finished"])
        self.assertFalse(view.smoke_export(FakeApi(run={"running": True, "results": [],
                                                        "cancel": False}))["finished"])
        self.assertTrue(view.smoke_export(FakeApi(run={"running": False, "cancel": True,
                                                       "results": []}))["finished"])

    def test_running_is_reported_at_the_top_level(self):
        """Kotlin 靠这个字段决定导出循环要不要继续；藏在 chunks 里它读不到（#1072 真机）。"""
        self.assertTrue(view.smoke_export(FakeApi(run={"running": True, "results": []}))["running"])
        self.assertFalse(view.smoke_export(FakeApi(run={"running": False, "results": []}))["running"])

    def test_the_export_is_registered_for_the_client(self):
        self.assertIn("smoke_export", view.EXPORTS)

    def payload(self, **run):
        return json.loads("".join(view.smoke_export(FakeApi(run=run), "ready")["chunks"]))

    def test_the_full_payload_has_exactly_the_agreed_shape(self):
        payload = self.payload(running=False, cancel=False, idx=2, total=3, title="系统广告", sec=12,
                               recovery="", outcome="ok",
                               results=[{"title": "系统广告", "rc": 0, "skipped": False,
                                         "stopped": False, "sec": 3}])
        self.assertEqual(payload, {
            "shell": "ready", "finished": True,
            "run": {"running": False, "cancel": False, "idx": 2, "total": 3, "title": "系统广告",
                    "sec": 12, "outcome": "ok", "recovery": "",
                    "results": [{"title": "系统广告", "rc": 0, "skipped": False,
                                 "stopped": False, "sec": 3, "summary": ""}]}})

    def test_missing_fields_use_the_documented_defaults(self):
        payload = self.payload()
        self.assertEqual(payload["run"], {"running": False, "cancel": False, "idx": 0, "total": 0,
                                          "title": "", "sec": 0, "outcome": "ok", "recovery": "",
                                          "results": []})
        self.assertFalse(payload["finished"])

    def test_running_with_results_is_not_finished(self):
        out = view.smoke_export(FakeApi(run={"running": True, "results": [{"rc": 0}]}), "")
        self.assertEqual((out["running"], out["finished"]), (True, False))
        self.assertTrue(json.loads("".join(out["chunks"]))["run"]["running"])

    def test_a_cancelled_run_is_finished(self):
        self.assertTrue(self.payload(running=False, cancel=True)["run"]["cancel"])

    def test_shell_defaults_to_empty(self):
        payload = json.loads("".join(view.smoke_export(FakeApi(run={}))["chunks"]))
        self.assertEqual(payload["shell"], "")

    def test_recovery_is_carried_through(self):
        self.assertEqual(self.payload(recovery="saved")["run"]["recovery"], "saved")

    def test_the_chunks_keep_the_chinese_unescaped(self):
        """写出的是 UTF-8 而不是 \\u 转义：日志与模板都要能直接读（ensure_ascii=False）。"""
        raw = "".join(view.smoke_export(FakeApi(run={"title": "系统广告"}), "")["chunks"])
        self.assertIn("系统广告", raw)

    def test_the_flag_is_false_not_the_equivalent_none(self):
        """ensure_ascii 传的是 False 而不是等价的 None：json 只看真假，输出分不开，只能锁参数。"""
        with mock.patch("json.dumps", wraps=json.dumps) as dumps:
            view.smoke_export(FakeApi(run={"title": "系统广告"}), "")
        self.assertIs(dumps.call_args.kwargs.get("ensure_ascii"), False)


class SetupStepsTextTest(unittest.TestCase):
    """首次设置三步的文案逐字：页面与通知栏都从这一份取，改一个字用户就照错的点。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        docs = Path(self.tmp.name, "docs")
        docs.mkdir()
        docs.joinpath("brand-taps.json").write_text(
            (ROOT / "docs" / "手机版教程" / "brand-taps.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        old, view.BASE = view.BASE, self.tmp.name
        self.addCleanup(setattr, view, "BASE", old)

    def shape(self, brand):
        steps = view.setup_steps(brand)
        return ([s["lines"] for s in steps],
                [s["notice"]["text"] if s["notice"] else None for s in steps],
                [(s["key"], s["title"], s["action"], s["note"]) for s in steps])

    def test_oppo(self):
        lines, notices, meta = self.shape("OPPO")
        self.assertEqual(lines, [
            ["点下面的按钮，进入系统设置", "连点「关于本机 → 版本信息」里的「版本号」 7 下，输入锁屏密码",
             "看到「已处于开发者模式」，回到这里"],
            ["连上 Wi-Fi，点下面的按钮", "打开「无线调试」", "弹窗里勾「始终允许」，点「允许」"],
            ["点下面的按钮，共享屏幕时选「整个屏幕」，点「立即开始」",
             "在打开的页面点「无线调试」→「使用配对码配对设备」",
             "本 App 读出 6 位数字自己完成授权，你不用输入"]])
        self.assertEqual(notices, [
            "连点「关于本机 → 版本信息」里的「版本号」 7 下，输入锁屏密码；看到「已处于开发者模式」就回到「肉呆去广告」。",
            "打开「无线调试」，弹窗里勾「始终允许」再点「允许」，然后回到「肉呆去广告」。",
            None])
        self.assertEqual(meta, [("about", "打开开发者选项", "打开「关于手机」", ""),
                                ("dev", "打开无线调试", "打开开发者选项", ""),
                                ("pair", "授权本 App", "开始授权",
                                 "截屏只在这台手机上识别数字，不保存、不上传，授权完成就停。")])

    def test_redmi_adds_the_usb_debugging_step(self):
        lines, notices, meta = self.shape("Redmi")
        self.assertEqual(lines[0][1], "连点「关于手机」里的「OS 版本」 7 下，输入锁屏密码")
        self.assertEqual(lines[1], ["连上 Wi-Fi，点下面的按钮", "打开「USB 调试（安全设置）」，不然点不动下一个开关",
                                    "打开「无线调试」", "弹窗里勾「始终允许」，点「允许」"])
        self.assertEqual(lines[2][1], "在打开的页面点「无线调试」→「输入配对码配对设备」")
        self.assertEqual(notices[0],
                         "连点「关于手机」里的「OS 版本」 7 下，输入锁屏密码；看到「已处于开发者模式」就回到「肉呆去广告」。")
        self.assertEqual(notices[1],
                         "先打开「USB 调试（安全设置）」；打开「无线调试」，弹窗里勾「始终允许」再点「允许」，"
                         "然后回到「肉呆去广告」。")
        self.assertEqual([m[0] for m in meta], ["about", "dev", "pair"])

    def test_vivo_uses_its_own_version_label(self):
        lines, notices, _ = self.shape("vivo")
        self.assertEqual(lines[0][1], "连点「关于手机 → 版本信息」里的「软件版本号」 7 下，输入锁屏密码")
        self.assertEqual(lines[1], ["连上 Wi-Fi，点下面的按钮", "打开「无线调试」", "弹窗里勾「始终允许」，点「允许」"])
        self.assertEqual(notices[0],
                         "连点「关于手机 → 版本信息」里的「软件版本号」 7 下，输入锁屏密码；"
                         "看到「已处于开发者模式」就回到「肉呆去广告」。")


class LazyModuleTest(unittest.TestCase):
    """共享实现的懒加载 + 缓存：清掉工具目录后不再重新加载（#1189 #1188）。"""

    def test_summary_module_is_loaded_once(self):
        saved = view._summary
        view._summary = None
        self.addCleanup(setattr, view, "_summary", saved)
        first = view._summary_module()
        self.assertIs(view._summary_module(), first)
        self.assertTrue(hasattr(first, "MACHINE_PREFIX"))

    def test_coverage_note_module_is_loaded_once(self):
        saved = view._coverage_note
        view._coverage_note = None
        self.addCleanup(setattr, view, "_coverage_note", saved)
        first = view._coverage_note_module()
        self.assertIs(view._coverage_note_module(), first)
        self.assertTrue(hasattr(first, "note"))


class StallWatchInitTest(unittest.TestCase):
    def test_initial_state(self):
        watch = view.StallWatch(now=lambda: 5)
        self.assertIsNone(watch.mark)
        self.assertEqual(watch.since, 5)
        self.assertEqual(watch.now(), 5)


if __name__ == "__main__":
    unittest.main()
