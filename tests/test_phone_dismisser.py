"""弹窗与推广位搬出 `Phone` 之后的对外契约（ADR-0033、#1043）。

钉三件事：
  · 门面继续转发 `dismiss()` / `_promoted_click()`——返回值由阶段给；
  · 这个阶段只造自己就能验：给一个假 `Screen` 与启动会话就能判「关不关得掉」与「是不是推广位」，
    不必造整台 `Phone`（搬迁声称的测试面下沉，不是实现细节）；
  · 弹窗的判据只有一份：词表归这一个模块，确认框那份仍只在观测基座（拨动点掉遮罩与导航报原因共用它）。
"""
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from phone import dismisser  # noqa: E402
from fixtures import (SIZES, Clock, clocked, fake_phone, load_recipe, phone_mock,  # noqa: E402
                      phone_stub, screen_stub, stub)

# ---------- 基线：3e7d47f 的旧实现，逐字冻结 ----------
# 词表搬进新模块时抄错或漏一个词，`fast.DISMISS is dismisser.DISMISS` 这种断言照样绿：
# 两边是同一个对象。所以期望值按基线逐字冻在这里，再断言实现的元组等于它。
BASE_DISMISS = ("以后再说", "暂不更新", "暂不", "取消", "我知道了", "跳过", "禁止", "不再提示", "不同意")
BASE_UPDATE_TITLE = r"检测到新版本|发现新版本|版本更新提示"
BASE_CLOSE = r"close|关闭|跳过|skip|cancel|dismiss|iv_x\b|btn_x\b"
BASE_BACK_LABELS = {"返回", "back"}

# 纯图标的广告弹窗：desc 读作「关闭」，页面上没有开关、也没有可滚动列表
CLOSE_POPUP = '''<hierarchy rotation="0">
  <node package="com.some.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="推荐内容" bounds="[140,660][900,720]"/>
    <node class="android.widget.ImageView" content-desc="关闭" clickable="true"
          resource-id="com.some.app:id/iv_close" bounds="[900,600][990,690]"/>
  </node>
</hierarchy>'''

# 浮层自己的返回键：desc 精确读作「返回」，id 里带 cancel（沿用 #753）
BACK_MENU = '''<hierarchy rotation="0">
  <node package="com.vivo.browser" bounds="[0,0][1080,2340]">
    <node class="android.widget.ImageView" content-desc="返回" clickable="true"
          resource-id="com.vivo.browser:id/iv_back_cancel" bounds="[40,120][140,220]"/>
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[100,700][900,800]"/>
  </node>
</hierarchy>'''

PERMISSION_PAGE = '''<hierarchy rotation="0">
  <node package="com.android.permissioncontroller" bounds="[0,0][1080,2340]">
    <node package="com.android.permissioncontroller" class="android.widget.Button" text="允许" bounds="[100,1800][500,1940]"/>
    <node package="com.android.permissioncontroller" class="android.widget.Button" text="拒绝" bounds="[580,1800][980,1940]"/>
  </node>
</hierarchy>'''

SETTINGS = "com.android.settings/.Settings"

# 浮层里的 ✕（不在滚动列表里，dismiss 会点它），列表里是正常内容
POPUP = '''<hierarchy><node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,0][1272,2772]">
  <node text="首页" bounds="[100,300][600,400]"/></node>
  <node class="android.widget.FrameLayout" bounds="[100,600][1172,2000]">
    <node content-desc="关闭" clickable="true" bounds="[1050,620][1150,720]"/></node></hierarchy>'''


def bare_dismisser(page, focus=SETTINGS, session=None, size=SIZES[0]):
    """只造弹窗阶段：观测替身取 `fixtures.screen_stub()`，没有 `Phone`。点击与返回只记账。"""
    screen = screen_stub(page, size=size)
    screen.focus = focus if callable(focus) else (lambda: focus)
    screen.say = lambda *a: None
    clicks, backs = [], []
    screen.click = lambda x, y: clicks.append((x, y))
    screen.back = lambda n=1: backs.append(n)
    return fast.Dismisser(screen, session or fast.LaunchSession()), clicks, backs


class FacadeForwardingTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_stub(W=1080, H=2340)

    def test_the_phase_methods_go_through_the_stage(self):
        """门面没有实现残留：把阶段换成替身，返回值必须由替身给出。"""
        self.p.dismisser = Mock()
        self.p.dismisser.dismiss.return_value = "取消"
        self.p.dismisser.promoted_click.return_value = True
        self.assertEqual(self.p.dismiss(), "取消")
        self.assertTrue(self.p._promoted_click(10, 20, "关闭 iv_close"))
        self.p.dismisser.dismiss.assert_called_once_with()
        self.p.dismisser.promoted_click.assert_called_once_with(10, 20, "关闭 iv_close")


