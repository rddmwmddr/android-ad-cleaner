"""PLZ110 机型选择与本机商店路径，不操作手机。

回读守卫沿用 PMX110 已有行为，旧实现也绿，守的是不回退。
"""
import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tool'))
from fixtures import Clock, fake_phone, install_clock, load_recipe, phone_mock
import fast
import run

RECIPE = ROOT / 'recipes/oneplus-PLZ110/recipe.py'

class Plz110RecipeTests(unittest.TestCase):
    def test_exact_model_has_its_own_seven_verified_segments(self):
        selected, reference = run.recipe_for('PLZ110', 'OnePlus', {'build': 'PLZ110_17.0.0.107(CN01)', 'os': ''})
        self.assertEqual(Path(selected), RECIPE)
        self.assertFalse(reference)
        self.assertEqual(run.recipe_meta(RECIPE)['steps'], ['软件商店', '下拉搜索', '负一屏', '主题', '视频', '游戏中心', '小布建议'])

    def scope(self):
        phone = phone_mock(W=1272, H=2772)
        scope, _ = load_recipe(phone, RECIPE, ['__no_steps__'])
        return phone, scope

    def test_store_prefers_privacy_entry_with_authorization_fallback(self):
        phone, scope = self.scope()
        for helper in ('app_settings', 'row', 'close_named'):
            scope[helper] = Mock()
        scope['read_switches'] = Mock(return_value={'福利专区': False})
        node = next(node for node in ast.parse(RECIPE.read_text(encoding='utf-8')).body
                    if isinstance(node, ast.FunctionDef) and node.decorator_list
                    and node.decorator_list[0].args[0].value == '软件商店')
        node.decorator_list, node.name = [], 'store_action'
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(RECIPE), 'exec'), scope)
        scope['store_action']()
        self.assertEqual(scope['app_settings'].call_args_list,
                         [call('com.heytap.market'), call('com.heytap.market')])
        self.assertEqual(scope['row'].call_args_list, [
            call(('隐私', '隐私授权管理'), package='com.heytap.market', activity='PrivacyActivity',
                 tries=3),
            call('个性化推荐', package='com.heytap.market', activity='PersonalRecommendActivity'),
            call('服务管理'),
        ])
        scope['read_switches'].assert_called_once_with('服务管理')
        self.assertEqual(scope['close_named'].call_args_list, [
            call(['个性化推荐'], '个性化推荐'),
            call(['福利专区'], '服务管理', snapshot={'福利专区': False}),
        ])

    def test_privacy_entry_falls_back_to_authorization_and_checks_the_landing(self):
        """两份脚本各有一份 row()，这份副本也要退到「隐私授权管理」并验落点（#907）。"""
        phone, scope = self.scope()
        phone.locked.return_value = False
        phone.texts.return_value = []
        phone.settle.return_value = True
        phone.scroll_more.return_value = False
        phone.focus.return_value = ('com.heytap.market/'
                                    'com.heytap.market.mine.cn.setting.ui.PrivacyActivity')
        phone.find.side_effect = lambda text, exact=False: text == '隐私授权管理'
        phone.tree.return_value = ET.fromstring(
            '<hierarchy><node class="android.widget.TextView" text="隐私授权管理" clickable="true" '
            'bounds="[40,300][900,380]"/></hierarchy>')
        scope['row'](('隐私', '隐私授权管理'), package='com.heytap.market', activity='PrivacyActivity')
        phone.click.assert_called_once_with(470, 340)

    def test_privacy_entry_retries_a_swallowed_click(self):
        """这一行必须点开，原来 p.enter 有三连点；换成 row() 后 tries 要把这条保住（#286）。"""
        phone, scope = self.scope()
        phone.locked.return_value = False
        phone.texts.return_value = []
        phone.scroll_more.return_value = False
        phone.settle.side_effect = [False, False, True]
        phone.focus.return_value = ('com.heytap.market/'
                                    'com.heytap.market.mine.cn.setting.ui.PrivacyActivity')
        phone.find.side_effect = lambda text, exact=False: text == '隐私授权管理'
        phone.tree.return_value = ET.fromstring(
            '<hierarchy><node class="android.widget.TextView" text="隐私授权管理" clickable="true" '
            'bounds="[40,300][900,380]"/></hierarchy>')
        scope['row'](('隐私', '隐私授权管理'), package='com.heytap.market', activity='PrivacyActivity',
                     tries=3)
        self.assertEqual(phone.click.call_args_list, [call(470, 340)] * 3)

    def test_missing_privacy_entry_keeps_the_page_scene(self):
        """一加这份 row() 也要在认不到入口时留下停在哪个页面与结构摘要（#907）。"""
        clock = Clock()
        original = fast.time
        install_clock(fast, clock)
        self.addCleanup(setattr, fast, 'time', original)
        page = ('<hierarchy rotation="0"><node class="android.widget.TextView" text="个性化推荐" '
                'clickable="true" bounds="[40,300][900,380]"/></hierarchy>')
        focus = 'com.heytap.market/com.heytap.market.mine.cn.setting.ui.SettingActivity'
        phone = fake_phone(clock=clock, stages=((0.0, page),), focus=((0.0, focus),))
        lines = []
        phone.say = phone.conn.say = lambda *a, **k: lines.append(' '.join(str(x) for x in a))
        scope, _ = load_recipe(phone, RECIPE, ['__no_steps__'])
        with self.assertRaisesRegex(RuntimeError, '没找到入口「隐私」，未继续本段'):
            scope['row'](('隐私', '隐私授权管理'), package='com.heytap.market',
                         activity='PrivacyActivity', tries=3)
        log = '\n'.join(lines)
        self.assertIn(focus, log)
        self.assertIn('结构', log)
        self.assertIn('隐私授权管理', log)

    def test_already_closed_targets_do_not_click_service_switches(self):
        phone, scope = self.scope()
        scope['read_switches'] = Mock(return_value={
            '应用安全': True, '应用安全安全内容推荐': False, '帮助与客服': True,
        })
        scope['close_named'](['应用安全安全内容推荐'], '服务管理')
        scope['read_switches'].assert_called_once_with('服务管理', 12)
        phone.off.assert_not_called()
        self.assertEqual(scope['VERIFIED_SWITCHES'], 1)

    def test_service_change_fails_readback(self):
        phone, scope = self.scope()
        scope['read_switches'] = Mock(side_effect=[
            {'应用安全': True, '应用安全安全内容推荐': True},
            {'应用安全': False, '应用安全安全内容推荐': False},
        ])
        with self.assertRaisesRegex(RuntimeError, '其他功能开关状态变化'):
            scope['close_named'](['应用安全安全内容推荐'], '服务管理')
        self.assertEqual(scope['read_switches'].call_count, 2)
        phone.off.assert_called_once()

    def test_missing_target_does_not_click(self):
        phone, scope = self.scope()
        scope['read_switches'] = Mock(return_value={'应用安全': True})
        with self.assertRaisesRegex(RuntimeError, '未识别全部目标'):
            scope['close_named'](['应用安全安全内容推荐'], '服务管理')
        scope['read_switches'].assert_called_once_with('服务管理', 12)
        phone.off.assert_not_called()

if __name__ == '__main__':
    unittest.main()
