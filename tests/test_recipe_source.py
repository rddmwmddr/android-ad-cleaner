"""机型脚本的「事实」层（tool/recipe_source.py，#1195）：一份源码里的调用点按语法解析，不按正则切。

守的是「脚本只被解释一次」这件事：实参切分（嵌套调用、含逗号字符串）、形参回填与
「最后一次赋值不是字面量时不退回旧值」、`am start -n` 与 `am start -a … -p` 的三种包名写法、
`p.setting` 两个实参、注入名归一，以及语法错直接抛。

共享实现的归属跟 import 走（#1243）：`from X import n` 与 `import X` + `X.n(…)` 都解析到 X 里那份，
两张注册表不再按名字合并；脚本本地同名 `def` 覆盖导入版，没有 import 的裸名字不算注入实现。
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import recipe_source  # noqa: E402


def scan(src):
    return recipe_source.scan_source(textwrap.dedent(src))


def calls(facts, name):
    return [call for call in facts.calls if call.name == name]


def only(call, keyword):
    return next(arg for arg in call.args if arg.keyword == keyword)


def texts(items):
    return [item.text for item in items]


class ArgumentTest(unittest.TestCase):
    """实参按语法切分：`[^)]*` 那套正则遇到嵌套调用或含逗号的字符串会静默错位。"""

    def test_nested_call_and_comma_string_stay_one_argument(self):
        facts = scan('''
            NAMES = ["开屏广告", "资讯,列表广告"]

            def _():
                p.off(only=NAMES, page="广告管理")
                p.setting(which("广告", "广告服务"), "广告服务")
        ''')
        off = calls(facts, "p.off")[0]
        self.assertEqual(texts(only(off, "only").values), ["开屏广告", "资讯,列表广告"])
        setting = calls(facts, "p.setting")[0]
        self.assertEqual(setting.args[0].text, "which('广告', '广告服务')")
        self.assertEqual(setting.args[0].values, ())
        self.assertEqual(texts(setting.args[1].values), ["广告服务"])

    def test_empty_list_is_resolved_with_no_values(self):
        """`only=[]` 解析成功、零个值；它与读不出靠 `resolved` 分开（词库靠这一位决定记不记未解析）。"""
        argument = only(calls(scan('p.off(only=[], page="广告管理")'), "p.off")[0], "only")
        self.assertTrue(argument.resolved)
        self.assertEqual(argument.values, ())

    def test_unreadable_expression_is_not_resolved(self):
        argument = only(calls(scan('p.off(only=load(), page="广告管理")'), "p.off")[0], "only")
        self.assertFalse(argument.resolved)

    def test_setting_restores_both_positional_arguments(self):
        facts = scan('''
            def _():
                p.setting("广告跟踪", "限制广告跟踪", path="隐私与安全 > 隐私 > 设备标识与广告")
        ''')
        setting = calls(facts, "p.setting")[0]
        self.assertEqual(texts(setting.args[0].values), ["广告跟踪"])
        self.assertEqual(texts(setting.args[1].values), ["限制广告跟踪"])
        self.assertEqual(only(setting, "path").keyword, "path")

    def test_page_label_follows_the_two_spellings(self):
        facts = scan('''
            def _():
                p.off(only=["a"], page="广告管理")
                p.off(only=["b"], page=f"{FAMILY}·隐私")
                close_named(["c"], "服务管理", snapshot=available)
        ''')
        self.assertEqual([call.page for call in facts.calls], ["广告管理", "{FAMILY}·隐私", "服务管理"])


class NameTest(unittest.TestCase):
    """名字的值取「文件内、位置之前最后一次同名赋值」；形参从左近的调用处回填。"""

    def test_formal_parameter_backfilled_from_call_site(self):
        facts = scan('''
            def open_settings(package, activity):
                p.start(package, activity)

            def _():
                open_settings("com.miui.securitycenter", ".settings.SettingsActivity")
        ''')
        start = calls(facts, "p.start")[0]
        self.assertEqual(texts(start.args[0].values), ["com.miui.securitycenter"])
        self.assertEqual(start.args[0].param, 0)
        self.assertEqual(texts(start.args[1].values), [".settings.SettingsActivity"])

    def test_last_assignment_wins_and_non_literal_does_not_fall_back(self):
        facts = scan('''
            def _():
                package = "com.old"
                package = "com.new"
                p.start(package, ".X")
        ''')
        self.assertEqual(texts(calls(facts, "p.start")[0].args[0].values), ["com.new"])

        facts = scan('''
            def _():
                package = "com.old"
                package = load()
                p.start(package, ".X")
        ''')
        self.assertEqual(calls(facts, "p.start")[0].args[0].values, ())

    def test_assignment_keeps_the_whole_command_string(self):
        """赋值取的是那次赋值的字符串本身：整条命令带空格与 `/`，旧词法的字符集卡只卡标识符那条路。"""
        facts = scan('''
            def _():
                hot_news = "am start -f 0x10008000 -n com.coloros.assistantscreen/.InfoFlowSettingActivity"
                open_page(hot_news, "热点资讯")
        ''')
        command = calls(facts, "open_page")[0].args[0]
        self.assertEqual(texts(command.values),
                         ["am start -f 0x10008000 -n com.coloros.assistantscreen/.InfoFlowSettingActivity"])

    def test_parameter_without_a_call_site_in_this_file_is_unreadable(self):
        facts = scan('''
            def app_settings(package):
                p.d.shell("am start -a oppo.intent.action.APP_SETTINGS -p " + package)
        ''')
        argument = calls(facts, "p.d.shell")[0].args[0]
        self.assertEqual(argument.values, ())
        self.assertEqual(argument.text, "'am start -a oppo.intent.action.APP_SETTINGS -p ' + package")


class AmStartTest(unittest.TestCase):
    """公开 Intent 与直达命令的包名三种写法：字面量、拼接变量、模板常量 `.format()`。"""

    SRC = '''
        MARKET = "com.heytap.market"
        TEMPLATE = "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p {}"

        def _():
            p.d.shell("am start -f 0x10008000 -n com.android.browser/.BrowserSettingsActivity")
            p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market")
            p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + MARKET)
            p.d.shell(TEMPLATE.format(MARKET))
    '''

    def test_all_three_spellings_resolve_to_the_same_command(self):
        commands = [texts(arg.values)[0] for call in calls(scan(self.SRC), "p.d.shell") for arg in call.args]
        self.assertEqual(len(commands), 4)
        self.assertEqual(commands[0], "am start -f 0x10008000 -n com.android.browser/.BrowserSettingsActivity")
        self.assertEqual(commands[1:], ["am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market"] * 3)

    def test_each_call_site_of_a_parameter_yields_its_own_command(self):
        facts = scan('''
            def app_settings(package):
                p.d.shell("am start -a oppo.intent.action.APP_SETTINGS -p " + package)

            def _():
                app_settings("com.heytap.market")
                app_settings("com.heytap.themestore")
        ''')
        command = calls(facts, "p.d.shell")[0].args[0]
        self.assertEqual(texts(command.values),
                         ["am start -a oppo.intent.action.APP_SETTINGS -p com.heytap.market",
                          "am start -a oppo.intent.action.APP_SETTINGS -p com.heytap.themestore"])




class DictEntryTest(unittest.TestCase):
    """模块级字典里的常量键值对：词库拿它筛说明文字，事实层只出结构、不判中文。"""

    def test_constant_pairs_carry_the_line_of_their_value(self):
        facts = scan('''
            CHANGES = {
                "音乐": "朋友页显示推荐动态",
                "浏览器":
                    "模式选择 → 简洁首页",
            }
            OTHER = {"com.a": ".Main"}
        ''')
        self.assertEqual([(entry.key, entry.value, entry.line) for entry in facts.dict_entries],
                         [("音乐", "朋友页显示推荐动态", 3), ("浏览器", "模式选择 → 简洁首页", 5),
                          ("com.a", ".Main", 7)])

    def test_non_constant_pairs_are_skipped(self):
        facts = scan('D = {**base, "a": ["不是字符串"], 1: "数字键"}')
        self.assertEqual(facts.dict_entries, ())


class DirectoryTest(unittest.TestCase):
    """遍历口径只在这里：只读 `recipe*.py`、相对路径、品牌过滤。"""

    def test_scan_dir_reads_recipe_files_only(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("xiaomi/M154FF/recipe.py", "xiaomi/M154FF/recipe_os4.py",
                         "xiaomi/M154FF/notes.txt", "unknown/M1/recipe.py"):
                path = Path(root) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("def _():\n    pass\n", encoding="utf-8")
            everything = recipe_source.scan_dir(root)
            self.assertEqual(list(everything), ["unknown/M1/recipe.py",
                                                "xiaomi/M154FF/recipe.py", "xiaomi/M154FF/recipe_os4.py"])
            known = recipe_source.scan_dir(root, {"xiaomi": "xiaomi"})
            self.assertEqual(list(known), ["xiaomi/M154FF/recipe.py", "xiaomi/M154FF/recipe_os4.py"])


class ErrorTest(unittest.TestCase):
    """语法错一律抛，不做容错返回：静默少几台机型比崩掉更糟。"""

    def test_syntax_error_is_raised(self):
        with self.assertRaises(SyntaxError):
            recipe_source.scan_source("def _(:\n    pass\n")


if __name__ == "__main__":
    unittest.main()