class StandalonePhaseTests(unittest.TestCase):
    def setUp(self):
        # 弹窗收场要等界面过渡（0.4~0.6 秒）：假钟一装，这些等待不占真实时间。
        self.clock = clocked(self, fast, Clock())

    def test_a_close_icon_popup_is_dismissed_without_a_phone(self):
        stage, clicks, _ = bare_dismisser(CLOSE_POPUP)
        self.assertEqual(stage.dismiss(), "✕")
        self.assertEqual(clicks, [(945, 645)])

    def test_a_permission_page_only_takes_the_explicit_deny_button(self):
        stage, clicks, _ = bare_dismisser(
            PERMISSION_PAGE, focus="com.android.permissioncontroller/.GrantPermissionsActivity")
        self.assertEqual(stage.dismiss(), "拒绝权限")
        self.assertEqual(clicks, [(780, 1870)])

    def test_the_back_button_of_a_menu_is_not_a_popup_close(self):
        """沿用 #753：菜单的返回键 id 里带 cancel，点一下就把刚打开的浮层收起来。"""
        stage, clicks, _ = bare_dismisser(BACK_MENU, focus="com.vivo.browser/.BrowserActivity")
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_a_promoted_close_falls_back_and_reads_the_launch_session(self):
        """推广位：点完前台换成商店 → 退回原 App 并记下这一处，这一次不算关掉了弹窗。"""
        session = fast.LaunchSession()
        session.app = "com.promo"
        focus = Mock(side_effect=["com.promo/Main", "com.shop/Promo", "com.promo/Main"])
        stage, clicks, backs = bare_dismisser(CLOSE_POPUP, focus=focus, session=session)
        self.assertTrue(stage.promoted_click(10, 20, "关闭 com.promo:id/iv_close"))
        self.assertEqual(session.promoted, {("com.promo", "关闭 com.promo:id/iv_close")})
        self.assertEqual(len(clicks), 1)
        self.assertEqual(backs, [1])


class SingleWordListTests(unittest.TestCase):
    def test_the_word_lists_match_the_frozen_baseline(self):
        """逐字对上搬走那一刻的词表：删词、抄错都会红，不只是「同一个对象」。"""
        self.assertEqual(dismisser.DISMISS, BASE_DISMISS)
        self.assertEqual(dismisser.UPDATE_TITLE.pattern, BASE_UPDATE_TITLE)
        self.assertEqual(dismisser.Dismisser.CLOSE.pattern, BASE_CLOSE)
        self.assertEqual(dismisser.Dismisser.CLOSE.flags & re.I, re.I)
        self.assertEqual(dismisser.Dismisser.BACK_LABELS, BASE_BACK_LABELS)

    def test_the_dismissal_word_lists_live_only_in_this_module(self):
        """词表只有在弹窗阶段有一份：门面上的常量是同一个对象，基座与拨动上不许再出现一份。"""
        self.assertIs(fast.DISMISS, dismisser.DISMISS)
        self.assertIs(fast.UPDATE_TITLE, dismisser.UPDATE_TITLE)
        self.assertIs(fast.Phone.CLOSE, dismisser.Dismisser.CLOSE)
        self.assertIs(fast.Phone.BACK_LABELS, dismisser.Dismisser.BACK_LABELS)
        for owner in (fast.Phone, fast.Screen, fast.Toggler):
            self.assertFalse(hasattr(owner, "DISMISS"), f"{owner.__name__} 上又出现了一份关闭词表")

    def test_the_mask_check_stays_on_the_base(self):
        """拨动里「先点掉遮罩再继续」用的是 `Screen.confirm_target()`（沿用 #555、#557）：
        弹窗阶段不许另认一份确认框。"""
        self.assertTrue(hasattr(fast.Screen, "confirm_target"))
        self.assertFalse(hasattr(dismisser.Dismisser, "confirm_target"))


