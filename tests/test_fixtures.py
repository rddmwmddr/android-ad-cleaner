"""夹具本身的行为：样本能抽出来、假时钟会走、时间轴会换页、假 Phone 能跑真的等待。

夹具错了，靠它对拍出来的「一致」也就没有意义，所以这里断言的正是对拍依赖的那几件事。
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import fast
import fixtures

PAGE = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node text="营销通知" bounds="[60,350][600,400]"/>
  <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,350][1080,400]"/>
</node></hierarchy>'''


class SampleTests(unittest.TestCase):
    def test_samples_come_from_the_test_sources(self):
        pages = fixtures.all_pages()
        self.assertGreaterEqual(len(pages), 40)
        for label, xml in pages:
            self.assertTrue(xml.startswith("<hierarchy"), label)
            self.assertTrue(xml.endswith("</hierarchy>"), label)

    def test_page_that_does_not_parse_is_skipped(self):
        # 错误上报那批里有一份故意造的非良构 XML，抽出来会把对拍整体打断
        good = '<hierarchy><node text="x" bounds="[0,0][10,10]"/></hierarchy>'
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "test_x.py").write_text(
                f'BROKEN = "<hierarchy><node></hierarchy>"\nOK = {good!r}\n', encoding="utf-8")
            self.assertEqual([xml for _, xml in fixtures.all_pages(folder)], [good])


class ClockTests(unittest.TestCase):
    def test_sleep_advances_the_same_clock_until_reads(self):
        clock = fixtures.Clock()
        clock.sleep(0.25)
        clock.sleep(0.5)
        self.assertAlmostEqual(clock.time(), 0.75)
        self.assertAlmostEqual(clock.monotonic(), 0.75)

    def test_reading_the_screen_costs_time_and_is_counted(self):
        clock = fixtures.Clock(read_cost=0.5, click_cost=0.05)
        clock.read()
        clock.click()
        self.assertAlmostEqual(clock.time(), 0.55)
        self.assertEqual((clock.page_reads, clock.clicks), (1, 1))


class TimelineTests(unittest.TestCase):
    def test_page_switches_on_the_given_second(self):
        timeline = fixtures.Timeline([(0.0, "a"), (0.6, "b")])
        self.assertEqual(timeline.page_at(0.0), "a")
        self.assertEqual(timeline.page_at(0.59), "a")
        self.assertEqual(timeline.page_at(0.6), "b")

    def test_focus_axis_runs_independently_of_the_page_axis(self):
        timeline = fixtures.Timeline([(0.0, "a")], focus=[(0.0, "x/A"), (1.0, "x/B")])
        self.assertEqual((timeline.page_at(2.0), timeline.focus_at(2.0)), ("a", "x/B"))

    def test_needs_at_least_one_page(self):
        with self.assertRaises(ValueError):
            fixtures.Timeline([])


class FakePhoneTests(unittest.TestCase):
    def setUp(self):
        # 假时钟装在模块上，跑完必须换回真时钟，否则后面的测试全都停在假时间里
        self.addCleanup(setattr, fast, "time", fast.time)

    def test_settle_sees_the_new_page_without_waiting_out_the_budget(self):
        clock = fixtures.Clock()
        fixtures.install_clock(fast, clock)
        p = fixtures.fake_phone(clock=clock, stages=[(0.0, fixtures.EMPTY_PAGE), (0.2, PAGE)])
        self.assertTrue(p.settle(p.sig(), 1.0))
        self.assertLess(clock.time(), 1.0)
        self.assertGreater(clock.page_reads, 1)

    def test_size_comes_back_from_the_device(self):
        p = fixtures.fake_phone(size=(720, 1600))
        p.tree()
        self.assertEqual((p.W, p.H), (720, 1600))

    def test_click_advances_the_clock_instead_of_touching_a_phone(self):
        clock = fixtures.Clock()
        p = fixtures.fake_phone(clock=clock)
        p.click(100, 200)
        self.assertEqual(clock.clicks, 1)

    def test_fields_replace_the_defaults(self):
        p = fixtures.fake_phone(locked=lambda: True, vivo_seen=True)
        self.assertTrue(p.locked())
        self.assertTrue(p.vivo_seen)

    def test_drive_reports_result_and_cost(self):
        out, elapsed, reads, clicks = fixtures.drive(lambda p: bool(p.sig()), modules=[fast],
                                                     stages=[(0.0, PAGE)])
        self.assertTrue(out)
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertEqual((reads, clicks), (1, 0))


class PhoneStubTests(unittest.TestCase):
    """`phone_stub` 是「不连手机的 Phone」的唯一装配点，fake_phone 也建在它上面。"""

    def test_serial_and_lost_write_through_to_the_link(self):
        p = fixtures.phone_stub("S")
        self.assertEqual(p.serial, "S")
        p.lost = True
        self.assertTrue(p.link.lost)
        self.assertEqual(p.link.serial, "S")

    def test_the_default_shell_answers_empty(self):
        self.assertEqual(fixtures.phone_stub().link.shell("getprop x").output, "")


if __name__ == "__main__":
    unittest.main()
