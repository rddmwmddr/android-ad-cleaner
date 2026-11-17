"""WKL-AN20：型号匹配、精确开关范围、确认按钮和账号页截图保护。"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import run
import fixtures
from fixtures import load_recipe, phone_stub, shell_result


class HonorWKLRecipeTests(unittest.TestCase):
    def load(self, phone):
        scope, _ = load_recipe(phone, ROOT / "recipes/honor/WKL-AN20/WKL-AN20.toml")
        return scope

    def phone(self, xml="<hierarchy/>"):
        p = phone_stub("test", reader=Mock())
        p.W, p.H = 1080, 2400
        p.conn.reader.window_size.return_value = (p.W, p.H)
        p.screen.tree = Mock(return_value=ET.fromstring(xml))
        p.locked = Mock(return_value=False)
        return p

    def closing_scope(self, before, after):
        p = Mock(changed=[])
        p.screen = p      # 机型脚本直接写 p.focus()，与观测基座用同一处桩
        p.screen.focus.return_value = "com.example/.Settings"
        p.screen.tree.return_value = ET.fromstring("<hierarchy/>")
        scope = self.load(p)
        for name, mock in (
                ("settle_page", Mock()),
                ("labels", Mock(return_value={"设置"})),
                ("scan_switches", Mock(side_effect=[before, after]))):
            fixtures.patch_surface(self, name, mock)
            scope[name] = mock
        return p, scope

    def test_model_build_and_steps_are_discoverable_by_runner(self):
        path, reference = run.recipe_for("WKL-AN20", "HONOR")
        self.assertFalse(reference)
        meta = run.recipe_meta(path)
        self.assertEqual(Path(path).parent.name, "WKL-AN20")
        self.assertEqual(meta["build"], "WKL-AN20 11.0.0.111(SP7C00E110R101P7)")
        self.assertEqual(len(meta["steps"]), 13)
        self.assertIn("音乐", meta["steps"])
        self.assertEqual(set(meta["steps"]), set(self.load(Mock())["CHANGES"]))

    def test_wrong_build_does_not_enter_any_action(self):
        p = Mock()
        p.shell.side_effect = [shell_result("WKL-AN20", 0), shell_result("another build", 0)]
        scope = self.load(p)
        scope["ONLY"] = ["系统管家"]
        action = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            scope["rt"].run_step("系统管家", action)
        action.assert_not_called()
        p.start.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["RESULTS"], [("系统管家", "跳过")])

    def test_wrong_model_is_skipped_not_failed(self):
        p = Mock()
        p.shell.side_effect = [shell_result("OTHER-MODEL", 0), shell_result("WKL-AN20 11.0.0.111", 0)]
        scope = self.load(p)
        scope["ONLY"] = ["系统管家"]
        action = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            scope["rt"].run_step("系统管家", action)
        action.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_full_run_skips_music_step_without_failing(self):
        """音乐段全跑时按约定跳过；记成未完成会让每轮全跑都退出码 1。

        `_` 是模块里最后一个 `@step` 装饰的段函数，也就是「音乐」这一段的函数体。
        """
        p = Mock()
        p.locked.return_value = False
        p.shell.side_effect = [shell_result("WKL-AN20", 0), shell_result("WKL-AN20 11.0.0.111(SP7C00E110R101P7)", 0)]
        scope = self.load(p)
        scope["ONLY"] = []
        with contextlib.redirect_stdout(io.StringIO()):
            action = next(st.action for st in scope["rt"].steps if st.name == "音乐")
            scope["rt"].run_step("音乐", action)
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["RESULTS"], [("音乐", "跳过")])

    def test_skip_step_does_not_enter_failed_steps(self):
        p = Mock()
        p.locked.return_value = False
        p.shell.side_effect = [shell_result("WKL-AN20", 0), shell_result("WKL-AN20 11.0.0.111(SP7C00E110R101P7)", 0)]
        scope = self.load(p)
        scope["ONLY"] = ["系统管家"]
        with contextlib.redirect_stdout(io.StringIO()):
            scope["rt"].run_step("系统管家", Mock(side_effect=scope["SkipStep"]("按约定跳过")))
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["RESULTS"], [("系统管家", "跳过")])

    def test_device_loss_is_not_swallowed_as_a_skipped_step(self):
        p = Mock()
        p.shell.side_effect = adb_link.DeviceLost("lost")
        scope = self.load(p)
        scope["ONLY"] = ["系统管家"]
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(adb_link.DeviceLost):
            scope["rt"].run_step("系统管家", Mock())

    def test_missing_switch_stops_before_any_changes(self):
        p, scope = self.closing_scope({"应用更新": True}, {})
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            scope["close_named_honor"](["个性化广告"], "测试", "com.example", "设置")
        scope["settle_page"].assert_called_once()
        p.off.assert_not_called()
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_similar_title_and_service_switch_do_not_reach_off(self):
        p, scope = self.closing_scope(
            {"个性化广告": True, "个性化广告服务说明": True, "应用更新": True},
            {"个性化广告": False, "个性化广告服务说明": True, "应用更新": True})
        p.switches.return_value = [("个性化广告", True, (100, 300)),
                                   ("个性化广告服务说明", True, (100, 400)),
                                   ("应用更新", True, (100, 500))]
        filtered = []
        p.off.side_effect = lambda **kw: filtered.extend(p.switches())
        scope["close_named_honor"](["个性化广告"], "测试", "com.example", "设置")
        scope["settle_page"].assert_called_once()
        self.assertEqual([row[0] for row in filtered], ["个性化广告"])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_reverted_target_is_not_reported_as_verified(self):
        p, scope = self.closing_scope({"个性化广告": True}, {"个性化广告": True})
        with self.assertRaisesRegex(RuntimeError, "回读未确认"):
            scope["close_named_honor"](["个性化广告"], "测试", "com.example", "设置")
        scope["settle_page"].assert_called_once()
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_unrelated_change_is_not_reported_as_verified(self):
        p, scope = self.closing_scope({"个性化广告": True, "评论提醒": True},
                                     {"个性化广告": False, "评论提醒": False})
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            scope["close_named_honor"](["个性化广告"], "测试", "com.example", "设置")
        scope["settle_page"].assert_called_once()
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_protection_switch_must_be_on(self):
        p, scope = self.closing_scope({"限制广告跟踪": False}, {"限制广告跟踪": True})
        scope["close_named_honor"](["限制广告跟踪"], "测试", "com.example", "设置")
        scope["settle_page"].assert_called_once()
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_account_page_custom_switch_never_takes_screenshot(self):
        p = self.phone('''<hierarchy><node text="我的" bounds="[0,50][100,100]"/>
          <node resource-id="app:id/switch" class="android.widget.ImageView"
           clickable="true" bounds="[900,400][1000,450]"/></hierarchy>''')
        scope = self.load(p)
        with scope["safe_ui"](p, scope["rt"]):
            self.assertEqual(p.switches(), [])
        p.conn.reader.screenshot.assert_not_called()

    def test_offscreen_and_disabled_confirmation_buttons_are_ignored(self):
        p = self.phone('''<hierarchy>
          <node text="确定" class="android.widget.Button" bounds="[2000,500][2100,600]"/>
          <node text="确定" class="android.widget.Button" enabled="false" bounds="[500,500][600,600]"/>
          <node text="确定" class="android.widget.Button" bounds="[500,700][600,800]"/>
          </hierarchy>''')
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"), scope["safe_ui"](p, scope["rt"]):
            self.assertEqual(p.confirm(), "确定")
        p.conn.reader.shell.assert_called_once_with("input swipe 550 750 550 750 80")

    def test_text_confirmation_requires_the_specific_music_dialog(self):
        p = self.phone('''<hierarchy><node text="确定" class="android.widget.TextView"
                           bounds="[500,700][600,800]"/></hierarchy>''')
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"), scope["safe_ui"](p, scope["rt"]):
            self.assertIsNone(p.confirm())
        p.conn.reader.shell.assert_not_called()
        root = p.screen.tree.return_value
        ET.SubElement(root, "node", text="关闭个性化广告推荐", bounds="[100,300][800,400]")
        ET.SubElement(root, "node", text="取消", bounds="[100,700][200,800]")
        with patch.object(scope["time"], "sleep"), scope["safe_ui"](p, scope["rt"]):
            self.assertEqual(p.confirm(), "确定")
        p.conn.reader.shell.assert_called_once_with("input swipe 550 750 550 750 80")

    def test_helpers_are_restored_even_when_action_fails(self):
        p = self.phone()
        scope = self.load(p)
        originals = {name: getattr(p, name) for name in ("click", "scroll", "confirm", "switches")}
        with self.assertRaisesRegex(RuntimeError, "stop"):
            with scope["safe_ui"](p, scope["rt"]):
                raise RuntimeError("stop")
        for name, value in originals.items():
            self.assertEqual(getattr(p, name), value)

    def test_homepage_radio_must_belong_to_the_named_option(self):
        p = self.phone('''<hierarchy><node bounds="[0,0][1080,2400]">
          <node text="简洁首页" bounds="[50,200][500,250]"/>
          <node class="android.widget.RadioButton" checkable="true" checked="true"
           bounds="[900,1600][1000,1700]"/>
          </node></hierarchy>''')
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "唯一单选按钮"):
            scope["radio"](p, scope["rt"], p.tree(), "简洁首页")
        p.conn.reader.shell.assert_not_called()
        root = ET.fromstring('''<hierarchy><node bounds="[0,200][1080,400]">
          <node text="简洁首页" bounds="[50,250][500,300]"/>
          <node class="android.widget.RadioButton" checkable="true" checked="false"
           bounds="[900,250][1000,300]"/>
          </node></hierarchy>''')
        self.assertEqual(scope["radio"](p, scope["rt"], root, "简洁首页").get("checked"), "false")


class DrawnSwitchReadTests(unittest.TestCase):
    """`close_named_honor(drawn=True)`：自绘页要读引擎自己那份开关表。

    段内包装器（`safe_ui`）把自绘开关的 `clickable` 抹成 false，读屏规则随即把它们过滤掉；
    「仅阅读」那一档本来就允许读它们，所以这一档必须拿 `p.switches_raw()`（引擎的读法），
    不是实例上那个包装器。"""

    def _require_switches(self, drawn):
        import recipe_lib.honor as honor
        row = ("个性化广告", True, (900, 425))
        p = phone_stub("test", reader=Mock())
        p.W, p.H = 1080, 2400
        p.screen.switches = Mock(return_value=[row])     # 引擎自己的读法
        wrapper = Mock(return_value=[])                  # 段内包装器：把自绘开关过滤掉
        p.switches = wrapper
        p.screen.tree = Mock(return_value=ET.fromstring("<hierarchy/>"))
        p.focus = Mock(return_value="com.hihonor.dz.reader/.Settings")
        p.scroll_more = Mock(return_value=False)
        p.top = Mock()
        p.off = Mock()
        rt = Mock()
        with patch.object(honor, "settle_page", Mock()), \
                patch.object(honor, "labels", Mock(return_value={"广告推荐服务"})):
            honor.close_named_honor(p, rt, ["个性化广告"], "阅读·广告推荐服务",
                                    "com.hihonor.dz.reader", "广告推荐服务", drawn=drawn)
        self.assertIs(p.switches, wrapper, "退出后 `switches` 没有还原到段内包装器")
        return rt.require_switches.call_args

    def test_the_drawn_branch_reads_the_custom_switch_through_the_engine(self):
        before, wanted, title = self._require_switches(True).args
        self.assertEqual(before, {"个性化广告": True}, "`drawn` 档没读到自绘开关")
        self.assertEqual((wanted, title), ({"个性化广告"}, "阅读·广告推荐服务"))

    def test_without_drawn_the_wrapper_still_hides_the_custom_switch(self):
        before, _wanted, _title = self._require_switches(False).args
        self.assertEqual(before, {}, "非 `drawn` 档不该绕过段内包装器")


class WklDataSegmentTests(unittest.TestCase):
    """阅读 / 魔法画报转成数据之后的行为（#1371）。

    调用序列快照对这两段是盲的（空假页面上读屏与等待都提前收场），所以判据只能落在「库收到了什么、
    按什么顺序」：阅读要先 settle 版面再点那一行；魔法画报已在画报页时不再点一次。旧树也绿，守的是
    转数据后不回退。
    """

    RECIPE = ROOT / "recipes/honor/WKL-AN20/WKL-AN20.toml"

    def record(self, *names):
        calls = []

        def make(name):
            def stub(phone, rt, *args, **kwargs):
                calls.append((name, args, kwargs))
            return stub

        for name in names:
            fixtures.patch_surface(self, name, make(name))
        return calls

    def phone(self, focus=""):
        """型号 / 版本核对通过的可编排设备：`guard` 每个段各读一次 getprop。"""
        p = Mock()
        p.locked.return_value = False
        p.shell.side_effect = [shell_result("WKL-AN20", 0),
                                 Mock(output="WKL-AN20 11.0.0.111(SP7C00E110R101P7)")]
        p.go.return_value = True
        p.setting.return_value = True
        p.focus.return_value = focus
        return p

    def test_the_reader_settles_the_drawn_switch_page_before_tapping_the_row(self):
        calls = self.record("tap", "settle_page", "close_named_honor")
        load_recipe(self.phone(), self.RECIPE, ["阅读"])
        self.assertEqual(calls, [
            ("tap", ("更多设置",), {}),
            ("settle_page", ("com.hihonor.dz.reader", "广告推荐服务"), {}),
            # 点这一行之前不翻页，关单走自绘开关的截图读数（`drawn`）。
            ("tap", ("广告推荐服务",), {"scrolls": 0}),
            ("close_named_honor", (["个性化广告"], "阅读·广告推荐服务",
                                   "com.hihonor.dz.reader", "广告推荐服务"), {"drawn": True}),
        ])

    def test_the_magazine_page_is_not_tapped_when_settings_search_already_landed_on_it(self):
        calls = self.record("tap", "close_named_honor")
        load_recipe(self.phone(focus="com.hihonor.magazine/.MainActivity"), self.RECIPE, ["魔法画报"])
        self.assertEqual([call[0] for call in calls], ["close_named_honor"])

    def test_the_magazine_entry_is_tapped_when_the_front_page_is_something_else(self):
        calls = self.record("tap", "close_named_honor")
        load_recipe(self.phone(focus="com.hihonor.magazine2/.MainActivity"), self.RECIPE, ["魔法画报"])
        self.assertEqual(calls, [
            ("tap", ("魔法画报",), {"scrolls": 0}),
            ("close_named_honor", (["锁屏壁纸轮播", "锁屏进入魔法画报", "数据流量自动更新"],
                                   "魔法画报", "com.hihonor.magazine", "魔法画报"), {}),
        ])


if __name__ == "__main__":
    unittest.main()