class PromotedClickTests(unittest.TestCase):
    """#420：`dismiss()` 的 ✕ 分支点完跳到了别的 App 就退回来，这一次不算关掉了弹窗。"""

    def phone(self, focus, app="com.heytap.market"):
        p = phone_stub("test", reader=Mock())
        p.W, p.H = 1272, 2772
        p.screen.tree = Mock(return_value=ET.fromstring(POPUP))
        p.screen.focus = Mock(side_effect=list(focus))
        self.click, self.back, self.say = Mock(), Mock(), Mock()
        stub(p, "click", self.click)
        stub(p, "back", self.back)
        stub(p, "say", self.say)
        p.app = app
        return p

    def test_close_icon_that_leads_to_another_app_is_undone(self):
        """#420 点完跳到快手开屏：退回来并说明「疑似推广位」，这次不算关掉了弹窗。"""
        p = self.phone(["com.heytap.market/.Main", "com.kuaishou.nebula/.Splash",
                        "com.heytap.market/.Main"])
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())            # 不算关掉了弹窗
        self.back.assert_called_once()
        self.click.assert_called_once_with(1100, 670)
        said = " ".join(" ".join(map(str, c.args)) for c in self.say.call_args_list)
        self.assertIn("疑似推广位", said)
        self.assertIn("com.kuaishou.nebula", said)

    def test_promoted_close_icon_is_not_clicked_again(self):
        """#420 同一个 App 的同一处只点一次：退回来以后不再接着点它。"""
        p = self.phone(["com.heytap.market/.Main", "com.kuaishou.nebula/.Splash",
                        "com.heytap.market/.Main"] * 2)
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
            self.assertIsNone(p.dismiss())
        self.assertEqual(self.click.call_count, 1)

    def test_the_same_close_label_in_another_app_is_still_clicked(self):
        """#420「关闭」是常见标签：在别的 App 里不能因为这一处点过就跳过。"""
        p = self.phone(["com.heytap.market/.Main", "com.kuaishou.nebula/.Splash",
                        "com.heytap.market/.Main"])
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
        p.screen.focus = Mock(return_value="com.heytap.themestore/.Main")
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        self.assertEqual(self.click.call_count, 2)

    def test_close_icon_without_leaving_the_app_keeps_the_output(self):
        """#420 前台没变：返回值、点击坐标与日志逐字不变。"""
        p = self.phone(["com.heytap.market/.Main"] * 2)
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        self.click.assert_called_once_with(1100, 670)
        self.back.assert_not_called()
        self.assertEqual([c.args[0] for c in self.say.call_args_list], ["  · 弹窗点了 ✕（关闭）"])

    def test_unreadable_foreground_after_click_is_not_a_promotion(self):
        """#420 点击后读不到前台：不知道去了哪，不当作推广位，也不回退。"""
        p = self.phone(["com.heytap.market/.Main", ""])
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        self.back.assert_not_called()

    def test_close_icon_of_a_foreign_overlay_is_not_a_promotion(self):
        """#420 点前前台是抢焦点的广告浮层、点后回到目标 App：这是正常关弹窗。"""
        p = self.phone(["com.miui.systemAdSolution/.Ad", "com.example.target/.Main"],
                       app="com.example.target")
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        self.back.assert_not_called()

    def test_return_that_cannot_get_back_stops_the_step(self):
        """#420 两次返回仍在别的 App：停下，不继续在陌生页面上操作。"""
        p = self.phone(["com.heytap.market/.Main", "com.kuaishou.nebula/.Splash",
                        "com.kuaishou.nebula/.Main", "com.kuaishou.nebula/.Main"])
        with patch.object(fast.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "仍停在"):
                p.dismiss()
        self.assertEqual(self.back.call_count, 2)


# ---------- #753：vivo 浏览器菜单的返回键不是弹窗 ✕ ----------
# 报告者借 recipes/vivo-V2547DA 跑 V2217A，日志是「弹窗点了 ✕（返回 com.vivo.browser:id/iv_back_cancel）」
# 接着「设置」没找到；同一个节点手工 p.tap("设置", exact=True) 一次就进去了。两处判据：
#
# - dismiss() 把 content-desc + resource-id 丢进 CLOSE 正则，裸词 cancel 命中了菜单自己的返回键
#   （desc 读作「返回」），点一下就把刚打开的菜单收起来；
# - 脚本靠 tap(scrolls=0) 的等待循环找菜单项，而这个循环本身就在调 dismiss()。
#
# 四个同形脚本（V2547DA、Android 17 变体、V2309A、V2303A）的浏览器段入口一起改。
BROWSER_RECIPES = [ROOT / "recipes/vivo/V2547DA/V2547DA.toml",
                   ROOT / "recipes/vivo/V2547DA/V2547DA-android17.toml",
                   ROOT / "recipes/vivo/V2309A/V2309A.toml",
                   ROOT / "recipes/vivo/V2303A/V2303A.toml"]

# vivo 浏览器右上菜单弹层：右上角是浮层自己的返回键（desc「返回」，id 里带 cancel），
# 下面才是「设置」那一行。
MENU_PAGE = '''<hierarchy>
  <node package="com.vivo.browser" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="返回" clickable="true"
          resource-id="com.vivo.browser:id/iv_back_cancel" bounds="[40,120][140,220]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[100,700][900,800]" />
  </node>
</hierarchy>'''

# 真正的弹窗 ✕：纯图标、desc 读作「关闭」，页面上没有开关也没有可滚动列表
POPUP_PAGE = '''<hierarchy>
  <node package="com.vivo.browser" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.LinearLayout" bounds="[100,600][980,1400]">
      <node class="android.widget.TextView" text="发现新版本" bounds="[140,660][900,720]" />
      <node class="android.widget.ImageView" content-desc="关闭" clickable="true"
            resource-id="com.vivo.browser:id/iv_close" bounds="[900,600][990,690]" />
    </node>
  </node>
</hierarchy>'''

