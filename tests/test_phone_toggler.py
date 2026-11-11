"""拨动会话搬出 `Phone` 之后的三条对外契约（ADR-0033、#1040）。

钉的是「结构变了、行为没变」里最容易被搬漏吃掉的那几条：
  · 门面继续转发 `off()` / `confirm()`，`safe_mode` 与 `changed` 仍是可写的活对象；
  · 残留提示的句子是 `row.residual_note()` 的纯函数，不读屏、不点击；
  · 导航侧的失败说明不再经过拨动会话——把 `toggler` 换成一个碰了就炸的替身，`tap()` 照样说得出来。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
import row  # noqa: E402
from fixtures import Clock, fake_phone, install_clock, phone_stub  # noqa: E402

SIZE = (1260, 2800)
CONFIRM_ONLY = ('<node class="android.widget.Button" content-desc="确认关闭" clickable="true" '
                'bounds="[308,2524][951,2665]"/>')


def page(dialog=False):
    return ('<hierarchy rotation="0"><node package="com.vivo.appstore" bounds="[0,0][1260,2800]">'
            + (CONFIRM_ONLY if dialog else "") + "</node></hierarchy>")


class _NoToggler:
    """碰一下就炸的拨动会话：导航侧的失败说明不该走到它。"""

    def __getattr__(self, name):
        raise AssertionError(f"导航侧访问了拨动会话的 {name}")


class FacadeForwardingTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_stub(W=1080, H=2340)

    def test_the_toggling_state_lives_on_the_session(self):
        """`p.safe_mode` 与 `p.changed` 转发到拨动会话本体：脚本照旧可写，集合仍是活对象。"""
        self.assertIs(self.p.changed, self.p.toggler.changed)
        self.assertIs(self.p.safe_mode, self.p.toggler.safe_mode)
        self.p.safe_mode = True
        self.assertIs(self.p.toggler.safe_mode, True)
        self.p.changed.append(("页", "开关"))
        self.assertEqual(self.p.toggler.changed, [("页", "开关")])

    def test_off_and_confirm_go_through_the_session(self):
        """门面没有实现残留：把会话换成替身，返回值必须由替身给出。"""
        self.p.toggler = Mock()
        self.p.toggler.off.return_value = 7
        self.p.toggler.confirm.return_value = "确定"
        self.assertEqual(self.p.off(page="页", only=["广告"]), 7)
        self.assertEqual(self.p.confirm(), "确定")
        self.p.toggler.off.assert_called_once_with((), ["广告"], "页", 40)

    def test_no_reflective_forwarding_on_the_toggler_side_either(self):
        """`__getattr__` 会把搬漏静默吃掉：门面与会话都不许有。"""
        self.assertNotIn("__getattr__", vars(type(self.p.toggler)))


class ResidualNoteTests(unittest.TestCase):
    def test_the_sentence_is_a_pure_function(self):
        self.assertEqual(row.residual_note("确认关闭", "；"), "；屏上还挂着没点掉的确认框「确认关闭」")
        self.assertEqual(row.residual_note(""), "")
        self.assertEqual(row.residual_note(None), "")

    def test_the_facade_reads_it_from_the_screen(self):
        """门面那句仍是读屏后拼出来的：有确认框时点名按钮，没有时是空串（#557）。"""
        p = fake_phone(clock=install_clock(fast, Clock()), size=SIZE,
                       stages=[(0.0, page(dialog=True))])
        self.assertEqual(p.residual_note(), "——屏上还挂着没点掉的确认框「确认关闭」")
        self.assertEqual(p.residual_note("；"), "；屏上还挂着没点掉的确认框「确认关闭」")


class NavigationDoesNotDependOnTogglingTests(unittest.TestCase):
    def test_tap_failure_names_the_dialog_without_the_toggler(self):
        """导航与拨动之间的那条环边：`tap()` 的失败说明只问观测基座，不问拨动会话。"""
        lines = []
        clock = install_clock(fast, Clock())
        p = fake_phone(clock=clock, size=SIZE, stages=[(0.0, page(dialog=True))],
                       say=lambda *a: lines.append(" ".join(str(x) for x in a)))
        p.toggler = _NoToggler()
        self.assertFalse(p.tap("服务管理", scrolls=0))
        self.assertEqual(lines[-1], "  ✗ 没找到「服务管理」——屏上还挂着没点掉的确认框「确认关闭」")


if __name__ == "__main__":
    unittest.main()
