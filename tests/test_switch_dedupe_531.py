"""#531: vivo's self-drawn switch stacks an untitled wrapper and the real switch on the same
bounds. The wrapper has no resource-id and no text, so collapsing duplicate nodes by
(resource-id, text, bounds) throws the checkable Switch away and the page reads as empty."""
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
from fixtures import phone_stub

PKG = "com.vivo.appstore"


def vivo_switch_row(title, top, checked):
    """One row of the vivo "personalized recommendation" page: title on the left, and on the
    right a four-node stack sharing the same bounds, the checkable Switch last."""
    bottom = top + 142
    box = f"[984,{top}][1125,{bottom}]"
    desc = "开启，开关" if checked else "关闭，开关"
    return (f'<node bounds="[40,{top}][1100,{bottom}]">'
            f'<node text="{title}" bounds="[40,{top}][700,{bottom}]"/>'
            f'<node class="android.widget.FrameLayout" resource-id="{PKG}:id/user_recommend_setting_bool_btn"'
            f' content-desc="{desc}" clickable="true" bounds="{box}">'
            f'<node class="android.widget.RelativeLayout" bounds="{box}"/>'
            f'<node class="android.widget.RelativeLayout" resource-id="{PKG}:id/move_switch_btn"'
            f' bounds="{box}"/>'
            f'<node class="android.widget.Switch" checkable="true"'
            f' checked="{"true" if checked else "false"}" bounds="{box}"/>'
            f'</node></node>')


def page(*rows):
    return (f'<hierarchy rotation="0"><node package="{PKG}" bounds="[0,0][1260,2800]">'
            + "".join(rows) + "</node></hierarchy>")


def phone(xml):
    p = phone_stub("test")
    p.W, p.H = 1260, 2800
    p.tree = lambda: ET.fromstring(xml)
    return p


class SelfDrawnSwitchTests(unittest.TestCase):
    def test_wrapper_without_identity_does_not_hide_the_real_switch(self):
        xml = page(vivo_switch_row("个性化推荐，关闭", 353, False),
                   vivo_switch_row("个性化广告推荐，关闭", 600, False))
        self.assertEqual([(t, c) for t, c, _ in phone(xml).switches()],
                         [("个性化推荐，关闭", False), ("个性化广告推荐，关闭", False)])


if __name__ == "__main__":
    unittest.main()