BROWSER_SETTINGS = "com.vivo.browser/com.vivo.browser.setting.SettingActivity"


def dismiss_phone(page, focus="com.vivo.browser/com.vivo.browser.BrowserActivity"):
    p = phone_stub("test", reader=Mock(), W=1080, H=2400)
    p.screen.tree = Mock(return_value=ET.fromstring(page))
    p.screen.focus = Mock(return_value=focus)
    p.app = "com.vivo.browser"
    p.click = p.screen.click = Mock()
    return p


class DismissBackButtonTests(unittest.TestCase):
    """#753：菜单的返回键 id 里有 cancel，不能被当成弹窗 ✕。"""

    def test_menu_back_button_is_not_treated_as_a_popup_close(self):
        """点了会把刚打开的浮层关掉，入口再也找不到。"""
        p = dismiss_phone(MENU_PAGE)
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
        p.click.assert_not_called()

    def test_a_real_popup_close_is_still_clicked(self):
        """旧树也绿，守的是不回退：desc 读作「关闭」的浮层 ✕ 照旧要关掉。"""
        p = dismiss_phone(POPUP_PAGE)
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        p.click.assert_called_once_with(945, 645)

    def test_an_english_or_padded_back_label_is_skipped_too(self):
        """真机 dump 的 desc 可能带首尾空白、也可能是英文界面：按同一判据排掉。"""
        p = dismiss_phone(MENU_PAGE.replace('content-desc="返回"', 'content-desc=" Back "'))
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
        p.click.assert_not_called()


def menu_phone(**fields):
    p = phone_mock(W=1080, H=2400, **fields)
    p.locked.return_value = False
    p.start.return_value = None
    p.back.return_value = None
    p.click.return_value = None
    p.screen.sig.return_value = "sig"
    p.await_page.return_value = True
    p.screen.settle.return_value = True
    p.in_settings_page.return_value = True
    p.find.return_value = (540, 750)
    p.entry.return_value = False
    p.off.return_value = None
    p.top.return_value = None
    p.screen.focus.return_value = BROWSER_SETTINGS
    p.tap_id_if_present.return_value = True
    return p


def run_browser(p, path):
    scope, out = load_recipe(p, path, only=["浏览器"])
    return scope, out.getvalue()


class VivoBrowserMenuTests(unittest.TestCase):
    """#753：入口改成只等那一行画出来再点，不经过会关弹窗的 tap()。"""

    def test_menu_row_is_clicked_without_dismissing_the_menu(self):
        for path in BROWSER_RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                scope, _ = run_browser(p, path)
                self.assertEqual(scope["FAILED_STEPS"], [])
                p.tap_id_if_present.assert_any_call("com.vivo.browser:id/menu_btn", timeout=3)
                p.click.assert_called_once_with(540, 750)
                self.assertNotIn("设置", [c.args[0] for c in p.tap.call_args_list if c.args])
                self.assertEqual(["首页设置", "网页浏览设置", "更多设置", "隐私权限设置"],
                                 [c.args[0] for c in p.entry.call_args_list])

    def test_reopens_the_menu_once_when_the_first_click_lands_elsewhere(self):
        """第一轮点完没进设置页：退回收起浮层、重开菜单再试一次。"""
        for path in BROWSER_RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                p.in_settings_page.side_effect = [False, True]
                scope, _ = run_browser(p, path)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual(2, p.tap_id_if_present.call_count)
                self.assertIn(call(), p.back.call_args_list)     # 退回收起浮层，重开菜单
                self.assertIn("首页设置", [c.args[0] for c in p.entry.call_args_list])

    def test_skips_the_section_when_the_browser_has_no_menu_button(self):
        """别的型号没有这个按钮（最多等 3 秒）：算本机没有这个入口，打印一句后跳过本段。"""
        for path in BROWSER_RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                p.tap_id_if_present.return_value = False
                scope, out = run_browser(p, path)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertIn("没有右上菜单按钮", out)
                p.back.assert_not_called()
                p.click.assert_not_called()

    def test_a_menu_without_the_settings_row_fails_the_step_loudly(self):
        """菜单开了却两轮都认不出设置页：必需入口没打开，记进 FAILED_STEPS，不再静默算成功。"""
        for path in BROWSER_RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                p.find.return_value = None
                scope, out = run_browser(p, path)
                self.assertEqual(["浏览器"], scope["FAILED_STEPS"])
                self.assertIn("浏览器设置页没有打开", out)
                p.entry.assert_not_called()
                self.assertEqual(2, p.tap_id_if_present.call_count)


