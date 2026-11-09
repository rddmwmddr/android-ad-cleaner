"""桌面引擎的离线用例：不连手机，用合成的界面树和假手机。"""
import json
import re
import unittest
import unittest.mock
from pathlib import Path

HARMONY = Path(__file__).resolve().parents[1] / "harmony"

from gui import harmony_engine as engine


def node(kind='Column', bounds='[0,0][1000,1000]', children=(), **attrs):
    data = {'type': kind, 'bounds': bounds, 'visible': 'true'}
    data.update(attrs)
    return {'attributes': data, 'children': list(children)}


def window(children, bundle='com.huawei.hmos.settings', bounds='[0,100][1000,2000]'):
    return {'attributes': {}, 'children': [
        node('root', bounds, children, bundleName=bundle),
        node('WindowScene', '[0,0][1000,100]', bundleName='com.ohos.sceneboard'),
    ]}


def text(value, bounds):
    return node('Text', bounds, text=value)


def toggle(checked, bounds):
    return node('Toggle', bounds, checkable='true', checked='true' if checked else 'false')


def page(children, bounds='[0,100][1000,2000]', key=''):
    return node('NavDestination', bounds, children, key=key)


class ScreenTest(unittest.TestCase):
    def test_covered_page_is_ignored(self):
        """被盖住的页面也报 visible=true，不能读到它。"""
        s = engine.Screen(window([page([text('下面', '[0,200][200,260]')]), page([text('上面', '[0,200][200,260]')])]))
        self.assertIsNotNone(s.find_text('上面'))
        self.assertIsNone(s.find_text('下面'))

    def test_split_panes_are_both_visible(self):
        """展开时左栏不是页面节点，也要读得到。"""
        left = node('List', '[0,100][400,2000]', [text('小艺', '[20,300][120,360]')])
        s = engine.Screen(window([left, page([text('详情', '[500,300][700,360]')], '[400,100][1000,2000]')]))
        self.assertIsNotNone(s.find_text('小艺'))
        self.assertIsNotNone(s.find_text('详情'))

    def test_floating_tab_bar_over_page_is_visible(self):
        """浮动底栏排在页面后面，虽然压在页面范围内也看得见。"""
        tabs = node('Tabs', '[0,100][1000,2000]', [
            page([text('内容', '[0,300][200,360]')]),
            text('我的', '[800,1900][900,1950]'),
        ])
        self.assertIsNotNone(engine.Screen(window([tabs])).find_text('我的'))

    def test_nested_pages_collect_each_node_once(self):
        """嵌套页面不能把节点收两遍，否则第 2 个单选项会认成第 1 个。"""
        radios = [node('Radio', '[100,300][150,350]', checkable='true', checked='true'),
                  node('Radio', '[600,300][650,350]', checkable='true', checked='false')]
        s = engine.Screen(window([page([page(radios)])]))
        self.assertEqual([r.rect.left for r in s.radios()], [100, 600])

    def test_switch_prefers_row_with_control_over_same_named_title(self):
        s = engine.Screen(window([page([
            text('个性化推荐', '[100,150][400,220]'),
            text('个性化推荐', '[60,700][400,760]'),
            toggle(True, '[850,700][950,760]'),
        ])]))
        controls = [s.switch_for(label) for label in s.find_all('个性化推荐')]
        self.assertIsNone(controls[0])
        self.assertEqual(controls[1].rect.left, 850)

    def test_row_level_switch_taps_inner_toggle(self):
        row = node('Row', '[40,600][960,760]', [text('应用活动', '[60,650][300,710]'), node('Toggle', '[850,650][950,710]')],
                   checkable='true', checked='true')
        s = engine.Screen(window([page([row])]))
        control = s.switch_for(s.find_text('应用活动'))
        self.assertEqual(s.tap_target(control).left, 850)

    def test_key_of_ignores_width_and_spaces(self):
        self.assertEqual(engine.key_of('USB 调试'), engine.key_of('USB调试'))
        self.assertEqual(engine.key_of('Ｗｉ\u200bＦｉ 连接'), 'WiFi连接')

    def test_consent_is_detected(self):
        s = engine.Screen(window([page([node('Button', '[0,300][100,360]', text='同意')])]))
        self.assertTrue(s.has_consent())

    def test_web_view_counts_as_scroll_area(self):
        """华为广告的网页不标 scrollable，内容要滚到附近才读得到。"""
        s = engine.Screen(window([page([node('Web', '[400,250][1000,2000]')])]))
        self.assertEqual([r.left for r in s.scroll_areas()], [400])

    def test_swipe_avoids_nested_list(self):
        """外屏主题卡片占满中间，要从旁边起手。"""
        outer = node('List', '[0,100][1000,2000]', [node('List', '[40,600][960,1800]', scrollable='true')], scrollable='true')
        s = engine.Screen(window([page([outer])]))
        area = s.scroll_areas()[0]
        self.assertEqual(s.swipe_column(area), 20)


