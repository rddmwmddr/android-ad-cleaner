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
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from phone import dismisser  # noqa: E402
from fixtures import SIZES, Clock, clocked, phone_stub, screen_stub  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
