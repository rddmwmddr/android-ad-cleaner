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
        p = phone_stub("test", d=Mock())
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
    p = phone_stub("test", d=Mock(), W=1080, H=2400)
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
    p.d.return_value.click_exists.return_value = True
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
                p.d.assert_any_call(resourceId="com.vivo.browser:id/menu_btn")
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
                self.assertEqual(2, p.d.return_value.click_exists.call_count)
                self.assertIn(call(), p.back.call_args_list)     # 退回收起浮层，重开菜单
                self.assertIn("首页设置", [c.args[0] for c in p.entry.call_args_list])

    def test_skips_the_section_when_the_browser_has_no_menu_button(self):
        """别的型号没有这个按钮（最多等 3 秒）：算本机没有这个入口，打印一句后跳过本段。"""
        for path in BROWSER_RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                p.d.return_value.click_exists.return_value = False
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
                self.assertEqual(2, p.d.return_value.click_exists.call_count)


BOTTOM_MENU_PAGE = '''<hierarchy>
  <node package="com.vivo.browser" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="返回" clickable="true"
          resource-id="com.vivo.browser:id/iv_back_cancel" bounds="[40,120][140,220]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[100,2250][900,2320]" />
  </node>
</hierarchy>'''


class _MenuButton:
    """p.d 的门面：既能按 uiautomator2 的选择器调用（找右上角按钮），又照旧当读屏 adapter 用。"""

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
                p.d = _MenuButton(p.reader)
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
    p = phone_stub("test", d=Mock())
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


if __name__ == "__main__":
    unittest.main()