class FakePhone(engine.Phone):
    """按脚本回放界面。点击和按键只记录，不碰真机。"""

    def __init__(self, screens):
        super().__init__('hdc', 'serial')
        self.screens = screens
        self.commands = []

    def shell(self, cmd, timeout=30):
        if self.should_stop() and not self.holding:
            raise engine.Stopped()
        self.commands.append(cmd)
        if 'dumpLayout' in cmd:
            current = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
            return current if isinstance(current, str) else json.dumps(current)
        return ''


SWITCH = {'title': '热搜榜', 'want': False, 'below': False, 'radio': -1, 'moot': ''}


def switch_page(checked, extra=()):
    return window([page([text('热搜榜', '[60,600][300,660]'), toggle(checked, '[850,600][950,660]'), *extra])])


class SetSwitchTest(unittest.TestCase):
    def setUp(self):
        patcher = unittest.mock.patch.object(engine.time, 'sleep', lambda _s: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_flip_and_read_back(self):
        phone = FakePhone([switch_page(True), switch_page(False)])
        self.assertEqual(phone.set_switch(SWITCH, False), ('changed', True))
        self.assertTrue(any('uiInput click 900 630' in c for c in phone.commands))

    def test_stop_waits_until_the_flip_is_read_back(self):
        """点了开关之后才按停止：要等回读确认，这次改动才记得下来。"""
        phone = FakePhone([switch_page(True), switch_page(False)])
        clicks = []
        orig = phone.shell

        def shell(cmd, timeout=30):
            out = orig(cmd, timeout)
            if 'uiInput click' in cmd:
                clicks.append(cmd)
            return out
        phone.shell = shell
        phone.should_stop = lambda: bool(clicks)
        self.assertEqual(phone.set_switch(SWITCH, False), ('changed', True))
        with self.assertRaises(engine.Stopped):
            phone.read()

    def test_already_in_state_does_not_tap(self):
        phone = FakePhone([switch_page(False)])
        self.assertEqual(phone.set_switch(SWITCH, False), ('already', False))
        self.assertFalse(any('click' in c for c in phone.commands))

    def test_confirm_button_in_web_page_is_tapped(self):
        confirm = text('确认停用', '[300,900][500,960]')
        phone = FakePhone([switch_page(True), switch_page(True, [confirm]), switch_page(False)])
        self.assertEqual(phone.set_switch(SWITCH, False), ('changed', True))
        self.assertTrue(any('uiInput click 400 930' in c for c in phone.commands))

    def test_consent_words_are_never_confirmed(self):
        agree = node('Button', '[300,900][500,960]', text='同意')
        phone = FakePhone([switch_page(True), switch_page(True, [agree])])
        self.assertEqual(phone.set_switch(SWITCH, False), ('failed', True))
        self.assertFalse(any('uiInput click 400 930' in c for c in phone.commands))

    def test_web_switch_waits_until_it_appears(self):
        """网页没加载完时只有文字没有开关，要等开关出来，不能直接报没找到。"""
        target = dict(SWITCH, title='个性化广告', below=True)
        web = node('Web', '[400,250][1000,2000]')
        not_yet = window([page([text('华为广告', '[60,150][300,200]')])])
        loading = window([page([web])])
        loaded = window([page([web, text('个性化广告', '[420,600][700,660]'),
                               node('switch', '[850,700][950,760]', checkable='true', checked='false')])])
        loaded_on = window([page([web, text('个性化广告', '[420,600][700,660]'),
                                  node('switch', '[850,700][950,760]', checkable='true', checked='true')])])
        phone = FakePhone([not_yet, loading, loading, loaded, loaded_on])
        self.assertEqual(phone.set_switch(target, True), ('changed', False))
        swipes = [c for c in phone.commands if 'swipe' in c]
        self.assertTrue(swipes and all(' 700 ' in c for c in swipes), swipes)

    def test_moot_when_notifications_are_off(self):
        target = dict(SWITCH, moot='通知已关闭')
        phone = FakePhone([switch_page(True, [text('通知已关闭', '[60,300][300,360]')])])
        self.assertEqual(phone.set_switch(target, False), ('moot', True))

    def test_lock_screen_raises(self):
        phone = FakePhone(['{"a":"MainPageView_Screen_Lock_Home"}'])
        with self.assertRaises(engine.ScreenLocked):
            phone.read()

    def test_garbage_output_means_device_lost(self):
        phone = FakePhone(['[Fail][E001005] Device not found or connected'])
        with self.assertRaises(engine.DeviceLost):
            phone.read()


class RunTest(unittest.TestCase):
    SEGMENTS = [
        {'id': 'a', 'name': '甲', 'kind': 'uri', 'value': 'x', 'ability': '', 'path': [],
         'pages': [{'path': [], 'targets': [SWITCH]}]},
        {'id': 'b', 'name': '乙', 'kind': 'app', 'value': 'com.demo', 'ability': 'Main', 'path': ['入口'],
         'pages': [{'path': [], 'targets': [dict(SWITCH, title='资讯')]}]},
    ]

    def setUp(self):
        patcher = unittest.mock.patch.object(engine.time, 'sleep', lambda _s: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events = []

    def emit(self, kind, data):
        self.events.append((kind, data))

    def test_consent_page_skips_the_app_and_never_taps(self):
        consent = window([page([node('Button', '[300,900][500,960]', text='同意')])])
        phone = FakePhone([switch_page(False), consent])
        engine.run(phone, self.SEGMENTS[1:], None, self.emit)
        self.assertIn(('segment', {'id': 'b', 'status': 'skipped', 'note': '这个 App 还没同意过协议'}), self.events)
        self.assertFalse(any('click' in c for c in phone.commands))

    def test_restore_only_touches_listed_switches(self):
        phone = FakePhone([switch_page(True)])
        engine.run(phone, self.SEGMENTS, {'a/热搜榜': True}, self.emit)
        self.assertEqual(self.events[0][1]['status'], 'running')
        self.assertTrue(any(k == 'segment' and d['id'] == 'b' and d['status'] == 'skipped' for k, d in self.events))
        self.assertFalse(any('com.demo' in c for c in phone.commands))

    def test_stop_interrupts_the_run(self):
        phone = FakePhone([switch_page(False)])
        phone.should_stop = lambda: True
        with self.assertRaises(engine.Stopped):
            engine.run(phone, self.SEGMENTS, None, self.emit)

    def test_transient_read_failure_retries_the_segment(self):
        """读屏偶尔失败而手机还连着，这一段重跑一次，不整轮停掉。"""
        phone = FakePhone(['garbage', 'garbage', 'garbage', switch_page(True), switch_page(False)])
        orig = phone.shell
        phone.shell = lambda cmd, timeout=30: 'ok\n' if cmd == 'echo ok' else orig(cmd, timeout)
        engine.run(phone, self.SEGMENTS[:1], None, self.emit)
        kinds = [k for k, _ in self.events]
        self.assertIn('retry', kinds)
        self.assertIn(('segment', {'id': 'a', 'status': 'done', 'note': ''}), self.events)

    def test_lost_device_is_not_retried_forever(self):
        phone = FakePhone(['garbage'])
        with self.assertRaises(engine.DeviceLost):
            engine.run(phone, self.SEGMENTS[:1], None, self.emit)

    def test_never_opens_settings_home_for_uri_segments(self):
        phone = FakePhone([switch_page(False)])
        engine.run(phone, self.SEGMENTS[:1], None, self.emit)
        self.assertTrue(any("-U 'x'" in c for c in phone.commands))


class ParityTest(unittest.TestCase):
    """桌面和手机是同一套规则，改一边另一边要跟上。"""

    def test_confirm_words_match_phone_engine(self):
        source = (HARMONY / 'entry/src/main/ets/engine/Phone.ets').read_text('utf-8')
        words = re.findall(r"'([^']+)'", re.search(r'CONFIRM_WORDS: string\[\] = \[(.*?)\]', source, re.S).group(1))
        self.assertEqual(tuple(words), engine.CONFIRM_WORDS)

    def test_consent_words_excluded_from_confirm(self):
        for word in engine.CONFIRM_WORDS:
            self.assertNotIn('同意', word)
            self.assertNotIn('允许', word)

    def test_segments_cover_every_recipe_word(self):
        from gui import harmony_vocab as vocab
        expected = sorted((g.segment_id, w.text) for g in vocab.parse().groups for w in g.words)
        actual = sorted((s['id'], t['title']) for s in engine.load_segments() for p in s['pages'] for t in p['targets'])
        self.assertEqual(actual, expected)

    def test_choose_and_protective_targets_want_on(self):
        targets = {t['title']: t for s in engine.load_segments() for p in s['pages'] for t in p['targets']}
        self.assertTrue(targets['要求应用请求关联']['want'])
        self.assertTrue(targets['简洁主页']['want'])
        self.assertEqual(targets['简洁主页']['radio'], 1)
        self.assertTrue(targets['个性化广告']['below'])
        self.assertFalse(targets['热搜榜']['want'])
