"""AOSP 渠道页的「显示通知」：可点的 main_switch_bar 里包着真开关。外层不能按颜色当自绘开关，
否则它猜出的状态盖过真开关（#403 之后），关着的渠道读成开着，还原营销通知报「界面状态与渠道实际状态不一致」。
页面结构取自 Android 15 模拟器的真实 dump（测试应用 dev.aac.regression 的渠道页），文字只留标签。"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fast
from fixtures import phone_stub

PAGE = '''<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.settings" bounds="[0,0][1344,2992]">
    <node resource-id="com.android.settings:id/entity_header_title" class="android.widget.TextView" text="Regression promo" bounds="[428,928][916,1009]"/>
    <node resource-id="com.android.settings:id/main_switch_bar" class="android.widget.LinearLayout" clickable="true" checkable="false" bounds="[0,1120][1344,1448]">
      <node resource-id="com.android.settings:id/switch_text" class="android.widget.TextView" text="显示通知" bounds="[132,1240][1008,1328]"/>
      <node resource-id="android:id/switch_widget" class="android.widget.Switch" checkable="true" checked="CHECKED" clickable="false" bounds="[1080,1212][1236,1356]"/>
    </node>
  </node>
</hierarchy>'''


class MainSwitchBarTests(unittest.TestCase):
    def phone(self, checked):
        p = phone_stub("fake")
        p.W, p.H = 1344, 2992
        p.reader = Mock()
        p.reader.screenshot.side_effect = AssertionError("有真开关时不该截图猜颜色")
        return p, ET.fromstring(PAGE.replace("CHECKED", checked))

    def test_real_switch_inside_the_bar_decides_the_state(self):
        for checked, on in (("false", False), ("true", True)):
            p, root = self.phone(checked)
            self.assertEqual(fast.Phone.switches(p, root), [("显示通知", on, (1158, 1284))])


if __name__ == "__main__":
    unittest.main()
