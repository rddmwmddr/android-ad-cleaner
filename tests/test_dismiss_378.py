"""#378：设置页里含「关闭」字样的说明行被 dismiss() 当成弹窗 ✕ 点掉，等于替用户拨一次开关。"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import fast
from fixtures import phone_stub


def page(xml, focus):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1272, 2772
    p.focus = Mock(return_value=focus)
    p.tree = Mock(return_value=ET.fromstring(xml))
    p.click = Mock()
    return p


# 小米 HyperOS 广告服务设置页：说明与开关同在一行，整行可点，content-desc 就是「关闭后…」那段话
AD_SERVICE_PAGE = '''<hierarchy>
  <node package="com.android.settings" class="android.widget.LinearLayout" bounds="[0,0][1272,2772]">
    <node text="个性化广告推荐" bounds="[60,300][900,380]"/>
    <node class="android.widget.LinearLayout" content-desc="关闭后，广告数量不会因此减少，但广告内容的相关性会降低" clickable="true" bounds="[1000,420][1212,560]">
      <node class="android.widget.Switch" checkable="true" checked="true" bounds="[1040,440][1180,540]"/>
    </node>
  </node>
</hierarchy>'''


class DismissCloseRowTests(unittest.TestCase):
    def test_switch_row_with_close_wording_is_not_clicked(self):
        p = page(AD_SERVICE_PAGE, "com.android.settings/.Settings$AdServiceSettings")
        switch = p.tree().find(".//node[@class='android.widget.Switch']")
        # 点击会真的翻开关：没被挡下时 checked 会变，断言才有意义
        p.click = Mock(side_effect=lambda x, y: switch.set(
            "checked", "false" if switch.get("checked") == "true" else "true"))
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
        p.click.assert_not_called()
        self.assertEqual(switch.get("checked"), "true")

    def test_checkable_candidate_itself_is_not_clicked(self):
        # 真机上 content-desc 直接挂在 Switch 上，候选节点自身就是开关
        p = page('''<hierarchy>
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
        p = page('''<hierarchy>
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
