"""#555: vivo 商店「个性化推荐」页的确认框进树要 0.6 秒左右，而 confirm() 只在 0.2 秒时
拍一次快照，从点击那一刻起就必然错过。等待必须是有界的轮询：晚到的弹窗照样认得出，
没有弹窗的页面也不能无限等。

设备无关：读屏走假时钟。前两条按 `fixtures.drive()` 的时间轴换页；后两条用 `StoreDevice`
记账——它会改开关状态、按需弹/关确认框、数被遮罩吞掉的点击，这样「点击有没有落在遮罩上」
才是可断言的。
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import fast
from fixtures import Clock, drive, fake_phone, install_clock

PAGE = ('<hierarchy rotation="0"><node package="com.vivo.appstore" bounds="[0,0][1260,2800]"/></hierarchy>')
DIALOG = ('<hierarchy rotation="0"><node package="com.vivo.appstore" bounds="[0,0][1260,2800]">'
          '<node class="android.widget.Button" content-desc="取消" clickable="true" bounds="[308,2333][951,2474]"/>'
          '<node class="android.widget.Button" content-desc="确认关闭" clickable="true" bounds="[308,2524][951,2665]"/>'
          '</node></hierarchy>')


class LateDialogTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, fast, "time", fast.time)      # 假时钟装进模块后要还原，别影响后面的用例

    def test_dialog_that_arrives_late_is_still_confirmed(self):
        """0.6 秒才进树的弹窗仍要被认出来，且只点一次「确认关闭」。"""
        out, _, _, clicks = drive(lambda p: p.confirm(), modules=(fast,),
                                  size=(1260, 2800), stages=[(0.0, PAGE), (0.6, DIALOG)], read_cost=0.1)
        self.assertEqual(out, "确认关闭")
        self.assertEqual(clicks, 1)

    def test_page_without_dialog_does_not_wait_forever(self):
        """整屏没有确认框：返回 None、一次也不点，花费有上界。"""
        out, elapsed, _, clicks = drive(lambda p: p.confirm(), modules=(fast,), size=(1260, 2800), read_cost=0.1)
        self.assertIsNone(out)
        self.assertEqual(clicks, 0)
        self.assertLessEqual(elapsed, 1.5)


TITLES = ("个性化推荐", "个性化广告推荐", "推荐内容", "热点推荐", "应用推荐",
          "内容推荐", "搜索推荐", "榜单推荐", "视频推荐", "商品推荐")
TOPS = tuple(250 + 250 * i for i in range(len(TITLES)))
SWITCH_X = 1054
CONFIRM_XY = (629, 2594)


def store_page(states, dialog):
    rows = "".join(
        f'<node bounds="[40,{top}][1100,{top + 142}]">'
        f'<node text="{title}" bounds="[40,{top}][700,{top + 142}]"/>'
        f'<node class="android.widget.Switch" checkable="true"'
        f' checked="{"true" if on else "false"}" bounds="[984,{top}][1125,{top + 142}]"/></node>'
        for title, top, on in zip(TITLES, TOPS, states))
    overlay = ('<node class="android.widget.Button" content-desc="取消" clickable="true" bounds="[308,2333][951,2474]"/>'
               '<node class="android.widget.Button" content-desc="确认关闭" clickable="true" bounds="[308,2524][951,2665]"/>'
               ) if dialog else ""
    return (f'<hierarchy rotation="0"><node package="com.vivo.appstore" bounds="[0,0][1260,2800]">'
            f'{rows}{overlay}</node></hierarchy>')


class StoreDevice:
    """vivo 商店的这一页：第一次往「关」拨之后 delay 秒弹确认框，弹窗挂着时页面上的点击被遮罩吞掉，
    只有点「确认关闭」能让它消失。"""

    def __init__(self, clock, delay):
        self.clock, self.delay = clock, delay
        self.states = [True] * len(TITLES)
        self.dialog_at, self.dialog, self.swallowed = None, False, 0
        self.lost_streak = self.max_lost_streak = 0        # 连续被吞的次数：一次竞态可以，一路吞不行

    def dump_hierarchy(self):
        self.clock.read()
        if self.dialog_at is not None and not self.dialog and self.clock.t >= self.dialog_at:
            self.dialog = True
        return store_page(self.states, self.dialog)

    def window_size(self):
        return (1260, 2800)

    def shell(self, command, timeout=60):
        return SimpleNamespace(output="", exit_code=0)

    def screenshot(self):
        return None

    def click(self, x, y):
        self.clock.click()
        if self.dialog:
            if (x, y) == CONFIRM_XY:
                self.dialog, self.dialog_at = False, None      # 关掉之后下一次拨动才会再弹
            else:
                self.swallowed += 1
                self.lost_streak += 1
                self.max_lost_streak = max(self.max_lost_streak, self.lost_streak)
            return
        self.lost_streak = 0
        for i, top in enumerate(TOPS):
            if (x, y) == (SWITCH_X, top + 71) and self.states[i]:
                self.states[i] = False
                if self.dialog_at is None:
                    self.dialog_at = self.clock.t + self.delay
                return


class MaskClickTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, fast, "time", fast.time)

    def run_off(self, delay):
        clock = Clock(read_cost=0.1)
        install_clock(fast, clock)
        device = StoreDevice(clock, delay)
        phone = fake_phone(clock=clock, size=(1260, 2800), click=device.click, d=device)
        return phone.off(), device

    def test_late_dialog_never_swallows_the_remaining_clicks(self):
        """报告者的场景：首击 0.6 秒后才弹的确认框。剩下的目标不能在弹窗挂着时去点。"""
        done, device = self.run_off(delay=0.6)
        self.assertEqual(device.swallowed, 0, "有目标被点在弹窗遮罩上了")
        self.assertEqual(done, len(TITLES))

    def test_dialog_slower_than_the_wait_budget_does_not_eat_later_clicks(self):
        """弹窗晚于 confirm() 的等待预算（慢机型）：连点前也要先看清屏上有没有确认框。

        读屏与点击之间仍有空隙，单次竞态漏掉一下是允许的；但不能一路吞下去。"""
        done, device = self.run_off(delay=1.2)
        self.assertLessEqual(device.max_lost_streak, 1, "连点被弹窗连续吞掉")
        self.assertEqual(done, len(TITLES))


if __name__ == "__main__":
    unittest.main()