BOTTOM_MENU_PAGE = '''<hierarchy>
  <node package="com.vivo.browser" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="返回" clickable="true"
          resource-id="com.vivo.browser:id/iv_back_cancel" bounds="[40,120][140,220]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[100,2250][900,2320]" />
  </node>
</hierarchy>'''


class _MenuButton:
    """p.conn.reader 的门面：既能按 uiautomator2 的选择器调用（找右上角按钮），又照旧当读屏 adapter 用。"""

    def __init__(self, device):
        self._device = device

    def __call__(self, **selectors):
        return self

    def click_exists(self, timeout=3):
        return True

    def __getattr__(self, name):
        return getattr(self._device, name)


class VivoBrowserRealPageTests(unittest.TestCase):
    """走真 find() 与真 clicks：把「设置」那一行放到底部 8% 带里，验证等待用的是带 edge_ok 的查找。"""

    def test_a_row_at_the_bottom_of_the_sheet_is_clicked(self):
        for path in BROWSER_RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                clock = Clock()
                clocked(self, fast, clock)
                clicks = []
                p = fake_phone(clock=clock, size=(1080, 2400), stages=[(0.0, BOTTOM_MENU_PAGE)],
                               focus=((0.0, "com.vivo.browser/.BrowserActivity"),),
                               click=lambda x, y: clicks.append((x, y)))  # noqa: B023 - 每轮新建 clicks，点击同步发生
                p.start = lambda *a, **k: None
                p.await_page = lambda *a, **k: True
                p.screen.settle = lambda *a, **k: True
                p.in_settings_page = lambda: True
                p.back = lambda *a, **k: None
                p.top = lambda *a, **k: None
                p.entry = lambda *a, **k: False
                p.off = lambda *a, **k: None
                p.conn.reader = _MenuButton(p.conn.reader)
                scope, _ = run_browser(p, path)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual([(500, 2285)], clicks)      # 菜单那一行，不是上面那个「返回」✕


# ---------- #378：设置页里含「关闭」字样的说明行不是弹窗 ✕ ----------
# 小米 HyperOS 广告服务设置页：说明与开关同在一行，整行可点，content-desc 就是「关闭后…」那段话
AD_SERVICE_PAGE = '''<hierarchy>
  <node package="com.android.settings" class="android.widget.LinearLayout" bounds="[0,0][1272,2772]">
    <node text="个性化广告推荐" bounds="[60,300][900,380]"/>
    <node class="android.widget.LinearLayout" content-desc="关闭后，广告数量不会因此减少，但广告内容的相关性会降低" clickable="true" bounds="[1000,420][1212,560]">
      <node class="android.widget.Switch" checkable="true" checked="true" bounds="[1040,440][1180,540]"/>
    </node>
  </node>
</hierarchy>'''


def close_row_phone(page, focus):
    p = phone_stub("test", reader=Mock())
    p.W, p.H = 1272, 2772
    p.screen.focus = Mock(return_value=focus)
    p.screen.tree = Mock(return_value=ET.fromstring(page))
    p.click = p.screen.click = Mock()
    return p


class DismissCloseRowTests(unittest.TestCase):
    """#378：点一下那个「关闭」等于替用户拨一次开关。"""

    def test_switch_row_with_close_wording_is_not_clicked(self):
        p = close_row_phone(AD_SERVICE_PAGE, "com.android.settings/.Settings$AdServiceSettings")
        switch = p.tree().find(".//node[@class='android.widget.Switch']")
        # 点击会真的翻开关：没被挡下时 checked 会变，断言才有意义
        p.click = p.screen.click = Mock(side_effect=lambda x, y: switch.set(
            "checked", "false" if switch.get("checked") == "true" else "true"))
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
        p.click.assert_not_called()
        self.assertEqual(switch.get("checked"), "true")

    def test_checkable_candidate_itself_is_not_clicked(self):
        # 真机上 content-desc 直接挂在 Switch 上，候选节点自身就是开关
        p = close_row_phone('''<hierarchy>
          <node package="com.android.settings" class="android.widget.LinearLayout" bounds="[0,0][1272,2772]">
            <node text="个性化广告推荐" bounds="[60,700][700,750]"/>
            <node text="个性化广告服务会根据您的喜好进行精准匹配" bounds="[60,755][900,860]"/>
            <node class="android.widget.Switch" checkable="true" checked="true" clickable="true"
                  content-desc="关闭后，广告数量不会因此减少" bounds="[1000,760][1212,900]"/>
          </node>
        </hierarchy>''', "com.android.settings/.Settings$AdServiceSettings")
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
        p.click.assert_not_called()

    def test_overlay_close_on_switch_page_is_still_clicked(self):
        # ColorOS 17 隐私页：整屏有开关，但浮层的 ✕ 子树里没有开关，仍要关掉
        p = close_row_phone('''<hierarchy>
          <node package="com.oplus.securitypermission" class="android.widget.LinearLayout" bounds="[0,0][1272,2772]">
            <node text="隐私与安全" bounds="[60,200][900,280]"/>
            <node class="android.widget.Switch" checkable="true" checked="true" bounds="[1080,900][1190,980]"/>
            <node class="android.widget.FrameLayout" bounds="[150,1200][1120,1900]">
              <node content-desc="关闭" clickable="true" bounds="[1030,1230][1120,1320]"/>
            </node>
          </node>
        </hierarchy>''', "com.oplus.securitypermission/.privacy.PrivacySecuritySettingsDashboardActivity")
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        p.click.assert_called_once_with(1075, 1275)


