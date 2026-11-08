"""PLZ110 机型选择与本机商店路径，不操作手机。

回读守卫沿用 PMX110 已有行为，旧实现也绿，守的是不回退。
"""
import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tool'))
from fixtures import load_recipe, phone_mock
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

    def test_store_uses_privacy_authorization_instead_of_missing_privacy_entry(self):
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
        phone.enter.assert_called_once_with('隐私授权管理', scrolls=8)
        self.assertEqual(scope['app_settings'].call_args_list,
                         [call('com.heytap.market'), call('com.heytap.market')])
        self.assertEqual(scope['row'].call_args_list, [
            call('个性化推荐', package='com.heytap.market', activity='PersonalRecommendActivity'),
            call('服务管理'),
        ])
        scope['read_switches'].assert_called_once_with('服务管理')
        self.assertEqual(scope['close_named'].call_args_list, [
            call(['个性化推荐'], '个性化推荐'),
            call(['福利专区'], '服务管理', snapshot={'福利专区': False}),
        ])

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
