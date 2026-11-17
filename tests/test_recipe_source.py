"""机型脚本的「事实」层（tool/recipe_source.py，#1195）：一份源码里的调用点按语法解析，不按正则切。

守的是「脚本只被解释一次」这件事：实参切分（嵌套调用、含逗号字符串）、形参回填与
「最后一次赋值不是字面量时不退回旧值」、`am start -n` 与 `am start -a … -p` 的三种包名写法、
`p.setting` 两个实参、注入名归一，以及语法错直接抛。

共享实现的归属跟 import 走（#1243）：`from X import n` 与 `import X` + `X.n(…)` 都解析到 X 里那份，
两张注册表不再按名字合并；脚本本地同名 `def` 覆盖导入版，没有 import 的裸名字不算注入实现。
"""
import ast
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import recipe_source  # noqa: E402
from recipe_source import Item  # noqa: E402


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
                p.shell("am start -a oppo.intent.action.APP_SETTINGS -p " + package)
        ''')
        argument = calls(facts, "p.shell")[0].args[0]
        self.assertEqual(argument.values, ())
        self.assertEqual(argument.text, "'am start -a oppo.intent.action.APP_SETTINGS -p ' + package")


class AmStartTest(unittest.TestCase):
    """公开 Intent 与直达命令的包名三种写法：字面量、拼接变量、模板常量 `.format()`。"""

    SRC = '''
        MARKET = "com.heytap.market"
        TEMPLATE = "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p {}"

        def _():
            p.shell("am start -f 0x10008000 -n com.android.browser/.BrowserSettingsActivity")
            p.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market")
            p.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + MARKET)
            p.shell(TEMPLATE.format(MARKET))
    '''

    def test_all_three_spellings_resolve_to_the_same_command(self):
        commands = [texts(arg.values)[0] for call in calls(scan(self.SRC), "p.shell") for arg in call.args]
        self.assertEqual(len(commands), 4)
        self.assertEqual(commands[0], "am start -f 0x10008000 -n com.android.browser/.BrowserSettingsActivity")
        self.assertEqual(commands[1:], ["am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market"] * 3)

    def test_each_call_site_of_a_parameter_yields_its_own_command(self):
        facts = scan('''
            def app_settings(package):
                p.shell("am start -a oppo.intent.action.APP_SETTINGS -p " + package)

            def _():
                app_settings("com.heytap.market")
                app_settings("com.heytap.themestore")
        ''')
        command = calls(facts, "p.shell")[0].args[0]
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

    def test_a_stray_file_in_a_model_slot_does_not_stop_the_scan(self):
        """`*/*` 这一层既会匹配目录也会匹配文件：排在前面的散落文件只跳过，不终止遍历。"""
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "aaa").mkdir()
            (Path(root) / "aaa" / "notes.txt").write_text("x", encoding="utf-8")
            model = Path(root) / "xiaomi" / "M154FF"
            model.mkdir(parents=True)
            (model / "recipe.py").write_text("def _():\n    pass\n", encoding="utf-8")
            self.assertEqual(list(recipe_source.scan_dir(root)), ["xiaomi/M154FF/recipe.py"])


class LibrarySourcesTest(unittest.TestCase):
    """库实现表是进程内常量：`inspect.getsource` 很慢，一次全量回归会调上千次（#1307）。"""

    def test_second_call_reuses_the_scanned_table(self):
        self.assertIs(recipe_source.library_sources(), recipe_source.library_sources())


class ScanCacheTest(unittest.TestCase):
    """同一份源码只解析一次（#1321）：`tests.test_vocab` 单跑时 `scan_source` 被调 13,116 次，
    不同源码只有 282 份。`bindings` / `externals` 是 dict，缓存键得先收成可哈希的形状；
    两条 `test_distinct_*` 在加缓存之前也是绿的，守的是缓存键不漏字段。"""

    SRC = 'NAMES = ["广告"]\n\ndef _():\n    p.off(only=NAMES, page="广告管理")\n'

    def test_repeated_scans_parse_the_source_once(self):
        src = 'p.off(only=["广告"], page="广告管理")\n'
        recipe_source.scan_source(src)   # 预热：先吃掉可能还没缓存的那一次
        with mock.patch.object(recipe_source.ast, "parse", wraps=ast.parse) as parse:
            for _ in range(5):
                recipe_source.scan_source(src)
        self.assertEqual(parse.call_count, 0)

    def test_cached_scan_returns_the_same_object(self):
        first = recipe_source.scan_source(self.SRC)
        self.assertIs(first, recipe_source.scan_source(self.SRC))

    def test_distinct_externals_do_not_share_a_cache_entry(self):
        src = "def _():\n    p.off(only=rt.constants['HOT'], page=\"广告\")\n"
        first = recipe_source.scan_source(src, externals={"HOT": (Item("热词一", 1),)})
        second = recipe_source.scan_source(src, externals={"HOT": (Item("热词二", 1),)})
        self.assertIsNot(first, second)
        self.assertEqual(texts(only(calls(first, "p.off")[0], "only").values), ["热词一"])
        self.assertEqual(texts(only(calls(second, "p.off")[0], "only").values), ["热词二"])

    def test_distinct_bindings_do_not_share_a_cache_entry(self):
        src = "def _fn(one):\n    p.off(only=one, page=\"广告\")\n"
        first = recipe_source.scan_source(src, bindings={0: ["热词一"]})
        second = recipe_source.scan_source(src, bindings={0: ["热词二"]})
        self.assertIsNot(first, second)
        self.assertEqual(texts(only(calls(first, "p.off")[0], "only").values), ["热词一"])
        self.assertEqual(texts(only(calls(second, "p.off")[0], "only").values), ["热词二"])


class PageLabelTest(unittest.TestCase):
    """页面标签的每一处写法：`page=` / `title=`、`close_named*` 的位置实参、以及没写时的空串。"""

    def pages(self, src):
        return [call.page for call in scan(src).calls]

    def test_a_call_without_a_page_keyword_has_an_empty_label(self):
        self.assertEqual(self.pages('p.off(only=["a"])'), [""])

    def test_title_is_the_fallback(self):
        self.assertEqual(self.pages('p.off(only=["a"], title="标题")'), ["标题"])
        self.assertEqual(self.pages('close_named(["a"], title="标题")'), ["标题"])

    def test_page_wins_over_title(self):
        self.assertEqual(self.pages('p.off(only=["a"], page="页面", title="标题")'), ["页面"])
        self.assertEqual(self.pages('close_named(["a"], page="页面", title="标题")'), ["页面"])

    def test_close_named_without_a_label_position_has_an_empty_page(self):
        self.assertEqual(self.pages('close_named(["a"])'), [""])
        self.assertEqual(self.pages('def _():\n    close_named(p, rt)'), [""])

    def test_the_injected_prefix_is_stripped_before_the_page(self):
        self.assertEqual(self.pages('def _():\n    close_named(p, rt, ["a"], "页面")'), ["页面"])

    def test_a_variable_named_rt_alone_is_not_the_prefix(self):
        """`close_named(名单, rt)` 只对上了 `rt` 那一位：前缀没剥，`rt` 是第二个位置实参。"""
        self.assertEqual(self.pages('def _():\n    close_named(["a"], rt)'), ["<rt>"])

    def test_a_keyword_after_the_prefix_belongs_to_the_page_lookup(self):
        """前缀只看前两位：第三位起是关键字实参时，剥完前缀仍要从 `page=` 取标签。"""
        self.assertEqual(self.pages('def _():\n    close_named(p, rt, page="页")'), ["页"])

    def test_a_module_qualified_close_named_reads_its_page(self):
        """`strategies.close_named_vivo(...)` 是属性调用，模块限定名也要认（策略库的位置写法）。"""
        self.assertEqual(self.pages('strategies.close_named_vivo(["a"], "页面")'), ["页面"])


class ValueResolutionTest(unittest.TestCase):
    """一个表达式解析出的字符串：常量、外部常量、形参回填、`rt.constants` 与拼接的笛卡尔积。"""

    def test_a_literal_carries_its_own_line(self):
        facts = scan('def _():\n    p.off(only="甲", page="p")')
        argument = only(calls(facts, "p.off")[0], "only")
        self.assertEqual([(item.text, item.line) for item in argument.values], [("甲", 2)])

    def test_the_last_assignment_before_the_use_carries_its_line(self):
        facts = scan('X = "甲"\ndef _():\n    p.off(only=X, page="p")')
        argument = only(calls(facts, "p.off")[0], "only")
        self.assertEqual([(item.text, item.line) for item in argument.values], [("甲", 1)])

    def test_a_bare_name_is_read_from_the_callers_constants(self):
        facts = recipe_source.scan_source('def _():\n    p.off(only=HOT, page="p")',
                                          externals={"HOT": (Item("热", 1),)})
        self.assertEqual(texts(only(calls(facts, "p.off")[0], "only").values), ["热"])

    def test_backfilled_values_carry_the_use_line(self):
        facts = recipe_source.scan_source('def f(one):\n    p.off(only=one, page="p")',
                                          bindings={0: ["热"]})
        argument = only(calls(facts, "p.off")[0], "only")
        self.assertEqual([(item.text, item.line) for item in argument.values], [("热", 2)])

    def test_rt_constants_get_is_read_like_the_subscript(self):
        src = 'def _():\n    p.off(only=rt.constants.get("HOT"), page="p")'
        facts = recipe_source.scan_source(src, externals={"HOT": (Item("热", 1),)})
        self.assertEqual(texts(only(calls(facts, "p.off")[0], "only").values), ["热"])

    def test_rt_constants_get_reads_the_name_not_the_default(self):
        src = 'def _():\n    p.off(only=rt.constants.get("HOT", "默认"), page="p")'
        facts = recipe_source.scan_source(src, externals={"HOT": (Item("热", 1),)})
        self.assertEqual(texts(only(calls(facts, "p.off")[0], "only").values), ["热"])

    def test_concatenation_backfills_both_operands_and_yields_their_product(self):
        facts = scan('''
            def shell(a, b):
                p.shell(a + b)
            def _():
                shell("x1", "y1")
                shell("x2", "y2")
        ''')
        argument = calls(facts, "p.shell")[0].args[0]
        self.assertEqual(texts(argument.values), ["x1y1", "x1y2", "x2y1", "x2y2"])
        self.assertEqual({item.line for item in argument.values}, {3})


class FormattedTemplateTest(unittest.TestCase):
    """`模板常量.format(…)`：占位按位置从左往右填，多一个 / 少一个都读不出。"""

    def values(self, src):
        return calls(scan(src), "p.shell")[0].args[0].values

    def test_a_template_without_a_slot_is_not_read(self):
        self.assertEqual(self.values('T = "am start"\ndef _():\n    p.shell(T.format())'), ())

    def test_two_slots_are_filled_left_to_right(self):
        # 与行号那条用不同的模板：`scan_source` 进程内缓存会吞掉同源的第二份，变异统计看不到它。
        self.assertEqual(
            texts(self.values('T = "go {} via {}"\ndef _():\n    p.shell(T.format("x", "y"))')),
            ["go x via y"])

    def test_a_leftover_slot_is_unreadable(self):
        self.assertEqual(self.values('T = "{} {}"\ndef _():\n    p.shell(T.format("a"))'), ())

    def test_a_parameter_is_backfilled_through_the_template(self):
        facts = scan('''
            T = "am start -a oppo.intent.action.APP_SETTINGS -p {}"
            def app_settings(package):
                p.shell(T.format(package))
            def _():
                app_settings("com.heytap.market")
        ''')
        self.assertEqual(
            texts(calls(facts, "p.shell")[0].args[0].values),
            ["am start -a oppo.intent.action.APP_SETTINGS -p com.heytap.market"])

    def test_every_filled_part_carries_the_call_line(self):
        values = self.values('T = "am {} -n {}"\ndef _():\n    p.shell(T.format("a", "b"))')
        self.assertEqual({item.line for item in values}, {3})


class ImportScanTest(unittest.TestCase):
    """脚本的导入面：`import X` / `import X.Y` / 别名 / `from . import` / TYPE_CHECKING 与 try 块。"""

    def test_a_plain_import_maps_the_top_name(self):
        facts = scan("import recipe_nav")
        self.assertEqual(facts.imports, {"recipe_nav": "recipe_nav"})
        self.assertEqual(facts.import_lines, {"recipe_nav": 1})

    def test_a_dotted_import_maps_its_top_segment_to_the_full_module(self):
        self.assertEqual(scan("import package.sub").imports, {"package": "package.sub"})

    def test_an_aliased_dotted_import_keeps_the_alias(self):
        facts = scan("import package.sub as alias")
        self.assertEqual(facts.imports, {"alias": "package.sub"})

    def test_from_imports_map_the_name_to_the_module(self):
        self.assertEqual(scan("from recipe_nav import gear").imports, {"gear": "recipe_nav"})
        self.assertEqual(scan("from recipe_nav import gear as g").imports, {"g": "recipe_nav"})

    def test_a_relative_from_import_has_an_empty_module(self):
        self.assertEqual(scan("from . import helpers").imports, {"helpers": ""})

    def test_type_checking_and_try_blocks_are_walked(self):
        facts = scan('''
            if TYPE_CHECKING:
                import recipe_nav
            try:
                import recipe_strategies
            except ImportError:
                import recipe_steps
        ''')
        self.assertEqual(facts.imports, {"recipe_nav": "recipe_nav",
                                         "recipe_strategies": "recipe_strategies",
                                         "recipe_steps": "recipe_steps"})

    def test_a_function_local_import_is_not_collected(self):
        self.assertEqual(scan("def f():\n    import recipe_nav").imports, {})

    def test_a_subscript_call_name_is_unwrapped(self):
        """历史写法 `g["X"](…)` 归一成裸名 `X`：按名字写的调用，但没有 import 归属。"""
        call = calls(scan('def _():\n    g["off_exact"](p, rt)'), "off_exact")[0]
        self.assertEqual((call.injected, call.module), (True, ""))

    def test_an_attribute_call_is_not_injected_and_has_no_module(self):
        call = calls(scan('def _():\n    p.start("com.a", ".X")'), "p.start")[0]
        self.assertEqual((call.injected, call.module), (False, ""))

    def test_a_bare_name_without_an_import_has_an_empty_module(self):
        self.assertEqual(calls(scan("def _():\n    gear(p, rt)"), "gear")[0].module, "")


class ModuleConstantTest(unittest.TestCase):
    """模块级常量：单个字符串与纯字符串列表，后赋了别的值就不算。"""

    def test_augmented_assignment_drops_the_constant(self):
        self.assertEqual(scan('X = "a"\nX += "b"').constants, {})

    def test_augmented_assignment_without_a_previous_value_does_not_raise(self):
        self.assertEqual(scan('X += "b"').constants, {})

    def test_a_later_augmented_assignment_does_not_stop_the_scan(self):
        self.assertEqual(texts(scan('A = "a"\nA += "b"\nB = "b"').constants["B"]), ["b"])

    def test_a_non_string_assignment_after_a_constant_drops_it(self):
        self.assertNotIn("X", scan('X = "a"\nX = load()').constants)

    def test_a_single_string_constant_carries_its_line(self):
        facts = scan('X = "a"')
        self.assertEqual([(item.text, item.line) for item in facts.constants["X"]], [("a", 1)])

    def test_a_dict_value_stops_resolving_after_a_non_dict_assignment(self):
        facts = scan('T = {"a": ["甲"]}\nT = 5\ndef _():\n    p.off(only=T["a"], page="p")')
        self.assertEqual(calls(facts, "p.off")[0].args[0].values, ())


class DictEntryScanTest(unittest.TestCase):
    """模块级字典的常量键值对：非字典语句跳过但不终止扫描，`{**other}` 的 None 键不收。"""

    def test_a_non_dict_statement_does_not_stop_the_scan(self):
        facts = scan('def f():\n    p.off(only=["甲"], page="p")\nCHANGES = {"音乐": "说明"}')
        self.assertEqual([(entry.key, entry.value) for entry in facts.dict_entries],
                         [("音乐", "说明")])


class BusinessArgsTest(unittest.TestCase):
    """`business_args()` 剥掉注入调用的 `(p, rt)` 前缀，只剥认得出的那一种，只剥前两位。"""

    def test_the_prefix_is_stripped_when_both_names_match(self):
        argument = calls(scan('def _():\n    close_named(p, rt, ["a"], "页")'), "close_named")[0]
        self.assertEqual([item.text for item in recipe_source.business_args(argument)],
                         ["['a']", "'页'"])

    def test_exactly_two_arguments_leave_nothing_behind(self):
        argument = calls(scan('def _():\n    close_named(p, rt)'), "close_named")[0]
        self.assertEqual(recipe_source.business_args(argument), ())

    def test_a_keyword_in_the_second_slot_means_no_prefix(self):
        argument = calls(scan('def _():\n    close_named(p, rt="x")'), "close_named")[0]
        self.assertEqual(len(recipe_source.business_args(argument)), 2)

    def test_a_keyword_after_the_prefix_is_kept(self):
        """前缀只看前两位：第三位起的关键字实参不是前缀，剥完仍原样返回。"""
        argument = calls(scan('def _():\n    close_named(p, rt, title="标题")'), "close_named")[0]
        self.assertEqual([item.text for item in recipe_source.business_args(argument)], ["'标题'"])


class ParamItemsTest(unittest.TestCase):
    """形参回填只从本文件里「函数定义之后」的调用处取。"""

    def test_a_call_on_the_definition_line_is_not_after_the_function(self):
        facts = scan('def f(x): p.off(only=x, page="p"); f("rec")')
        self.assertEqual(calls(facts, "p.off")[0].args[0].values, ())

    def test_an_earlier_call_does_not_end_the_search(self):
        facts = scan('''
            g("early")
            def f(x):
                p.off(only=x, page="p")
            def g(y):
                pass
            f("late")
        ''')
        self.assertEqual(texts(calls(facts, "p.off")[0].args[0].values), ["late"])


class WalkHitsTest(unittest.TestCase):
    """库实现逐层下扫（#1352）：只认有归属的调用，本地同名定义不命中，查不到的实现不进遍历。"""

    GEAR = ("recipe_lib.shared", "def gear(p, rt):\n    p.off(only=['甲'], page='p')\n")
    OFF_ONE = ("recipe_lib.shared", "def off_one(p, rt):\n    p.off(only=['乙'], page='p')\n")

    def hits(self, src, sources):
        return list(recipe_source.library_hits(scan(src), sources))

    def test_a_hit_reports_the_name_module_call_line_and_implementation_facts(self):
        facts = scan('''
            import recipe_nav

            def _():
                recipe_nav.gear(p, rt)
        ''')
        hits = recipe_source.library_hits(facts, {"gear": self.GEAR})
        hit = next(hits)
        self.assertEqual((hit.name, hit.module, hit.call_site), ("gear", "recipe_lib.shared", 5))
        self.assertEqual(texts(calls(hit.facts, "p.off")[0].args[0].values), ["甲"])

    def test_a_bare_name_without_an_import_is_not_a_library_call(self):
        self.assertEqual(self.hits("def _():\n    gear(p, rt)", {"gear": self.GEAR}), [])

    def test_a_local_definition_shadows_the_library_implementation(self):
        facts = scan('''
            import recipe_nav

            def gear(p, rt):
                pass

            def _():
                recipe_nav.gear(p, rt)
        ''')
        self.assertEqual(list(recipe_source.library_hits(facts, {"gear": self.GEAR})), [])

    def test_a_shadowed_name_does_not_end_the_walk(self):
        facts = scan('''
            import recipe_nav

            def gear(p, rt):
                pass

            def _():
                recipe_nav.gear(p, rt)
                recipe_nav.off_one(p, rt)
        ''')
        self.assertEqual([hit.name for hit in recipe_source.library_hits(
            facts, {"gear": self.GEAR, "off_one": self.OFF_ONE})], ["off_one"])

    def test_a_missing_implementation_does_not_end_the_walk(self):
        facts = scan('''
            import recipe_nav

            def _():
                recipe_nav.missing(p, rt)
                recipe_nav.gear(p, rt)
        ''')
        self.assertEqual([hit.name for hit in recipe_source.library_hits(
            facts, {"gear": self.GEAR})], ["gear"])

    def test_an_import_without_a_call_site_still_counts_with_its_line(self):
        facts = scan("from recipe_nav import gear")
        hits = recipe_source.library_hits(facts, {"gear": self.GEAR})
        self.assertEqual([(hit.name, hit.call_site) for hit in hits], [("gear", 1)])

    def test_a_formal_parameter_expression_is_not_backfilled_from_this_layer(self):
        """`_bindings()` 只收这一层写死的实参：形参的值是上一层的活，这里交回去就会错位（#1352）。"""
        facts = scan('''
            def f(names):
                close_named(names, "页")
            def _():
                f("甲")
        ''')
        self.assertEqual(recipe_source._bindings(calls(facts, "close_named")), {1: ("页",)})

    def test_literal_arguments_are_keyed_by_business_position(self):
        facts = scan('import recipe_nav\ndef _():\n    recipe_nav.gear(p, rt, "甲", "乙")')
        self.assertEqual(recipe_source._bindings(calls(facts, "gear")), {0: ("甲",), 1: ("乙",)})


class KeywordScanTest(unittest.TestCase):
    """`scan_source` 的形状：`**kwargs` 不截断后面的关键字，函数外的调用记空函数名。"""

    def test_a_double_star_argument_does_not_stop_the_other_keywords(self):
        facts = scan('def _():\n    p.off(**extra, page="页")')
        call = calls(facts, "p.off")[0]
        self.assertEqual(texts(only(call, "page").values), ["页"])
        self.assertEqual(call.page, "页")

    def test_a_module_level_call_has_an_empty_function_name(self):
        self.assertEqual(calls(scan('p.off(only=["a"], page="p")'), "p.off")[0].function, "")


class ErrorTest(unittest.TestCase):
    """语法错一律抛，不做容错返回：静默少几台机型比崩掉更糟。"""

    def test_syntax_error_is_raised(self):
        with self.assertRaises(SyntaxError):
            recipe_source.scan_source("def _(:\n    pass\n")


if __name__ == "__main__":
    unittest.main()