# ---------- 变异判据（ADR-0043、#1539）：四条退化链各自的判据与边界 ----------
def popup(**attrs):
    """一个只带给定属性的弹窗 ✕ 节点（bounds 默认落在屏幕中部的小图标上）。"""
    attrs.setdefault("bounds", "[900,600][990,690]")
    body = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f'<node {body}/>'


def page(*nodes):
    return '<hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>"


class PermissionDismissTests(unittest.TestCase):
    """运行时权限页只点明确的拒绝键：词表、按钮类名、坐标与等待。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def permission_page(self, text, **attrs):
        attrs.setdefault("class", "android.widget.Button")
        attrs.setdefault("package", "com.android.permissioncontroller")
        attrs.setdefault("bounds", "[580,1800][980,1940]")
        attrs["text"] = text
        body = " ".join(f'{k}="{v}"' for k, v in attrs.items())
        return page(f'<node package="com.android.permissioncontroller" bounds="[0,0][1080,2340]">'
                    f"<node {body}/></node>")

    def test_every_deny_wording_takes_the_explicit_button(self):
        for word in ("拒绝", "不允许", "Deny", "Don't allow"):
            with self.subTest(word=word):
                self.clock.t = 0.0
                stage, clicks, _ = bare_dismisser(
                    self.permission_page(word),
                    focus="com.android.permissioncontroller/.GrantPermissionsActivity")
                stage.screen.say = Mock()
                self.assertEqual(stage.dismiss(), "拒绝权限")
                self.assertEqual(clicks, [(780, 1870)])
                self.assertTrue(all(isinstance(v, int) for v in clicks[0]))
                self.assertAlmostEqual(self.clock.t, 0.4)
                stage.screen.say.assert_called_once_with("  · 已拒绝运行时权限申请，未授予权限")

    def test_a_deny_node_without_a_button_class_is_not_clicked(self):
        """没有 class 属性的拒绝节点不是按钮：默认值不能把它当成 Button。"""
        body = page('<node package="com.android.permissioncontroller" bounds="[0,0][1080,2340]">'
                    '<node package="com.android.permissioncontroller" text="拒绝" '
                    'bounds="[580,1800][980,1940]"/></node>')
        stage, clicks, _ = bare_dismisser(
            body, focus="com.android.permissioncontroller/.GrantPermissionsActivity")
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_only_node_elements_count_as_permission_buttons(self):
        """带权限包名但不是 `<node>` 的元素不算按钮：判据认的是页面树里的控件。"""
        body = page('<node package="com.android.permissioncontroller" bounds="[0,0][1080,2340]"/>',
                    '<button package="com.android.permissioncontroller" class="android.widget.Button" '
                    'text="拒绝" bounds="[580,1800][980,1940]"/>')
        stage, clicks, _ = bare_dismisser(
            body, focus="com.android.permissioncontroller/.GrantPermissionsActivity")
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_a_frame_with_the_permission_package_does_not_make_a_permission_page(self):
        """权限包名出现在非控件元素上时不算权限页：走回普通弹窗词表。"""
        body = page('<node package="com.example" bounds="[0,0][1080,2340]">'
                    '<node text="取消" bounds="[580,1800][980,1940]"/></node>',
                    '<frame package="com.android.permissioncontroller"/>')
        stage, _, _ = bare_dismisser(
            body, focus="com.android.permissioncontroller/.GrantPermissionsActivity")
        self.assertEqual(stage.dismiss(), "取消")


class CloseIconCullTests(unittest.TestCase):
    """纯图标弹窗的 ✕：key 取自 desc+id、排除列表内的、排除开关行、按尺寸与屏内判。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_the_click_uses_the_desc_and_the_resource_id(self):
        stage, clicks, _ = bare_dismisser(
            page(popup(**{"package": "com.x", "resource-id": "com.x:id/iv_close",
                          "clickable": "true"})))
        stage.screen.say = Mock()
        self.assertEqual(stage.dismiss(), "✕")
        self.assertEqual(clicks, [(945, 645)])
        self.assertTrue(all(isinstance(v, int) for v in clicks[0]))
        stage.screen.say.assert_called_once_with("  · 弹窗点了 ✕（com.x:id/iv_close）")

    def test_a_close_id_beside_a_label_is_not_a_popup_close(self):
        """✕ 必须是纯图标：同一节点上还有文字就不是（`关闭` 二字可能是正文）。"""
        stage, clicks, _ = bare_dismisser(
            page(popup(**{"package": "com.x", "resource-id": "com.x:id/iv_close",
                          "text": "关闭", "clickable": "true"})))
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_the_systemui_package_is_left_alone(self):
        stage, clicks, _ = bare_dismisser(
            page(popup(**{"package": "com.android.systemui", "content-desc": "关闭",
                          "clickable": "true"})))
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_a_close_inside_a_scrollable_list_is_left_alone(self):
        """列表里卡片的 ✕ 点了会打开别的页面：从候选往上走到滚动容器就跳过。"""
        body = page('<node package="com.x" class="androidx.recyclerview.widget.RecyclerView" '
                    'scrollable="true" bounds="[0,0][1080,2340]">'
                    '<node class="android.widget.FrameLayout" bounds="[100,500][1000,800]">'
                    '<node content-desc="关闭" clickable="true" bounds="[900,600][990,690]"/></node></node>')
        stage, clicks, _ = bare_dismisser(body)
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_the_icon_size_bounds_are_strict(self):
        cases = [
            ("[100,100][101,200]", False),     # 宽度 1：太大/太小都不行，0 < w 成立
            ("[100,100][100,200]", True),      # 宽度 0：不可点
            ("[100,100][424,200]", True),      # 正好 30% 屏宽：不含
            ("[100,100][600,200]", True),      # 超过 30% 屏宽：不算图标
            ("[100,100][200,101]", False),
            ("[100,100][200,100]", True),
            ("[100,100][200,500]", True),      # 超过 12% 屏高
        ]
        for bounds, should_skip in cases:
            with self.subTest(bounds=bounds):
                stage, clicks, _ = bare_dismisser(
                    page(popup(**{"package": "com.x", "content-desc": "关闭",
                                  "clickable": "true", "bounds": bounds})))
                result = stage.dismiss()
                if should_skip:
                    self.assertIsNone(result)
                    self.assertEqual(clicks, [])
                else:
                    self.assertEqual(result, "✕")

    def test_the_height_limit_is_the_shared_constant(self):
        stage, clicks, _ = bare_dismisser(
            page(popup(**{"package": "com.x", "content-desc": "关闭", "clickable": "true",
                          "bounds": "[100,100][200,400]"})), size=(1000, 2500))
        self.assertIsNone(stage.dismiss())          # 高度正好 12% 屏高：不含
        self.assertEqual(clicks, [])

    def test_an_icon_outside_the_screen_is_skipped(self):
        stage, clicks, _ = bare_dismisser(
            page(popup(**{"package": "com.x", "content-desc": "关闭", "clickable": "true"})))
        stage.screen.on_screen = lambda n: False
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_a_non_node_close_mark_is_not_a_popup_close(self):
        stage, clicks, _ = bare_dismisser(
            page('<close package="com.x" content-desc="关闭" clickable="true" bounds="[900,600][990,690]"/>'))
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_the_log_truncates_a_long_key_at_forty_characters(self):
        stage, _, _ = bare_dismisser(
            page(popup(**{"package": "com.x", "content-desc": "关闭",
                          "resource-id": "com.x:id/" + "x" * 60, "clickable": "true"})))
        stage.screen.say = Mock()
        self.assertEqual(stage.dismiss(), "✕")
        key = "关闭 " + "com.x:id/" + "x" * 60
        stage.screen.say.assert_called_once_with(f"  · 弹窗点了 ✕（{key[:40]}）")


class DismissWordListTests(unittest.TestCase):
    """按文字认拒绝类按钮的那条链：词表、开关/列表守卫、文字行数的上界。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_a_refuse_word_is_clicked_and_waited_for(self):
        stage, clicks, _ = bare_dismisser(
            page('<node package="com.x" text="取消" bounds="[540,900][900,1000]"/>'))
        stage.screen.say = Mock()
        self.assertEqual(stage.dismiss(), "取消")
        self.assertEqual(clicks, [(720, 950)])
        self.assertTrue(all(isinstance(v, int) for v in clicks[0]))
        self.assertAlmostEqual(self.clock.t, 0.6)
        stage.screen.say.assert_called_once_with("  · 弹窗点了「取消」")

    def test_a_switch_row_with_close_wording_is_a_switch_not_a_popup(self):
        stage, clicks, _ = bare_dismisser(
            page('<node package="com.x" class="android.widget.Switch" checkable="true" '
                 'text="取消" bounds="[0,0][1080,2340]"/>'))
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_a_page_with_exactly_sixteen_texts_still_counts(self):
        rows = "".join(f'<node package="com.x" text="行{i}" bounds="[0,{100 + i * 40}][900,{130 + i * 40}]"/>'
                       for i in range(15))
        stage, clicks, _ = bare_dismisser(
            page(rows, '<node package="com.x" text="取消" bounds="[540,900][900,1000]"/>'))
        self.assertEqual(stage.dismiss(), "取消")
        self.assertEqual(clicks, [(720, 950)])

    def test_seventeen_texts_is_too_busy_to_be_a_popup(self):
        rows = "".join(f'<node package="com.x" text="行{i}" bounds="[0,{100 + i * 40}][900,{130 + i * 40}]"/>'
                       for i in range(16))
        stage, clicks, _ = bare_dismisser(
            page(rows, '<node package="com.x" text="取消" bounds="[540,900][900,1000]"/>'))
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_a_scrollable_page_is_not_a_popup_however_it_reads(self):
        """带滚动列表的页面不能只凭文字当弹窗关掉。"""
        stage, clicks, _ = bare_dismisser(
            page('<node package="com.x" class="android.widget.ScrollView" scrollable="true" '
                 'bounds="[0,0][1080,2340]"/>',
                 '<node package="com.x" text="取消" bounds="[540,900][900,1000]"/>'))
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])

    def test_only_node_elements_count_as_scrollable(self):
        stage, clicks, _ = bare_dismisser(
            page('<list scrollable="true" bounds="[0,0][1080,2340]"/>',
                 '<node package="com.x" text="取消" bounds="[540,900][900,1000]"/>'))
        self.assertEqual(stage.dismiss(), "取消")

    def test_the_texts_are_read_from_the_same_snapshot_as_the_candidates(self):
        """`refuse()` 用的是这一拍开始时的页面快照，不重新读一次树。"""
        first = ET.fromstring(page('<node package="com.x" text="首页" bounds="[0,100][900,200]"/>'))
        second = ET.fromstring(page('<node package="com.x" text="取消" bounds="[540,900][900,1000]"/>'))
        stage, clicks, _ = bare_dismisser(page())
        stage.screen.tree = Mock(side_effect=[first, second])
        self.assertIsNone(stage.dismiss())
        self.assertEqual(clicks, [])


class PromotedSessionTests(unittest.TestCase):
    """推广位的退回：等待时长、两次返回、key 的截断。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def promoted(self, focus, key="关闭 com.promo:id/iv_close"):
        session = fast.LaunchSession()
        session.app = "com.promo"
        stage, clicks, backs = bare_dismisser(
            CLOSE_POPUP, focus=Mock(side_effect=list(focus)), session=session)
        stage.screen.say = Mock()
        return stage, clicks, backs, key

    def test_the_click_and_the_return_each_wait_their_own_moment(self):
        stage, clicks, backs, key = self.promoted(
            ["com.promo/Main", "com.shop/Promo", "com.promo/Main"])
        self.assertTrue(stage.promoted_click(10, 20, key))
        self.assertAlmostEqual(self.clock.t, 1.0)      # 点击后 0.6 秒 + 退回后 0.4 秒

    def test_a_second_return_is_needed_when_the_first_one_lands_elsewhere(self):
        stage, clicks, backs, key = self.promoted(
            ["com.promo/Main", "com.shop/Promo", "com.shop/Main", "com.promo/Main"])
        self.assertTrue(stage.promoted_click(10, 20, key))
        self.assertEqual(len(backs), 2)
        self.assertAlmostEqual(self.clock.t, 1.4)      # 0.6 + 0.4 + 0.4

    def test_the_package_is_split_at_the_first_slash(self):
        stage, clicks, backs, key = self.promoted(
            ["com.promo/Main", "com.shop/Promo", "com.promo/Main"])
        self.assertTrue(stage.promoted_click(10, 20, key))

    def test_a_whitespace_padded_foreground_is_not_the_target_app(self):
        """焦点串没经过 strip：包名按第一个 / 之前的部分切，带前导空白的串对不上目标 App。"""
        stage, clicks, backs, key = self.promoted(
            [" com.promo/Main", "com.shop/Promo", " com.promo/Main"])
        self.assertFalse(stage.promoted_click(10, 20, key))
        self.assertEqual(backs, [])

    def test_the_log_truncates_the_key_at_forty_characters(self):
        key = "关闭 " + "com.promo:id/" + "x" * 60
        stage, clicks, backs, _ = self.promoted(
            ["com.promo/Main", "com.shop/Promo", "com.promo/Main"])
        self.assertTrue(stage.promoted_click(10, 20, key))
        stage.screen.say.assert_called_once_with(
            f"  · 点了 ✕ 后跳到 com.shop，疑似推广位，已退回（{key[:40]}）")


if __name__ == "__main__":
    unittest.main()
