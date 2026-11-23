"""catalog 内核（#1259）：页面树数据经唯一装载入口跑出与旧脚本逐条相同的调用序列，校验器在装载期
拒绝非法数据，`only` 两态（字面量 / 本机策略）与 UI「全部关闭」单列 page-wide。

判据只看外部行为：同一台合成手机、同一组读屏观察下的调用序列（复用 `compare_recipe_calls` 的记录
机制），以及数据经校验器后的接受 / 报错。不看解释器内部函数，也不看数据文件内部结构。
"""
import ast
import contextlib
import io
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tool"))

import fixtures  # noqa: E402
from fixtures import shell_result  # noqa: E402

fixtures.load_tool()
import catalog  # noqa: E402
import catalog_family  # noqa: E402
import family  # noqa: E402
import fast  # noqa: E402
import recipe_runtime  # noqa: E402

SCRIPT = "tests/fixtures/vivo_v1986a/recipe.py"
DATA = "recipes/vivo/V1986A/V1986A.toml"



def patch_library(case, **fns):
    """把库实现换成桩：解释器按名字查 `interpreter.LIBRARY`，只在用例期间替换。"""
    import catalog.interpreter as interpreter
    saved = {name: interpreter.LIBRARY.get(name) for name in fns}
    interpreter.LIBRARY.update(fns)
    def restore():
        for name, value in saved.items():
            if value is None:
                interpreter.LIBRARY.pop(name, None)
            else:
                interpreter.LIBRARY[name] = value
    case.addCleanup(restore)


class LibraryViewTests(unittest.TestCase):
    """`scope[...]` 的库视图（#1345）：五种结局直接落在库上，不再按顺序游三个兼容面。

    `MenuState` 是类型，`title_key` / `_labelled` 是纯函数不绑协作者，`labels` 只绑 `p`，其余绑
    `(p, rt)`。视图只给测试读库助手（解释器自己查 `interpreter.LIBRARY`），所以这里读到的就是
    「这名字该是什么」的全部判据——换了查找路径，这五种结局不许跟着变。
    """

    def setUp(self):
        import recipe_lib
        self.recipe_lib = recipe_lib
        self.phone = fixtures.fake_phone(clock=fixtures.Clock(), fast_mod=fast)
        self.scope = catalog.load(ROOT / DATA, self.phone, only=[]).namespace

    def test_the_menu_state_type_comes_back_unbound(self):
        self.assertIs(self.scope["MenuState"], self.recipe_lib.MenuState)
        self.assertEqual(tuple(self.scope["MenuState"](True, False)), (True, False))

    def test_pure_helpers_come_back_unbound(self):
        self.assertIs(self.scope["title_key"], self.recipe_lib.title_key)
        self.assertEqual(self.scope["title_key"]("设置.已开启"), "设置")
        self.assertIs(self.scope["_labelled"], self.recipe_lib._labelled)
        self.assertTrue(self.scope["_labelled"]("全部关闭 - 已停用", "全部关闭"))
        self.assertFalse(self.scope["_labelled"]("全部关闭服务", "全部关闭"))

    def test_labels_binds_only_the_phone(self):
        self.phone.texts = Mock(return_value=[("甲", "1", (0, 0)), ("乙", "2", (0, 1))])
        self.assertEqual(self.scope["labels"](), {"甲", "乙"})
        # `labels(p, root=None)` 只绑手机：装载器把 rt 也绑进去时这里收到的是 rt 而不是 None。
        self.phone.texts.assert_called_once_with(None)

    def test_library_implementations_bind_phone_and_runtime(self):
        stub = Mock(return_value={"甲": True})
        patch_library(self, read_switches=stub)
        self.assertEqual(self.scope["read_switches"]("设置页"), {"甲": True})
        self.assertEqual(stub.call_args.args, (self.phone, self.scope["rt"], "设置页"))

    def test_an_unknown_name_is_a_key_error(self):
        with self.assertRaises(KeyError) as caught:
            self.scope["no_such_library_name"]
        self.assertEqual(caught.exception.args, ("no_such_library_name",))
        with self.assertRaises(KeyError):      # 兼容壳的垫片内部名不是库名，别在这里冒出来
            self.scope["_root"]


class ScopeContractTests(unittest.TestCase):
    """装载器给出的命名空间（#1541）：字典初始化、`rt` 视图与 `ONLY` / `HALTED` 的写回。

    视图是测试读这次执行的唯一读缝（解释器自己查 `interpreter.LIBRARY`），所以读到的正是
    「这个名字该是什么」；写 `ONLY` / `HALTED` 必须落到 `rt` 上，否则用例改了名单不生效。"""

    def setUp(self):
        import catalog.loader as loader
        self.loader = loader
        self.phone = fixtures.fake_phone(clock=fixtures.Clock(), fast_mod=fast)
        self.rt = recipe_runtime.Runtime(self.phone, [], fixtures.Clock())
        self.scope = loader.CatalogScope({"preset": 1}, other=2, rt=self.rt)

    def test_positional_and_keyword_entries_both_land_in_the_scope(self):
        self.assertEqual(dict(self.scope), {"preset": 1, "other": 2})
        self.assertIs(self.scope.rt, self.rt)

    def test_the_runtime_names_come_from_this_execution(self):
        for name in ("page", "require", "skip", "require_switches",
                     "skip_in_safe_mode", "start_or_skip"):
            with self.subTest(name=name):
                self.assertEqual(self.scope[name], getattr(self.rt, name))

    def test_only_and_halted_write_through_to_the_runtime(self):
        self.scope["ONLY"] = ["a"]
        self.assertEqual(self.scope["ONLY"], ["a"])
        self.assertEqual(self.rt.only, ["a"])
        self.scope["HALTED"] = True
        self.assertTrue(self.scope["HALTED"])
        self.assertTrue(self.rt.halted)
        action = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            self.rt.run_step("a", action)
        action.assert_not_called()
        self.assertEqual(self.rt.halted_steps, ["a"])


class LoaderInputTests(unittest.TestCase):
    """装载入口的输入边界（#1541）：目录取唯一 `.toml`、同名例外 `.py`、常量与钩子绑定。"""

    TOML = '[[segment]]\nname="a"\nops=[]\n'

    def phone(self):
        return fixtures.fake_phone(clock=fixtures.Clock(), fast_mod=fast)

    def test_a_directory_with_one_toml_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "M.toml"
            data.write_text(self.TOML, encoding="utf-8")
            recipe = catalog.load(Path(tmp), self.phone())
        self.assertEqual(recipe.path, str(data))
        self.assertEqual([step.name for step in recipe.steps], ["a"])

    def test_a_directory_with_two_tomls_is_rejected_with_the_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "A.toml").write_text(self.TOML, encoding="utf-8")
            (Path(tmp) / "B.toml").write_text(self.TOML, encoding="utf-8")
            with self.assertRaises(FileNotFoundError) as caught:
                catalog.load(Path(tmp), self.phone())
        self.assertEqual(str(caught.exception), f"{Path(tmp)} 里应当恰有一份 .toml，实际 2 份")

    def test_an_empty_directory_is_rejected_with_the_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError) as caught:
                catalog.load(Path(tmp), self.phone())
        self.assertEqual(str(caught.exception), f"{Path(tmp)} 里应当恰有一份 .toml，实际 0 份")

    def test_a_broken_companion_points_at_its_own_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "M.toml").write_text(self.TOML, encoding="utf-8")
            companion = Path(tmp) / "M.py"
            companion.write_text("def broken(:\n", encoding="utf-8")
            with self.assertRaises(SyntaxError) as caught:
                catalog.load(companion.with_suffix(".toml"), self.phone())
        self.assertEqual(caught.exception.filename, str(companion))

    def test_the_callers_namespace_reaches_the_loaded_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "M.toml"
            data.write_text(self.TOML, encoding="utf-8")
            recipe = catalog.load(data, self.phone(), namespace={"PRESET": 7})
        self.assertEqual(recipe.namespace["PRESET"], 7)

    def test_only_uppercase_non_callables_become_constants(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[const]\nFROM_TOML = 2\n' + self.TOML,
                "import functools\nNO = 1\ndef PRINTER(p, rt):\n    pass\n")
        self.assertEqual(dict(recipe.rt.constants), {"FROM_TOML": 2, "NO": 1})

    def test_every_declared_hook_is_bound_under_its_runtime_name(self):
        hooks = ("tail", "guard", "detail", "wrap")
        toml = "".join(f'{hook} = "{hook}_fn"\n' for hook in hooks) + self.TOML
        py_text = "".join(
            f"def {hook}_fn(p, rt):\n    return None\n" for hook in hooks)
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(tmp, toml, py_text)
        self.assertEqual(dict(recipe.rt.constants), {})
        for hook in hooks:
            with self.subTest(hook=hook):
                self.assertIs(recipe.namespace[hook], recipe.namespace[f"{hook}_fn"])


class ValidatorTests(unittest.TestCase):
    """种类白名单：未知键、非法形状在装载期就报，不等真机。"""

    def test_rejects_invalid_shapes(self):
        for case in catalog_family.CASES:
            with self.subTest(case["id"]):
                with self.assertRaises(catalog.SchemaError) as caught:
                    catalog.validate(case["data"])
                self.assertIn(case["needle"], str(caught.exception))

    def test_accepts_the_shipped_data(self):
        import tomllib
        catalog.validate(tomllib.loads((ROOT / DATA).read_text(encoding="utf-8")))

    def test_accepts_the_boundary_values(self):
        """边界值也是合法数据：比例取 0 / 1、`ms=1`、`off_required` 不带 `keep`（#1414）。"""
        self.assertIsNone(catalog.validate({"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0, 0.5], "end": [1, 1], "ms": 1},
            {"kind": "off_required", "only": ["x"], "page": "p"},
        ]}]}))

    def test_the_top_level_sentences_are_exact(self):
        """顶层两条拒绝的原文逐字钉住：换个词、换个大小写、前后加个字都是另一种话（#1414）。"""
        for data, message in (
            ("这不是表", "数据顶层必须是表（table）"),
            ({"segment": "x"}, "至少要有 [[segment]]（一份数据至少一段）"),
        ):
            with self.subTest(message):
                with self.assertRaises(catalog.SchemaError) as caught:
                    catalog.validate(data)
                self.assertEqual(str(caught.exception), message)


class OpKeyListTests(unittest.TestCase):
    """`OPS` 每条的允许键由 `_keys` 从一行空格分隔的名单拆出来。

    它只在 import 时被调用一次，早于 mutation 生效，所以这里直接喂名单：一行写完、读一列就是
    完整键集，既是这份表的可读性约定，也是它唯一的产出（#1414）。"""

    def test_a_space_separated_line_becomes_the_key_set(self):
        from catalog.schema import _keys
        self.assertEqual(_keys("kind name args kwargs"),
                         frozenset({"kind", "name", "args", "kwargs"}))


class CatalogFamilyTests(unittest.TestCase):
    """族自己的守卫（沿用 #1398，结构反推 #1399）：句柄、产出、gap 跟快照与 `OPS` 对得上，case 行是纯数据。

    catalog 的 `id`（如 `skip-missing-text`）是手写的一句描述，不是任何字段的拼接——行里只有
    `data` 与 `needle`，没有可重建 id 的短句柄，所以这里不加「id 等于字段拼法」的断言；
    vocab / entries / channel_policy 三族各自有那一条（#1393 审查）。"""

    def test_snapshot_handles_and_outputs_agree(self):
        self.assertEqual(catalog_family.FAMILY.violations(), [])

    def test_case_rows_are_pure_data(self):
        self.assertEqual(family.pure_data_violations(catalog_family), [])

    def test_every_required_key_has_a_missing_case(self):
        """`OPS` 里每个必填键都要有一条「缺这个键」的 case（#1399）。"""
        self.assertEqual(catalog_family.FAMILY.gap_violations(), [])

    def test_a_new_required_key_demands_a_case(self):
        """加一个带必填键的 op，守卫立刻点名它缺 case——期望集合由 `OPS` 生成，不会自己漂。"""
        from catalog.schema import OPS as REAL_OPS, OpSpec
        probe = OpSpec(frozenset({"kind", "x"}), required=("x",))
        with patch.object(catalog_family, "OPS", {**REAL_OPS, "synthetic_probe": probe}):
            gaps = catalog_family.FAMILY.gap_violations()
        text = "\n".join(gaps)
        self.assertIn("synthetic_probe", text)
        self.assertIn("'x'", text)


def _load_tmp(tmp, toml_text, py_text=None):
    """在临时目录里放一份 .toml（与可选的本机例外 .py），经唯一入口装载。"""
    data = Path(tmp) / "M.toml"
    data.write_text(toml_text, encoding="utf-8")
    if py_text is not None:
        (Path(tmp) / "M.py").write_text(py_text, encoding="utf-8")
    phone = fixtures.fake_phone(clock=fixtures.Clock(), fast_mod=fast)
    calls = []

    def record_off(**kwargs):
        calls.append(("off", kwargs))

    def record_tap(text, **kwargs):
        calls.append(("tap", text))

    def record_confirm():
        calls.append(("confirm", None))

    phone.off = record_off
    phone.tap = record_tap
    phone.confirm = record_confirm
    recipe = catalog.load(data, phone, only=[])
    return recipe, phone, calls


class LoadTimeNameTests(unittest.TestCase):
    """装载期名字校验（#1289）：数据点名的库名 / 本机函数名写错在装载期就报，不等真机跑到那一段。"""

    def _bad(self, toml_text, *needles, py_text=None):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(catalog.SchemaError) as caught:
                _load_tmp(tmp, toml_text, py_text)
        message = str(caught.exception)
        for needle in needles:
            self.assertIn(needle, message)
        return message

    def test_a_misspelled_lib_name_is_rejected_and_suggests_the_close_one(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="lib", name="close_named_honr"}]\n',
                  "第 1 段「a」", "'close_named_honr'", "close_named_honor")

    def test_a_missing_require_lib_name_is_rejected(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="require_lib", name="no_such_helper",'
                  ' miss_print="x"}]\n', "'no_such_helper'")

    def test_a_missing_if_lib_name_is_rejected(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="if_lib", name="no_such_helper",'
                  ' ops=[{kind="back"}], else_ops=[{kind="back"}]}]\n', "'no_such_helper'")

    def test_a_missing_return_lib_name_is_rejected(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="return_lib", name="no_such_helper"}]\n',
                  "'no_such_helper'")

    def test_a_missing_segment_code_is_rejected(self):
        self._bad('[[segment]]\nname="a"\ncode="local_missing"\n',
                  "第 1 段「a」", "'local_missing'")

    def test_a_missing_only_code_strategy_is_rejected(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="off", page="p", only_code="no_such"}]\n',
                  "'no_such'")

    def test_a_missing_code_op_name_is_rejected(self):
        """op 级的 `code` 也走 `g[name]`（`interpreter._code`），与段级 `code=` 同一个命名空间。"""
        self._bad('[[segment]]\nname="a"\nops=[{kind="code", name="local_missing"}]\n',
                  "'local_missing'")

    def test_a_constant_in_the_exception_module_is_not_a_name(self):
        """合法的是可调用名字：命名空间里的常量被 `lib` 点名时拿到就调，会在运行时 TypeError。"""
        self._bad('[[segment]]\nname="a"\nops=[{kind="lib", name="NO"}]\n',
                  "'NO'", py_text="NO = 1\n")

    def test_a_nested_op_reports_the_index_chain(self):
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="back"}, {kind="if_lib", name="tap_row",'
            ' ops=[{kind="back"}, {kind="lib", name="no_such_helper"}], else_ops=[]}]\n',
            "'no_such_helper'")
        self.assertIn("第 2 个 op 的 ops 第 2 个 op", message)

    def test_an_else_ops_op_reports_the_index_chain(self):
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="if_focus", text="com.x/", ops=[{kind="back"}],'
            ' else_ops=[{kind="back"}, {kind="lib", name="no_such_helper"}]}]\n',
            "'no_such_helper'")
        self.assertIn("第 1 个 op 的 else_ops 第 2 个 op", message)

    def test_an_if_lib_any_name_call_is_checked(self):
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="if_lib_any", calls=[{name="no_such_helper"}],'
            ' ops=[], else_ops=[]}]\n', "'no_such_helper'")
        self.assertIn("第 1 个 call", message)

    def test_an_if_lib_any_method_call_is_a_facade_method_not_a_library_name(self):
        """带 `method` 的调用是 Phone 门面方法（另一套集合，属门面），不按库名校验。"""
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="if_lib_any",'
                     ' calls=[{method="tap", args=["我的"]}], ops=[], else_ops=[]}]\n')
        self.assertEqual([step.name for step in recipe.steps], ["a"])

    def test_a_name_inside_a_callback_argument_block_is_rejected(self):
        """实参里的再入块（`close_named(..., reopen={ops = [...]})`）点错名字，装载期就报（#1371）。"""
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="lib", name="close_named", args=[["行"]],'
            ' kwargs={reopen={ops=[{kind="lib", name="no_such_helper"}]}}}]\n',
            "'no_such_helper'")
        self.assertIn("第 1 个 op 的实参块 第 1 个 op", message)

    def test_a_name_inside_a_callback_argument_list_is_rejected(self):
        """`args` 里的实参块与 `kwargs` 里的同一规则：位置实参里藏着的错名装载期也报。"""
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="lib", name="close_named",'
            ' args=["行", {ops=[{kind="lib", name="no_such_helper"}]}]}]\n',
            "'no_such_helper'")
        self.assertIn("第 1 个 op 的实参块 第 1 个 op", message)

    def test_a_correct_name_inside_a_callback_argument_block_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="lib", name="close_named", args=[["行"]],'
                     ' kwargs={reopen={ops=[{kind="lib", name="close_named", args=[["行"]]}]}}}]\n')
        self.assertEqual([step.name for step in recipe.steps], ["a"])

    def test_names_from_the_exception_module_are_legal(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="lib", name="local_x"}]\n',
                "def local_x(p, rt):\n    pass\n")
        self.assertEqual([step.name for step in recipe.steps], ["a"])

    def test_a_name_without_a_close_match_reports_without_inventing_one(self):
        message = self._bad('[[segment]]\nname="a"\nops=[{kind="lib", name="zzzqqqxxx"}]\n',
                            "'zzzqqqxxx'")
        self.assertNotIn("相近的名字", message, "没有近似名时不该硬凑候选")
        self.assertTrue(message.endswith("也不是本机例外函数"), message)

    def test_the_hint_lists_three_close_names_at_most(self):
        """`difflib` 的默认 n 就是 3：候选更多时只列三个，且用「、」连起来。"""
        py_text = "".join(f"def abc{number}(p, rt):\n    pass\n" for number in range(1, 5))
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="lib", name="abc"}]\n', "'abc'", py_text=py_text)
        hint = message.split("相近的名字：", 1)[1]
        self.assertEqual(len(hint.split("、")), 3, hint)
        self.assertNotIn("XX", hint, "候选之间的分隔符只能是「、」")

    def test_a_dunder_defined_by_the_exception_module_is_not_a_legal_name(self):
        """`__` 开头的名字是模块私名：`exec` 把它写进命名空间，但数据点名它仍要在装载期报。"""
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="lib", name="__helper"}]\n', "'__helper'",
            py_text="def __helper(p, rt):\n    pass\n")
        self.assertIn("也不是本机例外函数", message)


class BindingLoadTimeTests(unittest.TestCase):
    """段内变量在装载期核对（#1373）：库名写错、绑的名字与库重名、引用未绑定的名字，都当场报。

    可见性只有两条：绑定的名字只在本段内，且只在绑定它的那条 op 之后；子分支里绑的出了分支看不见。"""

    def _bad(self, toml_text, *needles, py_text=None):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(catalog.SchemaError) as caught:
                _load_tmp(tmp, toml_text, py_text)
        message = str(caught.exception)
        for needle in needles:
            self.assertIn(needle, message)
        return message

    def test_a_misspelled_let_lib_is_rejected_and_suggests_the_close_one(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="let", name="pkg", lib="close_named_honr"}]\n',
                  "第 1 段「a」", "'close_named_honr'", "close_named_honor")

    def test_a_binding_that_shadows_a_library_name_is_rejected(self):
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="let", name="tap", lib="browser_settings"}]\n',
            "'tap'", "与库 / 本机实现同名")
        self.assertIn("换一个名字", message)

    def test_a_reference_to_an_unbound_name_is_rejected(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="lib", name="tap",'
                  ' args=[{expr="var", name="pkg"}]}]\n', "'pkg'", "第 1 个 op",
                  "；本段还没有绑定任何名字（先写一条 let）")

    def test_the_message_names_what_is_already_bound(self):
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="let", name="pkg", lib="browser_settings"},'
            '{kind="lib", name="tap", args=[{expr="var", name="ghost"}]}]\n', "'ghost'")
        self.assertIn("本段这一处已绑定的是 ['pkg']", message)

    def test_every_reference_is_checked_after_a_bound_one(self):
        """同一 op 里前一个引用已绑过，不能连同这一 op 后面那个未绑的一起放过。"""
        self._bad('[[segment]]\nname="a"\nops=[{kind="let", name="pkg", lib="browser_settings"},'
                  '{kind="lib", name="tap", args=[{expr="var", name="pkg"},'
                  ' {expr="var", name="ghost"}]}]\n', "'ghost'")

    def test_a_reference_nested_deeper_in_a_table_is_rejected(self):
        """变量引用不只在实参表顶层：套在 kwargs 里的表一样按引用核对。"""
        self._bad('[[segment]]\nname="a"\nops=[{kind="lib", name="tap",'
                  ' kwargs={outer={expr="var", name="pkg"}}}]\n', "'pkg'")

    def test_a_name_bound_inside_a_branch_is_visible_to_a_later_op_in_that_branch(self):
        """分支里先绑后用的名字属于这一支：父块不该把它当成自己的未绑定引用。"""
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="if_tap", text="X",'
                     ' ops=[{kind="let", name="pkg", lib="browser_settings"},'
                     '{kind="lib", name="tap", args=[{expr="var", name="pkg"}]}]}]\n')
        self.assertEqual([step.name for step in recipe.steps], ["a"])

    def test_the_same_holds_inside_an_else_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="if_tap", text="X", ops=[],'
                     ' else_ops=[{kind="let", name="pkg", lib="browser_settings"},'
                     '{kind="lib", name="tap", args=[{expr="var", name="pkg"}]}]}]\n')
        self.assertEqual([step.name for step in recipe.steps], ["a"])

    def test_a_nested_block_is_checked_for_unbound_names(self):
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="if_tap", text="X", ops=[{kind="lib",'
            ' name="tap", args=[{expr="var", name="ghost"}]}]}]\n', "'ghost'")
        self.assertIn("第 1 个 op 的 ops 第 1 个 op", message)

    def test_an_else_block_is_checked_for_unbound_names(self):
        message = self._bad(
            '[[segment]]\nname="a"\nops=[{kind="if_tap", text="X", ops=[],'
            ' else_ops=[{kind="lib", name="tap", args=[{expr="var", name="ghost"}]}]}]\n',
            "'ghost'")
        self.assertIn("第 1 个 op 的 else_ops 第 1 个 op", message)

    def test_a_name_bound_in_the_previous_segment_is_not_visible(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="let", name="pkg", lib="browser_settings"}]\n'
                  '[[segment]]\nname="b"\nops=[{kind="lib", name="tap",'
                  ' args=[{expr="var", name="pkg"}]}]\n',
                  "第 2 段「b」", "'pkg'")

    def test_a_name_bound_in_a_branch_is_not_visible_after_it(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="if_tap", text="X",'
                  ' ops=[{kind="let", name="pkg", lib="browser_settings"}]},'
                  '{kind="lib", name="tap", args=[{expr="var", name="pkg"}]}]\n',
                  "第 2 个 op", "'pkg'")

    def test_an_if_var_on_an_unbound_name_is_rejected(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="if_var", name="v", ops=[]}]\n', "'v'")

    def test_require_switches_on_an_unbound_name_is_rejected(self):
        self._bad('[[segment]]\nname="a"\nops=[{kind="require_switches",'
                  ' before={expr="var", name="switches"}, names=["X"], title="X"}]\n', "'switches'")

    def test_a_bound_name_is_visible_inside_a_nested_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="let", name="pkg", lib="browser_settings"},'
                     '{kind="if_tap", text="X", ops=[{kind="lib", name="tap",'
                     ' args=[{expr="var", name="pkg"}]}]}]\n')
        self.assertEqual([step.name for step in recipe.steps], ["a"])


class OnlySourceTests(unittest.TestCase):
    """`only` 两态：内联字面量，或 `only_code` 指向本机策略；两者都下发给 `p.off(only=…)`，都算「点名」。"""

    def test_inline_only_is_passed_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, calls = _load_tmp(
                tmp,
                '[[segment]]\nname="a"\nops=[{kind="off", only=["A","B"], page="p"}]\n',
            )
            recipe.run()
        self.assertEqual(calls, [("off", {"page": "p", "only": ["A", "B"]})])

    def test_only_code_resolves_to_local_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, calls = _load_tmp(
                tmp,
                '[[segment]]\nname="a"\nops=[{kind="off", only_code="targets", page="p"}]\n',
                "def targets(p, rt):\n    return ['A', 'B']\n",
            )
            recipe.run()
        self.assertEqual(calls, [("off", {"page": "p", "only": ["A", "B"]})])


SKIP_IN_SAFE_MODE = "skip_in_safe_mode"


def _call_name(call):
    """`p.off(...)` / `strategies.close_all(...)` 里的 `off` / `close_all`。"""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _py_close_form(call):
    """一次调用是不是整页关闭：`wide` / `named` / `None`（不是拨动）。

    `p.off()` 不带 `only`、任何 `close_all*`、以及名单实参为 `None` 的 `close_named*` 都是整页关闭。
    """
    name = _call_name(call)
    if name == "off":
        return "named" if "only" in {keyword.arg for keyword in call.keywords} else "wide"
    if name.startswith("close_all"):
        return "wide"
    if name.startswith("close_named"):
        argument = call.args[2] if len(call.args) > 2 else None
        return "wide" if isinstance(argument, ast.Constant) and argument.value is None else "named"
    return None


def _toml_close_form(op):
    """数据里一条 op 的拨动形态，与 `_py_close_form()` 同一套判据（`off` / `lib` 两种写法）。"""
    kind = op.get("kind")
    if kind == "off":
        return "named" if "only" in op or "only_code" in op else "wide"
    if kind == "close_all":
        return "wide"                                 # 解释器 op：点 UI 的「全部关闭」按钮
    if kind == "off_required":
        return "named"
    if kind == "lib":
        name = str(op.get("name", ""))
        if name.startswith("close_all"):
            return "wide"
        if name.startswith("close_named"):
            args = op.get("args") or []
            return "wide" if not args or args[0] is None else "named"
    return None


def page_wide_toml_units(path):
    """一份数据里「整段只做整页关闭」的段：[(段名, 首句 kind)]。

    只看段**顶层**的拨动：嵌在 `if_tap` / `if_entry` 里的不算（它不一定执行），段里还关着点名
    开关的也不算（那些段不能整段跳过）。
    """
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    units = []
    for segment in data.get("segment", []):
        ops = [op for op in segment.get("ops") or [] if isinstance(op, dict)]
        forms = [form for form in (_toml_close_form(op) for op in ops) if form]
        if forms and all(form == "wide" for form in forms):
            units.append((segment.get("name"), ops[0]["kind"] if ops else None))
    return units


def _starts_with_safe_mode_exit(fn):
    """函数体第一句（跳过 docstring）是不是安全模式跳过出口。

    两种写法都算：`rt.skip_in_safe_mode()`，以及「先判 safe_mode、命中就 skip」的守卫
    （PMX110 还要顺带挡别的型号，所以它的出口长成一条 if）。
    """
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return False
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
        return _call_name(first.value) == SKIP_IN_SAFE_MODE
    if isinstance(first, ast.If) and "safe_mode" in ast.unparse(first.test):
        return any(_call_name(call).endswith("skip")
                   for stmt in first.body for call in ast.walk(stmt) if isinstance(call, ast.Call))
    return False


def page_wide_py_units(path):
    """例外 `.py` 里「整段只做整页关闭」的模块级函数：[(函数名, 是否以跳过出口开头)]。"""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    units = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        forms = [form for form in (_py_close_form(call) for call in ast.walk(node)
                                   if isinstance(call, ast.Call)) if form]
        if forms and all(form == "wide" for form in forms):
            units.append((node.name, _starts_with_safe_mode_exit(node)))
    return units


class PageWideTests(unittest.TestCase):
    """UI「全部关闭」按钮单列一种动作，登记为 page-wide：安全模式下不点，普通模式点按钮并确认。"""

    TOML = '[[segment]]\nname="a"\nops=[{kind="close_all", page="p", button="全部关闭"}]\n'

    def test_clicks_the_button_when_not_in_safe_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, calls = _load_tmp(tmp, self.TOML)
            phone.safe_mode = False
            recipe.run()
        self.assertEqual(calls, [("tap", "全部关闭"), ("confirm", None)])

    def test_skips_in_safe_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, calls = _load_tmp(tmp, self.TOML)
            phone.safe_mode = True
            recipe.run()
        self.assertEqual(calls, [])
        self.assertIn("a", recipe.rt.skipped_steps)

    def test_page_wide_units_start_with_a_safe_mode_exit(self):
        """整段只做整页关闭的段 / 函数，安全模式下必须走跳过出口（#909、#947）。

        安全模式下 `off()` 只关点名的开关，整页关闭的单元一个都点不到；它再回读「必须全关」就
        稳定记成失败。出口写在第一句，是因为写在后面等于先翻页、再报「没关掉」，现场与结论都
        指向错的环节。数据与例外 `.py` 两侧都扫：判据是「顶层拨动全是整页关闭形态」——段里还
        关着点名开关的不算，那些段整段跳过会把正常该关的项也丢掉。
        """
        offenders, checked = [], 0
        for path in sorted((ROOT / "recipes").rglob("*.toml")):
            if path.name == "verified.toml":
                continue
            for name, first in page_wide_toml_units(path):
                checked += 1
                if first != SKIP_IN_SAFE_MODE:
                    offenders.append(f"{path.relative_to(ROOT)} 段「{name}」：首句是 {first!r}")
        for path in sorted((ROOT / "recipes").rglob("*.py")):
            for name, ok in page_wide_py_units(path):
                checked += 1
                if not ok:
                    offenders.append(f"{path.relative_to(ROOT)}:{name} 首句不是安全模式跳过出口")
        self.assertGreater(checked, 0, "一份整页关闭单元都没扫到：这条守卫空转")
        self.assertEqual(offenders, [], "整页关闭的段没在安全模式下按跳过收尾")


class CodeFallbackTests(unittest.TestCase):
    """`code = "<本机策略名>"` 兜底端到端可用（#1260）：例外 `.py` 里的普通函数由装载入口装进命名空间，
    段里 `code=` 真跑到它，`p` / `rt` 作参数传入。批次（#1262–#1267）靠这条路收表达不了的段。"""

    def test_segment_code_runs_the_exception_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp,
                '[[segment]]\nname="a"\ncode="local_x"\n',
                "def local_x(p, rt):\n    p.back(2)\n    rt.confirm(3)\n",
            )
            backs = []
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        self.assertEqual(backs, [2], "code= 没跑到例外函数，或 p / rt 没按参数传进去")
        self.assertEqual(recipe.rt.verified, 3, "例外函数里 rt.confirm 没记进这次执行")
        self.assertEqual(recipe.rt.results, [("a", "完成")])


class ScopedOpTests(unittest.TestCase):
    """`scoped` op：段内设一个页面属性，退出必须恢复到原值。

    属性归观测基座（`p.screen`），设与恢复打的是同一个对象——V1986A 的「阅图锁屏」段靠它：
    恢复没做到，退出后读屏一直算上 `com.android.systemui` 的状态栏文字，后续段会误判。"""

    TOML = ('[[segment]]\nname="a"\n'
            'ops=[{kind="scoped", systemui_text=true, ops=[{kind="back", n=1}]}]\n')

    def test_the_attribute_is_visible_inside_and_restored_afterwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            seen = []
            phone.back = lambda n=1: seen.append(phone.screen.systemui_text)
            before = phone.screen.systemui_text
            recipe.run()
        self.assertEqual(seen, [True], "段内没把 systemui_text 设上")
        self.assertEqual(phone.screen.systemui_text, before, "退出后没有恢复到原值")
        self.assertNotIn("systemui_text", vars(phone),
                         "恢复打到了 Phone 上而不是 Screen：属性已不在门面上，这句只是挂了个死属性")

    def test_a_failing_op_still_restores_the_attribute(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            before = phone.screen.systemui_text

            def boom(n=1):
                raise RuntimeError("段体失败")

            phone.back = boom
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        self.assertEqual(phone.screen.systemui_text, before)


class EnterOpTests(unittest.TestCase):
    """`enter` op（#1264）：数据里的 `p.enter(text, scrolls=…)`，与 `entry`（布尔入口）是两条路。"""

    def test_enter_passes_text_and_scrolls(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="enter", text="隐私", scrolls=4}]\n')
            seen = []
            phone.enter = lambda text, scrolls=6: seen.append((text, scrolls))
            recipe.run()
        self.assertEqual(seen, [("隐私", 4)])


class IfFocusOpTests(unittest.TestCase):
    """`if_focus` op（#1264）：按前台窗口判走哪一支，`match` 明写比法（equals / starts / contains）。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="if_focus", text="com.heytap.market/", match="starts",'
            ' ops=[{kind="back", n=2}], else_ops=[{kind="back", n=1}]}]\n')

    def _run(self, focus):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            backs = []
            phone.focus = lambda *a, **k: focus
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        return backs

    def test_starts_branch_is_taken_when_the_foreground_matches(self):
        self.assertEqual(self._run("com.heytap.market/com.heytap.market.mine.ui.X"), [2])

    def test_else_branch_is_taken_when_the_foreground_differs(self):
        self.assertEqual(self._run("com.heytap.browser/.BrowserActivity"), [1])

    def test_equals_does_not_match_a_longer_foreground(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="if_focus", text="p/.A", match="equals",'
                     ' ops=[{kind="back", n=2}], else_ops=[{kind="back", n=1}]}]\n')
            backs = []
            phone.focus = lambda *a, **k: "p/.A/.B"
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        self.assertEqual(backs, [1])


class IfTapOpTests(unittest.TestCase):
    """`if_tap` op（#1264）：`if p.tap(text, exact=…, scrolls=…): … else: …`，返回值决定走哪支。

    与 `lib` 里的 `tap` 不同：那个注入名失败就抛错（`TAP_STYLE` 的走法），这个按返回值分岔。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="if_tap", text="广告管理", exact=true, scrolls=0,'
            ' ops=[{kind="back", n=2}], else_ops=[{kind="back", n=1}]}]\n')

    def _run(self, hit):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            backs, taps = [], []
            phone.tap = lambda text, **kw: taps.append((text, kw)) or hit
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        return taps, backs

    def test_ops_branch_runs_when_the_tap_lands(self):
        taps, backs = self._run(True)
        self.assertEqual(backs, [2])
        self.assertEqual(taps, [("广告管理", {"exact": True, "scrolls": 0})])

    def test_else_branch_runs_when_the_tap_misses(self):
        self.assertEqual(self._run(False)[1], [1])


class TapIdOpTests(unittest.TestCase):
    """`tap_id` op（#1362）：按 u2 选择器（资源 id / 文字）直点一个控件，文字点不准的入口走它。

    读屏库在页面上找不到控件时抛 not-found：带 `miss_print` 的段打印一句就停（这一段算完成），
    `optional` 当没这回事继续走，都不写就照原样上抛（这一段按未完成收场）。"""

    class Reader:
        """只够这一段用的读屏替身：选择器交给 `select`，锁屏检查用的 shell 一律空输出。"""

        def __init__(self, select):
            self._select = select

        def __call__(self, **selectors):
            return self._select(selectors)

        def shell(self, command, timeout=None):
            return SimpleNamespace(output="", exit_code=0)

    def _tap(self, toml):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            seen, clicks = [], []

            class Target:
                def click(self):
                    clicks.append(True)

            phone.conn.reader = self.Reader(lambda selectors: seen.append(selectors) or Target())
            recipe.run()
        return seen, clicks, recipe.rt.results

    def test_resource_id_and_text_are_both_handed_to_the_selector(self):
        seen, clicks, results = self._tap(
            '[[segment]]\nname="a"\nops=[{kind="tap_id",'
            ' resource_id="com.x:id/gear", text="设置"}]\n')
        self.assertEqual(seen, [{"resourceId": "com.x:id/gear", "text": "设置"}])
        self.assertEqual(clicks, [True])
        self.assertEqual(results, [("a", "完成")])

    def test_a_text_only_selector_still_taps(self):
        seen, clicks, _results = self._tap(
            '[[segment]]\nname="a"\nops=[{kind="tap_id", text="我的"}]\n')
        self.assertEqual(seen, [{"text": "我的"}])
        self.assertEqual(clicks, [True])

    def test_a_missing_node_fails_the_segment_without_miss_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="tap_id", resource_id="com.x:id/none"}]\n')
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        self.assertEqual(recipe.rt.results, [("a", "未完成")])

    def test_miss_print_only_swallows_the_not_found_case(self):
        """只把「控件不在」收成停段：别的失败（读屏掉了、点按被拒）照旧上抛，这一段记未完成。"""
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="tap_id", resource_id="com.x:id/x",'
                     ' miss_print="  ✗ 没找到"}]\n')

            class Target:
                def click(self):
                    raise RuntimeError("读屏失败了")

            phone.conn.reader = self.Reader(lambda _selectors: Target())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                recipe.run()
        self.assertEqual(recipe.rt.results, [("a", "未完成")])
        self.assertNotIn("没找到", out.getvalue())

    def test_optional_keeps_going_when_the_node_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="tap_id", resource_id="com.x:id/none",'
                     ' optional=true}, {kind="back", n=2}]\n')
            backs = []
            phone.back = lambda n=1: backs.append(n)
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        self.assertEqual(backs, [2], "optional 点不到之后剩下的 op 要照常走完")
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_miss_print_ends_the_segment_without_touching_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="tap_id", resource_id="com.x:id/none",'
                     ' miss_print="  ✗ 没找到右上角的更多按钮"}, {kind="back", n=2}]\n')
            backs = []
            phone.back = lambda n=1: backs.append(n)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                recipe.run()
        self.assertEqual(backs, [], "点不到之后剩下的 op 不该再跑")
        self.assertEqual(recipe.rt.results, [("a", "完成")])
        self.assertIn("没找到右上角的更多按钮", out.getvalue())


class GestureOpTests(unittest.TestCase):
    """`gesture` op（#1362）：两端按屏宽 / 屏高的比例现算，下发一条 `input swipe`。"""

    def _commands(self, toml, size=(1080, 2340)):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            phone.W, phone.H = size
            shells = []
            phone.shell = lambda command, timeout=None: (shells.append(command), "")[1]
            recipe.run()
        return [command for command in shells if command.startswith("input swipe")]

    def test_a_vertical_swipe_takes_its_y_from_the_height(self):
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="gesture",'
                           ' start=[0.5, 0.3], end=[0.5, 0.7], ms=300}]\n'),
            ["input swipe 540 702 540 1638 300"])

    def test_a_horizontal_swipe_takes_its_x_from_the_width(self):
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="gesture",'
                           ' start=[0.25, 0.5], end=[0.75, 0.5], ms=250}]\n'),
            ["input swipe 270 1170 810 1170 250"])


class LetOpTests(unittest.TestCase):
    """`let` op（#1373）：把库助手的返回值绑成段内名字，后面的 op 用 `{expr = "var"}` 取它当实参。

    判据只看「库收到了什么」：绑定的名字本身不是词条、不是入口事实，看得见的只有那几次调用。"""

    def _run(self, toml, **fns):
        # 桩要在装载前装好：装载期核对点名的实现时读的是同一张 `LIBRARY`。
        seen = []
        patch_library(self, **{name: fn(seen) for name, fn in fns.items()})
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(tmp, toml)
            recipe.run()
        return seen

    def test_the_bound_value_reaches_the_next_call_as_a_positional_arg(self):
        toml = ('[[segment]]\nname="a"\nops=['
                '{kind="let", name="pkg", lib="pick_package"},'
                '{kind="lib", name="record", args=["标题", {expr="var", name="pkg"}]}]\n')
        seen = self._run(toml, pick_package=lambda seen: lambda p, rt: seen.append(("pick",)) or "com.x",
                         record=lambda seen: lambda p, rt, *a: seen.append(("record", a)))
        self.assertEqual(seen, [("pick",), ("record", ("标题", "com.x"))])

    def test_the_bound_value_reaches_a_keyword_arg(self):
        toml = ('[[segment]]\nname="a"\nops=['
                '{kind="let", name="pkg", lib="pick_package"},'
                '{kind="lib", name="record", kwargs={package={expr="var", name="pkg"}}}]\n')
        seen = self._run(toml, pick_package=lambda seen: lambda p, rt: "com.x",
                         record=lambda seen: lambda p, rt, **kw: seen.append(kw))
        self.assertEqual(seen, [{"package": "com.x"}])

    def test_a_later_let_rebinds_the_name_for_the_following_ops(self):
        toml = ('[[segment]]\nname="a"\nops=['
                '{kind="let", name="pkg", lib="pick_package"},'
                '{kind="lib", name="record", args=[{expr="var", name="pkg"}]},'
                '{kind="let", name="pkg", lib="pick_other"},'
                '{kind="lib", name="record", args=[{expr="var", name="pkg"}]}]\n')
        seen = self._run(toml, pick_package=lambda seen: lambda p, rt: "first",
                         pick_other=lambda seen: lambda p, rt: "second",
                         record=lambda seen: lambda p, rt, *a: seen.append(a[0]))
        self.assertEqual(seen, ["first", "second"])


class IfVarOpTests(unittest.TestCase):
    """`if_var` op（#1373）：按绑定的名字分岔。缺省与 `if_lib` 同档按真假值，`not_none = true` 时
    按「不是 None」分岔——后者才分得开「库返回了空值」与「库返回了 None」这两件事。"""

    def _branches(self, toml, value):
        patch_library(self, pick=lambda p, rt: value)
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            backs = []
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        return backs

    TOML = ('[[segment]]\nname="a"\nops=['
            '{kind="let", name="v", lib="pick"},'
            '{kind="if_var", name="v", ops=[{kind="back", n=2}], else_ops=[{kind="back", n=1}]}]\n')

    def test_the_true_branch_runs_for_a_truthy_value(self):
        self.assertEqual(self._branches(self.TOML, {"资讯服务": True}), [2])

    def test_the_else_branch_runs_for_a_falsey_value(self):
        self.assertEqual(self._branches(self.TOML, {}), [1])

    def test_the_else_branch_runs_for_none_by_truthiness(self):
        self.assertEqual(self._branches(self.TOML, None), [1])

    def test_not_none_takes_the_first_branch_for_an_empty_value(self):
        """空值不是 None：`if switches is not None:` 走的是「读到了」这一支。"""
        toml = ('[[segment]]\nname="a"\nops=['
                '{kind="let", name="v", lib="pick"},'
                '{kind="if_var", name="v", not_none=true, ops=[{kind="back", n=2}],'
                ' else_ops=[{kind="back", n=1}]}]\n')
        self.assertEqual(self._branches(toml, {}), [2])

    def test_not_none_takes_the_else_branch_for_none(self):
        toml = ('[[segment]]\nname="a"\nops=['
                '{kind="let", name="v", lib="pick"},'
                '{kind="if_var", name="v", not_none=true, ops=[{kind="back", n=2}],'
                ' else_ops=[{kind="back", n=1}]}]\n')
        self.assertEqual(self._branches(toml, None), [1])


class LibArgOpsBlockTests(unittest.TestCase):
    """`lib` 实参里的 `{ops = [...]}`（#1371）：一串 op 包成可调用对象传给库，由库决定什么时候调
    （`close_named(..., reopen=…)` 在关完、回读前重进一次页）。

    判据只看「库收到了什么、块什么时候跑」：解释器不预先求值，时序仍归库实现。"""

    TOML = ('[[segment]]\nname="a"\nops=['
            '{kind="lib", name="closer", args=["页"], kwargs={reopen={ops=['
            '{kind="enter", text="我的"},'
            '{kind="back", n=2}]}}}]\n')

    def _run(self, closer):
        seen = []

        def library_closer(p, rt, page, reopen=None):
            closer(seen, page, reopen)

        patch_library(self, closer=library_closer)
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            phone.enter = lambda text, **kw: seen.append(("enter", text))
            phone.back = lambda n=1: seen.append(("back", n))
            recipe.run()
        return seen

    def test_the_block_runs_only_when_the_library_calls_it(self):
        def closer(seen, page, reopen):
            seen.append(("closer", page, callable(reopen)))
            reopen()

        self.assertEqual(self._run(closer),
                         [("closer", "页", True), ("enter", "我的"), ("back", 2)])

    def test_a_library_that_ignores_the_block_leaves_it_unrun(self):
        """解释器不预先求值：没有回升调的段不该多出那几步调用（时序归库）。"""
        self.assertEqual(self._run(lambda seen, page, reopen: None), [])

    def test_a_bad_op_inside_the_block_is_rejected_at_load_time(self):
        toml = ('[[segment]]\nname="a"\nops=['
                '{kind="lib", name="close_named", kwargs={reopen={ops=[{kind="no_such_kind"}]}}}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(catalog.SchemaError) as caught:
                _load_tmp(tmp, toml)
        self.assertIn("实参块", str(caught.exception))


class RequireSwitchesOpTests(unittest.TestCase):
    """`require_switches` op（#1373）：把读到的开关表原样交给 `rt.require_switches(…)` 点名核对，
    缺一项就整段不动——与旧脚本里 `rt.require_switches(switches, ["X"], "页")` 同一条出口。"""

    TOML = ('[[segment]]\nname="a"\nops=['
            '{kind="let", name="switches", lib="pick"},'
            '{kind="require_switches", before={expr="var", name="switches"},'
            ' names=["资讯服务"], title="资讯服务"}]\n')

    def _run(self, switches):
        patch_library(self, pick=lambda p, rt: switches)
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            phone.page_evidence = lambda titles=(): "EVIDENCE"
            recipe.run()
        return recipe.rt.failed_steps

    def test_the_read_switches_are_checked_by_name(self):
        self.assertEqual(self._run({"资讯服务": True}), [])

    def test_a_missing_name_fails_the_segment_with_the_page_evidence(self):
        self.assertEqual(self._run({"别的开关": True}), ["a"])

    def test_an_empty_page_fails_the_segment(self):
        """名单为空也算没识别到（`rt.require_switches` 的既有判据）。"""
        self.assertEqual(self._run({}), ["a"])


class ReturnOutcomeTests(unittest.TestCase):
    """段的结局（#1264）：`return` 带 `value` 时整段按它记，`return_lib` 按库调用的返回值记。

    `run_step` 只在段体返回 `False` 时记「未完成」（`recipe_runtime` 的 `outcome is False`）；这三个
    出口是数据里唯一能表达「这一段没做成但不算异常」的地方。
    """

    def segment_results(self, toml, py_text=None):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(tmp, toml, py_text)
            recipe.run()
        return recipe.rt.results

    def test_return_false_marks_the_segment_failed(self):
        self.assertEqual(self.segment_results('[[segment]]\nname="a"\nops=[{kind="return", value=false}]\n'),
                         [("a", "未完成")])

    def test_return_without_a_value_ends_the_segment_as_done(self):
        self.assertEqual(self.segment_results('[[segment]]\nname="a"\nops=[{kind="return"}]\n'),
                         [("a", "完成")])

    def test_return_lib_takes_the_result_of_the_call(self):
        toml = '[[segment]]\nname="a"\nops=[{kind="return_lib", name="try_off", args=["x"]}]\n'
        scope = "def try_off(p, rt, name):\n    return ok\n"
        self.assertEqual(self.segment_results(toml, "ok = False\n" + scope), [("a", "未完成")])
        self.assertEqual(self.segment_results(toml, "ok = True\n" + scope), [("a", "完成")])


class PageOpTests(unittest.TestCase):
    """`page` op（#1265）：落点三段判据的声明式写法，`args` / `kwargs` 原样交给注入的 `page`。

    机型脚本里 `page("广告跟踪", SETTINGS, "OAIDActivity")` / `page("广告跟踪", activity=…)` 两处
    写法都出现过，位置实参与关键字实参必须逐条保住，所以照 `lib` 的形状收实参。"""

    def _run(self, toml):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(tmp, toml)
            seen = []
            recipe.rt.page = lambda *a, **k: seen.append((a, k))
            recipe.run()
        return seen

    def test_positional_args_are_forwarded(self):
        seen = self._run('[[segment]]\nname="a"\nops=[{kind="page", '
                         'args=["广告跟踪", "com.android.settings", "OAIDActivity"]}]\n')
        self.assertEqual(seen, [(("广告跟踪", "com.android.settings", "OAIDActivity"), {})])

    def test_keyword_args_are_forwarded(self):
        seen = self._run('[[segment]]\nname="a"\nops=[{kind="page", args=["广告跟踪"], '
                         'kwargs={activity="OAIDActivity"}}]\n')
        self.assertEqual(seen, [(("广告跟踪",), {"activity": "OAIDActivity"})])


class SkipOpTests(unittest.TestCase):
    """`skip` op（#1265）：按约定跳过这一段（`rt.skip`），结局记「跳过」而不是「未完成」。

    `skip_in_safe_mode` 只认安全模式；这一段在别的条件下也要跳过（如「本机没有这个入口」），
    文案是机型知识，交给数据。"""

    def test_skip_marks_the_segment_skipped_and_stops_the_ops(self):
        toml = '[[segment]]\nname="a"\nops=[{kind="skip", text="本机没有"}, {kind="back"}]\n'
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            backs = []
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        self.assertEqual(recipe.rt.results, [("a", "跳过")])
        self.assertEqual(recipe.rt.skipped_steps, ["a"])
        self.assertEqual(backs, [])         # 跳过之后不再做后面的 op


class FailOpTests(unittest.TestCase):
    """`fail` op（#1265）：这一段失败并带一句原因，进 `failed_steps`（与 `return false` 只改
    分段结局不同——失败段台账要能列出来，重试也按它定位）。"""

    def test_fail_marks_the_segment_failed_with_the_reason(self):
        toml = '[[segment]]\nname="a"\nops=[{kind="fail", text="设置里没走到"}, {kind="back"}]\n'
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            backs = []
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        self.assertEqual(recipe.rt.results, [("a", "未完成")])
        self.assertEqual(recipe.rt.failed_steps, ["a"])
        self.assertEqual(backs, [])

    def test_evidence_appends_the_page_snapshot(self):
        """`raise RuntimeError("…；" + p.page_evidence())`：现场只在真走到失败时读（#1267）。"""
        toml = '[[segment]]\nname="a"\nops=[{kind="fail", text="未进入；", evidence=true}]\n'
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            reads = []
            phone.page_evidence = lambda titles=(): reads.append(titles) or "EVIDENCE"
            recipe.run()
        self.assertEqual(reads, [()])
        self.assertEqual(recipe.rt.failed_steps, ["a"])


class RequireTapOpTests(unittest.TestCase):
    """`require_tap` op（#1265）：`require(p.tap(text, exact=…, scrolls=…), 文案)` 与 `if not p.tap(...): raise`
    是同一族（`require_go` / `require_tab` 的补齐）：点不到就按这一段失败，报错带文案、进失败段台账。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="require_tap", text="设置", exact=true, scrolls=0,'
            ' miss_print="没找到设置"}]\n')

    def test_tap_lands_and_the_segment_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            seen = []
            phone.tap = lambda text, **kw: seen.append((text, kw)) or True
            recipe.run()
        self.assertEqual(seen, [("设置", {"exact": True, "scrolls": 0})])
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_missing_tap_fails_with_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            phone.tap = lambda text, **kw: False
            recipe.run()
        self.assertEqual(recipe.rt.results, [("a", "未完成")])
        self.assertEqual(recipe.rt.failed_steps, ["a"])


class CloseListedOpTests(unittest.TestCase):
    """`close_listed` op（#1265）：「读回这一页的开关 → 只留点名的、页上真有的行 → 整表关」。

    PLZ110 / PMX110 的软件商店同形：`read_switches(page)` 读回，按候选名单过滤，空的按失败收尾，
    再 `close_named(names, page, snapshot=available)`。名单是机型知识，交给数据。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="close_listed", names=["甲", "乙", "丙"],'
            ' page="服务管理", miss_print="没识别到"}]\n')

    def test_keeps_present_rows_and_closes_them_with_the_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            opened = []
            saved = {"甲": True, "丙": True}
            patch_library(self, read_switches=lambda p, rt, page: dict(saved),
                          close_named=lambda p, rt, names, page, **kw: opened.append((names, page, kw)))
            recipe.run()
        self.assertEqual(opened, [(["甲", "丙"], "服务管理", {"snapshot": saved})])

    def test_selects_the_optional_variant_when_the_constant_is_set(self):
        """`close_listed` 按 CLOSE_NAMED_OPTIONAL 选档（#1268 修的生产 bug）。"""
        toml = '[const]\nCLOSE_NAMED_OPTIONAL = true\n' + self.TOML
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(tmp, toml)
            seen = []
            patch_library(self, read_switches=lambda p, rt, page: {"甲": True},
                          close_named_optional=lambda p, rt, names, page, **kw: seen.append(names))
            recipe.run()
        self.assertEqual(seen, [["甲"]])

    def test_empty_filter_fails_with_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            patch_library(self, read_switches=lambda p, rt, page: {},
                          close_named=lambda p, rt, *a, **k: None)
            recipe.run()
        self.assertEqual(recipe.rt.results, [("a", "未完成")])
        self.assertEqual(recipe.rt.failed_steps, ["a"])


class StartOpCommandTests(unittest.TestCase):
    """`start` op 的命令形状（#1473）：动作 / URI / 窗口模式 / 裸启动 / monkey 五种写法。

    判据是**下发到手机的 shell 串**：把数据里手写的 `am start` 迁进 op（#1478）要的是与迁移前
    逐字节相同的命令，所以这里逐字比字面量，不比「调了哪个方法」。不带形状键的 `start` 仍走
    `p.start`（落点校验那一条），见 `StartOpLandingTests`。
    """

    def _commands(self, toml):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            shells = []
            phone.shell = lambda command, timeout=None: (shells.append(command), "")[1]
            recipe.run()
        return shells

    def test_a_public_intent_launch_gets_the_clear_task_flag_by_default(self):
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="start",'
                           ' action="android.settings.SETTINGS"}]\n'),
            ["am start -f 0x10008000 -a android.settings.SETTINGS"])

    def test_a_page_launch_renders_the_same_command_as_the_handwritten_shell(self):
        """`-n` + 清栈：与数据里手写的 `shell` 串同一个形状，迁移才对得上。"""
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="start",'
                           ' pkg="com.android.settings", activity=".ad.AdServiceSettings",'
                           ' clear_task=true}]\n'),
            ["am start -f 0x10008000 -n com.android.settings/.ad.AdServiceSettings"])

    def test_a_bare_launch_drops_the_clear_task_flag(self):
        """裸启动：带清栈参数会立刻退出的页面（沿用 #165 的裁决），数据里写 `clear_task = false`。"""
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="start",'
                           ' pkg="com.heytap.browser",'
                           ' activity="com.heytap.browser.settings.component.BrowserPreferencesPage",'
                           ' clear_task=false}]\n'),
            ["am start -n com.heytap.browser/"
             "com.heytap.browser.settings.component.BrowserPreferencesPage"])

    def test_a_public_intent_names_its_package_when_the_page_is_not_exported(self):
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="start",'
                           ' action="oppo.intent.action.APP_SETTINGS", pkg="com.heytap.market"}]\n'),
            ["am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market"])

    def test_a_window_mode_flag_goes_right_after_am_start(self):
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="start",'
                           ' flags="--windowingMode 1", action="android.settings.SETTINGS"}]\n'),
            ["am start --windowingMode 1 -f 0x10008000 -a android.settings.SETTINGS"])

    def test_a_uri_is_quoted_so_the_device_shell_does_not_split_it(self):
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="start",'
                           ' action="android.intent.action.VIEW", data="gs://search/setting"}]\n'),
            ["am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"])

    def test_a_launcher_start_takes_the_monkey_route(self):
        self.assertEqual(
            self._commands('[[segment]]\nname="a"\nops=[{kind="start",'
                           ' pkg="com.android.browser", launcher=true}]\n'),
            ["monkey -p com.android.browser -c android.intent.category.LAUNCHER 1"])


class ShippedShellOpsTests(unittest.TestCase):
    """48 份数据里还剩哪些 raw `shell`（#1478）。

    拉起、强停与 monkey 都进了结构化 op；留下的只能是 op 表达不了的那几条。
    再加一条手写的 `am start` 就说明「同一批脚本被两套词法解释」又长回来了（ADR-0034 的病）。
    """

    KEPT = (
        "input tap 1098 240",          # 这版日历的「更多」对 uiautomator 点击不响应
        "input tap 769 647",           # 同上，「设置」
        "input keyevent KEYCODE_HOME",  # u2 的 press 走 jsonrpc，不是 input keyevent
        "input keyevent HOME",
        "input keyevent BACK",
        # 录脚本时写死的绝对坐标：`gesture` 按屏宽/屏高比例现算，真机上换回来的绝像素与原串不同
        "input swipe 600 2200 600 500 250",
        "input swipe 600 2200 600 500 250",
        "input swipe 600 2200 600 500 250",
    )

    @staticmethod
    def _walk(value):
        """op 出现在 `ops` / `else_ops` / 调用实参块里，一律递归收。"""
        if isinstance(value, dict):
            if isinstance(value.get("kind"), str):
                yield value
            for item in value.values():
                yield from ShippedShellOpsTests._walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from ShippedShellOpsTests._walk(item)

    def test_the_commands_that_stay_raw_shell_are_the_documented_ones(self):
        found = []
        for path in sorted((ROOT / "recipes").glob("*/*/*.toml")):
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            found += [op["command"] for op in self._walk(data) if op["kind"] == "shell"]
        self.assertEqual(sorted(found), sorted(self.KEPT))

    def test_no_catalog_data_launches_or_stops_through_a_shell_string(self):
        """`am start` / `am force-stop` / `monkey` 的形状只在 `tool/catalog/launch.py` 拼一次。"""
        leftovers = []
        for path in sorted((ROOT / "recipes").glob("*/*/*.toml")):
            for op in self._walk(tomllib.loads(path.read_text(encoding="utf-8"))):
                command = op.get("command", "")
                if op["kind"] == "shell" and (
                        "am start" in command or "am force-stop" in command
                        or command.startswith("monkey ")):
                    leftovers.append((path.relative_to(ROOT).as_posix(), command))
        self.assertEqual(leftovers, [])


class StartOpLandingTests(unittest.TestCase):
    """不带形状键的 `start` 仍是 `p.start`：落点校验（前台归属、弹窗）不能因为这次扩展丢掉。"""

    def test_a_plain_package_and_activity_still_goes_through_start(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="start", pkg="com.hionor.id",'
                ' activity=".oaid.ui.X", expect="广告"}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            seen = []
            phone.start = lambda *a, **kw: seen.append((a, kw))
            shells = []
            phone.shell = lambda command, timeout=None: shells.append(command)
            recipe.run()
        self.assertEqual(seen, [(("com.hionor.id", ".oaid.ui.X"),
                                 {"expect": "广告"})])
        self.assertEqual(shells, [])


class StartOrSkipOpTests(unittest.TestCase):
    """`start_or_skip` op（#1266）：数据里的 `start_or_skip(pkg, activity, dead_ends=…, reason=…)`。

    小米主题页是同一形状（5 台机型）：直达代理页，落点被系统转去商店 / 桌面时按跳过收尾。包名、
    Activity、落点名单与跳过理由是机型知识，交给数据；「落点不对就跳过」仍是库助手那一条。
    """

    TOML = ('[[segment]]\nname="a"\nops=[{kind="start_or_skip", pkg="com.example.theme",'
            ' activity=".Proxy", dead_ends=["com.example.market"], reason="打不开"}]\n')

    def test_forwards_the_landing_and_dead_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(tmp, self.TOML)
            seen = []
            recipe.rt.start_or_skip = lambda pkg, activity, **kw: seen.append((pkg, activity, kw))
            recipe.run()
        self.assertEqual(seen, [("com.example.theme", ".Proxy",
                                 {"dead_ends": ["com.example.market"], "reason": "打不开"})])


class SkipUnlessInstalledTests(unittest.TestCase):
    """`skip_unless_installed` op（沿用 #1266 的做法）：`if "package:" not in p.shell("pm path X"): print; return`。

    本机没装主题管理包时，后面的入口一个都走不到：打印一句、按「完成」收尾（旧脚本是 `return`，
    不是失败），后面的 op 不再做。"""
    from types import SimpleNamespace as _NS

    TOML = ('[[segment]]\nname="a"\nops=[{kind="skip_unless_installed",'
            ' command="pm path com.example.theme", contains="package:", text="  · 没有"},'
            ' {kind="back"}]\n')

    def _run(self, output):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            backs = []
            phone.back = lambda n=1: backs.append(n)
            phone.shell = lambda command, **kw: output
            recipe.run()
        return recipe, backs

    def test_missing_marker_prints_and_ends_the_segment(self):
        recipe, backs = self._run("")
        self.assertEqual(recipe.rt.results, [("a", "完成")])
        self.assertEqual(backs, [], "跳过之后不该再做后面的 op")

    def test_present_marker_continues(self):
        recipe, backs = self._run("package:/system/app/ThemeManager/ThemeManager.apk")
        self.assertEqual(recipe.rt.results, [("a", "完成")])
        self.assertEqual(backs, [1])


class AwaitPageOpTests(unittest.TestCase):
    """`await_page` op（#1266）：齿轮点完这一页可能还没画完，数据里显式等一次。"""

    def test_calls_await_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="await_page"}]\n')
            seen = []
            phone.await_page = lambda *a, **k: seen.append(a)
            recipe.run()
        self.assertEqual(seen, [()])


class OffRequiredOpTests(unittest.TestCase):
    """`off_required` op（#1266）：先跨翻页把这一页的开关读齐、点名断言都在，再点名关。

    4 台小米机型的主题设置同形：`before = {}; for _ in range(2): …p.switches(); if not
    p.scroll_more(): break` → `p.top(2)` → `require_switches(before, …, contains=True)` →
    `p.off(only=…, keep=…, page=…)`。点名与保留项是机型知识，交给数据。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="off_required", only=["每次联网时通知"],'
            ' keep=["自动更新"], page="主题·设置", contains=true}]\n')

    def test_collects_across_scrolls_then_toggles_only_and_keep(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, calls = _load_tmp(tmp, self.TOML)
            phone.switches = lambda root=None: [("每次联网时通知", True, (1, 2)),
                                                ("自动更新", True, (3, 4))]
            phone.scroll_more = lambda: False
            tops = []
            phone.top = lambda n=None: tops.append(n)
            recipe.run()
        self.assertEqual(tops, [2])
        self.assertEqual(calls, [("off", {"only": ["每次联网时通知"], "keep": ["自动更新"],
                                          "page": "主题·设置"})])
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_missing_target_fails_with_the_page_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, calls = _load_tmp(tmp, self.TOML)
            phone.switches = lambda root=None: []
            phone.scroll_more = lambda: False
            phone.top = lambda n=None: None
            phone.page_evidence = lambda titles=(): "EVIDENCE"
            recipe.run()
        self.assertEqual(calls, [])
        self.assertEqual(recipe.rt.results, [("a", "未完成")])
        self.assertEqual(recipe.rt.failed_steps, ["a"])


class RequireFailTests(unittest.TestCase):
    """`require_lib` 的 `fail` / `evidence`（#1266）：旧脚本 `if not gear(): raise RuntimeError(…；+ p.page_evidence())`。

    `require_lib` 原来按「打印现场再早退（完成）」收尾；`fail=true` 让它按这一段失败收尾、进失败段
    台账（重试按它定位），`evidence=true` 把当次页面现场接在文案后面。`require_tab` / `require_go` /
    `require_tap` 本来就 raise，只补 `evidence`。"""

    def _run(self, toml, **ns):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            phone.page_evidence = lambda titles=(): "EVIDENCE"
            recipe.namespace.update(ns)
            recipe.run()
        return recipe

    def test_require_lib_fail_raises_and_adds_the_evidence(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_lib", name="gear",'
                ' miss_print="主题设置入口没找到；", fail=true, evidence=true}]\n')
        recipe = self._run(toml, gear=lambda **kw: False)
        self.assertEqual(recipe.rt.results, [("a", "未完成")])
        self.assertEqual(recipe.rt.failed_steps, ["a"])

    def test_require_lib_without_fail_prints_and_ends_as_done(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_lib", name="gear", miss_print="…"}]\n')
        recipe = self._run(toml, gear=lambda **kw: False)
        self.assertEqual(recipe.rt.results, [("a", "完成")])
        self.assertEqual(recipe.rt.failed_steps, [])

    def test_require_tab_evidence_calls_page_evidence_on_miss(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_tab", name="我的",'
                ' miss_print="主题底部「我的」未找到；", evidence=true}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            evidence = []
            phone.tab = lambda name: False
            phone.page_evidence = lambda titles=(): evidence.append(titles) or "EVIDENCE"
            recipe.run()
        self.assertEqual(evidence, [()])
        self.assertEqual(recipe.rt.failed_steps, ["a"])


class IfFocusCaseInsensitiveTests(unittest.TestCase):
    """`if_focus` 的 `icontains`（#1266）：旧脚本 `if "basicmode" in p.focus().lower()`。

    浏览器拒绝协议后落到 basicmode 设置页，大小写不保证；小米族 8 份脚本都是先小写再比。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="if_focus", text="basicmode", match="icontains",'
            ' ops=[{kind="back", n=2}], else_ops=[{kind="back", n=1}]}]\n')

    def _run(self, focus):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            backs = []
            phone.focus = lambda *a, **k: focus
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        return backs

    def test_matches_in_any_case(self):
        self.assertEqual(self._run("com.android.browser/.BasicModeSettingActivity"), [2])

    def test_else_branch_when_not_found(self):
        self.assertEqual(self._run("com.android.browser/.BrowserActivity"), [1])


class IfSettingOpTests(unittest.TestCase):
    """`if_setting` op（#1267）：`if not p.setting("广告服务"): 深链兜底`。

    设置搜索搜不到就走兜底拉起，搜到了走另一支；两支里还会有 shell / sleep / off。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="if_setting", kw="广告服务", else_ops=[{kind="back", n=2}],'
            ' ops=[{kind="back", n=1}]}]\n')

    def _run(self, found):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            seen = []
            phone.setting = lambda kw, entry=None: seen.append((kw, entry)) or found
            backs = []
            phone.back = lambda n=1: backs.append(n)
            recipe.run()
        return seen, backs

    def test_present_takes_the_ops_branch(self):
        self.assertEqual(self._run(True), ([("广告服务", None)], [1]))

    def test_missing_takes_the_else_branch(self):
        self.assertEqual(self._run(False), ([("广告服务", None)], [2]))

    def test_entry_keyword_is_forwarded(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_setting", kw="广告服务", entry="隐私",'
                ' ops=[{kind="back", n=1}]}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            seen = []
            phone.setting = lambda kw, entry=None: seen.append((kw, entry)) or True
            phone.back = lambda n=1: None
            recipe.run()
        self.assertEqual(seen, [("广告服务", "隐私")])


class IfLibAnyOpTests(unittest.TestCase):
    """`if_lib_any` op（#1267）：`gear(toolbar_only=True) or gear()`。

    短路取第一个成功的助手：第一个成真就不再调第二个——旧脚本的 `or` 就是这个调用序列。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="if_lib_any", calls=[{name="gear", kwargs={toolbar_only=true}},'
            ' {name="gear"}], ops=[{kind="back", n=1}], else_ops=[{kind="back", n=2}]}]\n')

    def _run(self, first, second):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            seen = []
            phone.back = lambda n=1: seen.append(("back", n))
            patch_library(self, gear=lambda p, rt, **kw: seen.append(("gear", kw))
                          or (first if "toolbar_only" in kw else second))
            recipe.run()
        return seen

    def test_first_hit_short_circuits(self):
        self.assertEqual(self._run(True, True), [("gear", {"toolbar_only": True}), ("back", 1)])

    def test_second_hit_keeps_the_first_call(self):
        self.assertEqual(self._run(False, True),
                         [("gear", {"toolbar_only": True}), ("gear", {}), ("back", 1)])

    def test_both_miss_takes_the_else_branch(self):
        self.assertEqual(self._run(False, False),
                         [("gear", {"toolbar_only": True}), ("gear", {}), ("back", 2)])

    def test_a_page_method_can_stand_in_for_a_helper(self):
        """`tab_bot("我的") or p.tap("我的", exact=True, scrolls=0)`：短路链里可以混门面方法。"""
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_lib_any", calls=[{name="tab_bot", args=["我的"]},'
                ' {method="tap", args=["我的"], kwargs={exact=true, scrolls=0}}],'
                ' ops=[{kind="back", n=1}], else_ops=[{kind="back", n=2}]}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            seen = []
            phone.tap = lambda text, **kw: seen.append(("tap", text, kw)) or False
            phone.back = lambda n=1: seen.append(("back", n))
            patch_library(self, tab_bot=lambda p, rt, name: seen.append(("tab_bot", name)) or False)
            recipe.run()
        self.assertEqual(seen, [("tab_bot", "我的"), ("tap", "我的", {"exact": True, "scrolls": 0}),
                                ("back", 2)])


class RequireExpectOpTests(unittest.TestCase):
    """`require_expect` op（#1267）：`require(p.expect_page(…), …)` / `if not p.expect_page(…): raise`。

    实参逐条照原样下发（位置 / 关键字不合并），`calls` 里几个就短路 OR 几个；全落空按这一段失败。"""

    def _run(self, toml, results):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            seen = []
            phone.expect_page = lambda *a, **k: seen.append((a, k)) or results.pop(0)
            recipe.run()
        return seen

    def test_a_single_positional_timeout_is_forwarded_verbatim(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_expect", calls=[{args=["个性化广告推荐", 3]}],'
                ' miss_print="广告服务页没有打开"}]\n')
        self.assertEqual(self._run(toml, [True]), [(("个性化广告推荐", 3), {})])

    def test_any_call_short_circuits(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_expect", calls=['
                '{args=["每次联网时通知"], kwargs={timeout=3}}, {args=["自动更新"], kwargs={timeout=1}}],'
                ' miss_print="主题设置页没有打开；", evidence=true}]\n')
        self.assertEqual(self._run(toml, [False, True]),
                         [(("每次联网时通知",), {"timeout": 3}), (("自动更新",), {"timeout": 1})])

    def test_all_miss_fails_the_segment_with_the_evidence(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_expect", calls=[{args=["X"]}],'
                ' miss_print="主题设置页没有打开；", evidence=true}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            phone.expect_page = lambda *a, **k: False
            phone.page_evidence = lambda titles=(): "EVIDENCE"
            recipe.run()
        self.assertEqual(recipe.rt.failed_steps, ["a"])


class AtFocusTests(unittest.TestCase):
    """失败文案尾巴的另一种现场（#1267）：`f"…；停在 {p.focus()}"`。

    与 `evidence`（`p.page_evidence()`）并列，`at_focus=true` 时读一次前台接在文案后面——那次读
    也是脚本发出的调用，对拍要能对上。"""

    def test_require_lib_at_focus_reads_the_foreground(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_lib", name="browser_settings",'
                ' miss_print="浏览器设置入口没找到", fail=true, at_focus=true}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            reads = []
            phone.focus = lambda *a, **k: reads.append(1) or "com.android.browser/.Main"
            patch_library(self, browser_settings=lambda p, rt: False)
            recipe.run()
        self.assertEqual(reads, [1])
        self.assertEqual(recipe.rt.failed_steps, ["a"])

    def test_at_focus_reads_the_foreground_even_when_the_check_passes(self):
        """现场是 require 的实参：老脚本无论成败都先读一次前台，对拍里那条调用不能少。"""
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_lib", name="browser_settings",'
                ' miss_print="没找到", fail=true, at_focus=true}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            reads = []
            phone.focus = lambda *a, **k: reads.append(1) or "com.android.browser/.Main"
            patch_library(self, browser_settings=lambda p, rt: True)
            recipe.run()
        self.assertEqual(reads, [1])

    def test_require_tab_at_focus_reads_the_foreground_on_miss(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="require_tab", name="我的",'
                ' miss_print="没有「我的」", at_focus=true}]\n')
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml)
            reads = []
            phone.tab = lambda name: False
            phone.focus = lambda *a, **k: reads.append(1) or "x"
            recipe.run()
        self.assertEqual(reads, [1])


class IfFindKwargsTests(unittest.TestCase):
    """`if_find` 的 `edge_ok` / `nav`（#1267）：`if p.find("城市管理", exact=True, edge_ok="tab")`。

    天气的新版入口是底部标签，旧 `if_find` 只会下发 `exact`，把这两个关键字丢掉就与旧脚本不是
    同一条调用。"""

    TOML = ('[[segment]]\nname="a"\nops=[{kind="if_find", text="城市管理", exact=true, edge_ok="tab",'
            ' ops=[{kind="back", n=1}]}]\n')

    def test_edge_ok_is_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.TOML)
            seen = []
            phone.find = lambda text, **kw: seen.append((text, kw)) or True
            phone.back = lambda n=1: None
            recipe.run()
        self.assertEqual(seen, [("城市管理", {"exact": True, "edge_ok": "tab"})])


class NewOpValidatorTests(unittest.TestCase):
    """新 op 的封闭清单（沿用 #1266）：缺键、名单外的键都在装载期报。

    缺键 path 里少数几条已在 #1399 搬进 `catalog_family.CASES`（start_or_skip 缺 dead_ends、
    skip_unless_installed 缺 contains、off_required 缺 only、if_setting 缺 kw、let 缺 lib / name），
    这里只留「名单外的键」「取值非法」与 `OPS` 无 required 的 `check` 形态。"""

    def _bad(self, data, needle):
        with self.assertRaises(catalog.SchemaError) as caught:
            catalog.validate(data)
        self.assertIn(needle, str(caught.exception))

    def test_start_or_skip_rejects_an_unknown_key(self):
        op = {"kind": "start_or_skip", "pkg": "p", "activity": "a",
              "dead_ends": ["x"], "reason": "r", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_off_required_rejects_an_empty_only(self):
        op = {"kind": "off_required", "only": [], "page": "p"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "非空")

    def test_if_setting_rejects_an_unknown_key(self):
        op = {"kind": "if_setting", "kw": "x", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_if_lib_any_requires_a_non_empty_calls_list(self):
        op = {"kind": "if_lib_any", "calls": []}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "calls 必须是非空的数组")

    def test_if_lib_any_rejects_a_call_with_an_unknown_key(self):
        op = {"kind": "if_lib_any", "calls": [{"name": "gear", "surprise": 1}]}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_require_expect_requires_calls_and_the_message(self):
        self._bad({"segment": [{"name": "a", "ops": [{"kind": "require_expect",
                                                      "miss_print": "m"}]}]}, "缺 calls")
        self._bad({"segment": [{"name": "a", "ops": [{"kind": "require_expect",
                                                      "calls": [{"args": ["x"]}]}]}]}, "缺 miss_print")

    def test_require_expect_rejects_an_empty_calls_list(self):
        op = {"kind": "require_expect", "calls": [], "miss_print": "m"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "非空")

    def test_require_expect_rejects_an_unknown_key(self):
        op = {"kind": "require_expect", "calls": [{"args": ["x"]}], "miss_print": "m", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_if_find_accepts_the_scroll_and_nav_flags(self):
        op = {"kind": "if_find", "text": "x", "exact": True, "edge_ok": "tab", "nav": True, "ops": []}
        catalog.validate({"segment": [{"name": "a", "ops": [op]}]})

    def test_if_find_rejects_a_key_outside_its_list(self):
        op = {"kind": "if_find", "text": "x", "edge_ok": "tab", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_let_rejects_an_empty_name_and_an_unknown_key(self):
        self._bad({"segment": [{"name": "a", "ops": [{"kind": "let", "name": "", "lib": "x"}]}]},
                  "非空字符串")
        self._bad({"segment": [{"name": "a", "ops": [{"kind": "let", "name": "n", "lib": "x",
                                                      "surprise": 1}]}]}, "名单外的键")

    def test_if_var_rejects_a_non_boolean_not_none(self):
        self._bad({"segment": [{"name": "a", "ops": [{"kind": "if_var", "name": "v",
                                                      "not_none": "yes"}]}]}, "只能是 true / false")

    def test_require_switches_before_must_be_a_bound_name(self):
        op = {"kind": "require_switches", "before": {"资讯服务": True}, "names": ["资讯服务"],
              "title": "资讯服务"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, 'expr = "var"')

    def test_require_switches_requires_non_empty_names(self):
        op = {"kind": "require_switches", "before": {"expr": "var", "name": "v"}, "names": [],
              "title": "t"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "非空的字符串数组")


class NewOpProjectionTests(unittest.TestCase):
    """带「入口」的新 op 要同时进事实层（#1267）：漏一次，入口速查就没有这台机的设置搜索入口。"""

    DATA = {"segment": [{"name": "a", "ops": [
        {"kind": "if_setting", "kw": "广告服务", "else_ops": [
            {"kind": "shell", "command": "am start -n com.android.settings/.ad.AdServiceSettings"}]},
        {"kind": "if_lib_any", "calls": [{"name": "gear", "kwargs": {"toolbar_only": True}},
                                         {"name": "gear"}], "ops": []}]}]}

    def test_if_setting_and_if_lib_any_reach_the_lowered_source(self):
        import recipe_source
        lowered = recipe_source._catalog_src(self.DATA)
        self.assertIn('p.setting("广告服务")', lowered)
        self.assertIn('p.shell("am start -n com.android.settings/.ad.AdServiceSettings")', lowered)
        self.assertEqual([line for line in lowered.splitlines() if line.startswith("gear(")],
                         ["gear(p, rt)", "gear(p, rt)"])

    def test_if_setting_names_resolve_into_the_entry_facts(self):
        import recipe_source
        facts = recipe_source.scan_catalog(self.DATA)
        self.assertIn("p.setting", {call.name for call in facts.calls})


class WordsWalkTests(unittest.TestCase):
    """`words` 扫数据里的 op 表：没有段、段里没有 ops、kind 不在 `OPS` 里都跳过，跳过一个接着扫下一个。"""

    def test_data_without_segments_yields_nothing(self):
        self.assertEqual(catalog.words({}), [])

    def test_a_code_segment_has_no_ops_to_walk(self):
        self.assertEqual(catalog.words({"segment": [{"name": "a", "code": "x"}]}), [])

    def test_an_unknown_kind_is_skipped_and_the_rest_still_scanned(self):
        data = {"segment": [{"name": "a", "ops": [
            {"kind": "explode", "only": ["不认的字"]},
            {"kind": "off", "only": ["甲"], "page": "p"},
        ]}]}
        self.assertEqual(catalog.words(data), [("甲", "literal")])

    def test_a_string_valued_key_is_one_word_with_its_source(self):
        """字符串与列表两种写法都出词条：`only_code` 是策略名单，来源档是 `strategy`。"""
        data = {"segment": [{"name": "a", "ops": [
            {"kind": "off", "only_code": "system_ads", "page": "p"},
        ]}]}
        self.assertEqual(catalog.words(data), [("system_ads", "strategy")])


class OffRequiredProjectionTests(unittest.TestCase):
    """`off_required` 的名字要同时进词库与事实层（#1266）：漏一处，入口速查 / 词库就静默丢名字。

    这正是前三批连踩三次的坑（`close_listed`、`if_lib`…）：带开关名字的新 op 必须两处一起接。"""

    DATA = {"segment": [{"name": "a", "ops": [
        {"kind": "off_required", "only": ["每次联网时通知"], "keep": ["自动更新"], "page": "主题·设置"}]}]}

    def test_words_lists_only_and_keep_as_literals(self):
        self.assertEqual(sorted(catalog.words(self.DATA)),
                         [("每次联网时通知", "literal"), ("自动更新", "literal")])

    def test_facts_project_the_off_call(self):
        import recipe_source
        facts = recipe_source.scan_catalog(self.DATA)
        offs = [call for call in facts.calls if call.name == "p.off"]
        self.assertEqual(len(offs), 1, "off_required 没投影成 p.off，词库会漏掉这两个名")
        lowered = recipe_source._catalog_src(self.DATA)
        self.assertIn('only=["每次联网时通知"]', lowered)
        self.assertIn('keep=["自动更新"]', lowered)


class LibArgOpsProjectionTests(unittest.TestCase):
    """实参块里的 op 也要进事实层（#1371）：块里的 `enter` / `am start` 不投影，这台机的设置入口
    就从入口速查里静默消失（重进页的那一段恰恰是入口所在）。"""

    DATA = {"segment": [{"name": "a", "ops": [
        {"kind": "lib", "name": "close_named", "args": [["个性化推荐设置"], "主题·个性化推荐"],
         "kwargs": {"reopen": {"ops": [
             {"kind": "start", "pkg": "com.heytap.themestore"},
             {"kind": "enter", "text": "我的"},
             {"kind": "shell", "command": "am start -n com.heytap.themestore/.Setting"}]}}}]}]}

    def test_the_block_reaches_the_lowered_source(self):
        import recipe_source
        lowered = recipe_source._catalog_src(self.DATA)
        self.assertIn('p.start("com.heytap.themestore")', lowered)
        self.assertIn('p.enter("我的")', lowered)
        self.assertIn('p.shell("am start -n com.heytap.themestore/.Setting")', lowered)

    def test_the_block_names_resolve_into_the_entry_facts(self):
        import recipe_source
        names = {call.name for call in recipe_source.scan_catalog(self.DATA).calls}
        self.assertIn("p.enter", names)
        self.assertIn("p.shell", names)


class SettlePageVocabularyTests(unittest.TestCase):
    """`settle_page` 进数据词汇（#1371，ADR-0040 记修订）。

    判据是「只读前台 / 页面树的面才留在 `__all__` 外」：它自己走读屏与等待，与 `wait_page` 同档，
    所以数据该能点名。阅读那一段就靠它：自绘开关页在点下一行之前要等版面定下来。"""

    TOML = ('[[segment]]\nname="a"\nops=['
            '{kind="lib", name="settle_page", args=["com.hihonor.dz.reader", "广告推荐服务"]}]\n')

    def test_the_data_name_resolves_to_the_library_implementation(self):
        import recipe_lib
        self.assertIn("settle_page", recipe_lib.LIBRARY)
        self.assertNotIn("settle_page", recipe_lib.HELPERS)

    def test_the_loader_accepts_the_data_name(self):
        """装载期按 `LIBRARY` 核对点名的实现：不在词汇里就报错，等不到真机。"""
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(tmp, self.TOML)
            self.assertEqual([step.name for step in recipe.steps], ["a"])

    def test_a_segment_reaches_settle_page_with_its_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(tmp, self.TOML)
            seen = []
            patch_library(self, settle_page=lambda p, rt, package, *markers: seen.append((package, markers)))
            recipe.run()
        self.assertEqual(seen, [("com.hihonor.dz.reader", ("广告推荐服务",))])


class LetOpProjectionTests(unittest.TestCase):
    """`let` 的实现在事实层里照 `lib` 一样投影（#1373）：入口归属靠库实现下扫，漏一次这台机就从入口
    速查里消失；绑定的名字本身不是词条也不是入口，`require_switches` 也不产出事实。"""

    DATA = {"segment": [{"name": "a", "ops": [
        {"kind": "let", "name": "pkg", "lib": "browser_settings"},
        {"kind": "require_switches", "before": {"expr": "var", "name": "pkg"},
         "names": ["资讯服务"], "title": "资讯服务"}]}]}

    def test_the_lib_call_is_projected_and_the_binding_is_not(self):
        import recipe_source
        self.assertEqual([call.name for call in recipe_source.scan_catalog(self.DATA).calls],
                         ["browser_settings"])


def _load_model(relative_path, only):
    """装载 `recipes/` 下的一份数据、只跑点名的段；库实现由调用方用 `patch_library` 换成桩。"""
    clock = fixtures.Clock()
    phone = fixtures.fake_phone(clock=clock, fast_mod=fast)
    return catalog.load(ROOT / relative_path, phone, only=only, clock=clock), phone


class BrowserRecsBindingTests(unittest.TestCase):
    """WKL-AN20「浏览器推荐」转数据（#1373）：`browser_settings` 的返回值当后面三次关单的实参。

    空假页面上这三步一步都走不到（`close_named_honor` 先要认页），对拍对它是盲的——这里逐条断言
    库收到的实参：绑定丢了、上一次库、只绑不传，三种都会红。"""

    PATH = "recipes/honor/WKL-AN20/WKL-AN20.toml"

    def _run(self, package):
        seen = []
        patch_library(
            self, browser_settings=lambda p, rt: seen.append(("browser_settings",)) or package,
            tap=lambda p, rt, text, **kw: seen.append(("tap", text, kw)),
            close_named_honor=lambda p, rt, names, title, pkg, marker, **kw:
                seen.append(("close", names, title, pkg, marker)))
        recipe, phone = _load_model(self.PATH, ["浏览器推荐"])
        phone.back = lambda n=1: seen.append(("back", n))
        # 这份数据的 guard 钩子先核对型号与系统版本，对不上整份跳过。
        phone.shell = lambda command, timeout=None: shell_result(
            {"getprop ro.product.model": "WKL-AN20",
             "getprop ro.build.display.id": "WKL-AN20 11.0.0.111(SP7C00E110R101P7)"}.get(command, ""), 0)
        recipe.run()
        return seen

    def test_the_package_comes_from_the_one_browser_settings_call(self):
        seen = self._run("com.hihonor.browser")
        self.assertEqual([item for item in seen if item[0] == "browser_settings"],
                         [("browser_settings",)])
        self.assertEqual([item[3] for item in seen if item[0] == "close"],
                         ["com.hihonor.browser"] * 3)

    def test_the_three_sections_are_closed_in_order(self):
        seen = self._run("com.hihonor.browser")
        self.assertEqual([item[2] for item in seen if item[0] == "close"],
                         ["浏览器·消息通知", "浏览器·个性化推荐", "浏览器·互动广告"])
        self.assertEqual([item[1] for item in seen if item[0] == "tap"],
                         ["消息通知", "隐私管理", "个性化推荐", "互动广告管理"])

    def test_the_bound_package_keeps_whatever_the_helper_returned(self):
        """绑定的是库的返回值本身，不看真假：换了包名（或空值）也照样传下去。"""
        seen = self._run("")
        self.assertEqual([item[3] for item in seen if item[0] == "close"], [""] * 3)


class AssistantAdviceBindingTests(unittest.TestCase):
    """PLP120「小布建议」转数据（#1373）：`open_switch_page` 的返回值决定走哪一支，两支都提前收段。

    ColorOS 17 的入口是「资讯服务」，旧版本是「内容资讯」；库读不到时返回 `None`，读到了返回
    `{标题: 状态}`（可能是空表）。`if_lib` 的假值分岔会把空表与 `None` 并成一档，这里按
    「不是 None」分岔，两种返回值各断言一次。"""

    PATH = "recipes/oppo/PLP120/PLP120.toml"

    def _run(self, switches):
        seen = []
        patch_library(
            self, enter_settings=lambda p, rt, *a: seen.append(("enter_settings", a)),
            open_switch_page=lambda p, rt, name, titles, package:
                seen.append(("open", name, titles, package)) or switches)
        recipe, phone = _load_model(self.PATH, ["小布建议"])
        phone.off = lambda **kw: seen.append(("off", kw))
        # 落点校验归 `Runtime.page()`（另有 PageOpTests），这里只断言它仍被要求做一次。
        with patch.object(recipe_runtime.Runtime, "page",
                          lambda self, *a: seen.append(("page", a))):
            recipe.run()
        return seen, recipe.rt

    def test_the_first_entry_wins_when_it_returns_switches(self):
        seen, rt = self._run({"资讯服务": True})
        self.assertEqual([item for item in seen if item[0] == "page"],
                         [("page", ("小布建议", "com.android.settings"))])
        self.assertEqual([item[1] for item in seen if item[0] == "open"], ["资讯服务"])
        self.assertEqual([item[1] for item in seen if item[0] == "off"],
                         [{"only": ["资讯服务"], "page": "小布建议·资讯服务"}])
        self.assertEqual(rt.results, [("小布建议", "完成")])

    def test_an_empty_read_still_counts_as_landing_on_the_page(self):
        """空表不是 None：`if switches is not None:` 走「读到了」那一支，随后的点名核对按失败收场。"""
        seen, rt = self._run({})
        self.assertEqual([item[1] for item in seen if item[0] == "open"], ["资讯服务"])
        self.assertEqual(rt.results, [("小布建议", "未完成")])

    def test_none_falls_through_to_the_second_entry(self):
        seen, rt = self._run(None)
        self.assertEqual([item[1] for item in seen if item[0] == "open"], ["资讯服务", "内容资讯"])
        self.assertEqual([item[2] for item in seen if item[0] == "open"],
                         ["资讯服务", ["内容资讯", "资讯服务"]])
        self.assertEqual(rt.results, [("小布建议", "未完成")])


class GameCenterBindingTests(unittest.TestCase):
    """PLP120「游戏中心」转数据（#1373）：`read_on_page` 等开关画出来再读，读数交给点名核对；
    `game_settings_direct` 的真假决定走不走「我的 → 设置」，也决定最后退回几次。"""

    PATH = "recipes/oppo/PLP120/PLP120.toml"

    def _run(self, direct):
        seen = []
        patch_library(
            self, game_settings_direct=lambda p, rt: seen.append(("direct",)) or direct,
            game_settings_via_mine=lambda p, rt: seen.append(("via_mine",)),
            read_on_page=lambda p, rt, titles, package:
                seen.append(("read", titles, package)) or {"个性化推荐": True})
        recipe, phone = _load_model(self.PATH, ["游戏中心"])
        phone.enter = lambda text, scrolls=6: seen.append(("enter", text, scrolls))
        phone.off = lambda **kw: seen.append(("off", kw))
        phone.back = lambda n=1: seen.append(("back", n))
        recipe.run()
        return seen

    def test_the_direct_landing_skips_the_mine_route_and_goes_back_three(self):
        seen = self._run(True)
        self.assertNotIn("via_mine", [item[0] for item in seen])  # 直达成功就不走「我的 → 设置」
        self.assertEqual([item for item in seen if item[0] == "read"],
                         [("read", "个性化推荐管理", "com.nearme.gamecenter")])
        self.assertEqual(seen[-1], ("back", 3))

    def test_a_failed_direct_landing_takes_the_mine_route_and_goes_back_four(self):
        seen = self._run(False)
        self.assertIn(("via_mine",), seen)
        self.assertEqual(seen[-1], ("back", 4))

    def test_the_read_switches_are_checked_before_closing(self):
        seen = self._run(True)
        self.assertEqual([item for item in seen if item[0] in ("read", "off")],
                         [("read", "个性化推荐管理", "com.nearme.gamecenter"),
                          ("off", {"only": ["个性化推荐"], "page": "游戏中心·个性化推荐"})])


class NameSourceBaselineTests(unittest.TestCase):
    """词库按名单来源记：数据里每一条要关的 / 要留的词都能说出自己是字面量还是本机策略。

    单向基线：转换后的数据至少要覆盖旧脚本里写下的全部字面量（丢一个词条就会红）。
    """

    def test_data_literals_cover_the_script_literals(self):
        """单向基线：旧脚本里写下的字面量，数据一条都不能丢。

        数据可能比脚本多（`系统广告` 的名单原本住在注入的段体 `system_ads_chain` 里、脚本正文看不见，
        数据化后内联进来），所以判据是「脚本 ⊆ 数据」而不是相等。
        """
        from tomllib import loads
        data_words = {text for text, source in catalog.words(loads((ROOT / DATA).read_text(encoding="utf-8")))
                      if source == "literal"}
        self.assertLessEqual(_script_off_literals(ROOT / SCRIPT), data_words)


def _script_off_literals(path):
    """从旧脚本里取 `p.off(only=…)` / `keep=…` 的字符串字面量（独立来源，不读 TOML）。"""
    found = set()
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "off"):
            continue
        for keyword in node.keywords:
            if keyword.arg in ("only", "keep") and isinstance(keyword.value, (ast.List, ast.Tuple)):
                for element in keyword.value.elts:
                    if isinstance(element, ast.Constant) and isinstance(element.value, str):
                        found.add(element.value)
    return found


class ReaderTests(unittest.TestCase):
    """#1270：只扫 `recipe*.py` 的消费者（词库 / 入口速查 / 台账 / 类型检查）也认 `<型号>.toml`。

    判据是「同一台机的 `.py` 与 `.toml` 投影出同一份词库与入口」：把 V1986A 的两份分别放进临时
    目录，`.py` 一份、`.toml` 一份，各自 `vocab.scan` 与 `entries.used_by`，结果必须相同。这证明
    转成数据之后脚本不会从这些生成物里消失（否则批次验收「词条总数不下降 / 入口速查不变」无从谈起）。
    """



    def test_scan_dir_handles_a_toml_model(self):
        import recipe_source
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "vivo" / "V1986A"
            model_dir.mkdir(parents=True)
            (model_dir / "V1986A.toml").write_text((ROOT / DATA).read_text(encoding="utf-8"), encoding="utf-8")
            facts = recipe_source.scan_dir(tmp)
            self.assertEqual(list(facts), ["vivo/V1986A/V1986A.toml"])
            self.assertTrue(any(call.name == "p.off" for call in facts["vivo/V1986A/V1986A.toml"].calls))


    def test_recipe_meta_reads_toml(self):
        import recipe_meta
        meta = recipe_meta.recipe_meta(str(ROOT / DATA))
        self.assertEqual(meta["build"], "PD1986_A_8")
        self.assertEqual(meta["models"], ["V1986A"])
        self.assertEqual(meta["steps"], ["系统广告", "阅图锁屏", "应用商店"])

    def test_typecheck_validates_toml_data(self):
        from devtools import typecheck_recipes
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.toml"
            good.write_text((ROOT / DATA).read_text(encoding="utf-8"), encoding="utf-8")
            self.assertFalse(typecheck_recipes._check_catalog(str(good))[0])
            bad = Path(tmp) / "bad.toml"
            bad.write_text('model = "x"\n[[segment]]\nname = "s"\nops = [{kind = "nope"}]\n', encoding="utf-8")
            self.assertTrue(typecheck_recipes._check_catalog(str(bad))[0])

    def test_every_toml_lib_call_resolves_to_an_implementation(self):
        """`.toml` 里每个 lib / require_lib 名都要在 `LIBRARY`（数据可点名的集合）里（入口归属的根因守护）。

        数据显式点名实现，名字解析不到时入口速查会把这台机从「用过的机型」里静默删掉
        （`com.iqoo.secure` / `com.vivo.weather` 那次）。`let` 点名的实现写在 `lib` 上，同一个集合。
        覆盖全部已转型号，不是抽查一份。"""
        import tomllib
        import recipe_source

        library = set(recipe_source.library_sources())

        def lib_names(ops):
            for op in ops:
                if op.get("kind") in ("lib", "require_lib") and "name" in op:
                    yield op["name"]
                elif op.get("kind") == "let" and "lib" in op:
                    yield op["lib"]
                yield from lib_names(op.get("ops") or [])
                yield from lib_names(op.get("else_ops") or [])

        checked = 0
        for toml in sorted((ROOT / "recipes").rglob("*.toml")):
            data = tomllib.loads(toml.read_text(encoding="utf-8"))
            segments = data.get("segment")
            if not segments:          # recipes/verified.toml 这类非页面树文件
                continue
            wanted = {name for seg in segments for name in lib_names(seg.get("ops") or [])}
            if not wanted:
                continue
            checked += 1
            missing = wanted - library
            self.assertEqual(missing, set(),
                             f"{toml.relative_to(ROOT)}：这些 lib 名没解析到实现 {sorted(missing)}")
        self.assertGreater(checked, 0, "一份带 lib 的 .toml 都没扫到：发现口径坏了")

    def test_entry_doc_matches_generator(self):
        """提交的 `docs/清单/入口速查.md` 必须与生成器逐字一致（入口归属变化的产物守护，#1263）。"""
        import entries
        doc = (ROOT / "docs" / "清单" / "入口速查.md").read_text(encoding="utf-8")
        self.assertEqual(doc, entries.markdown(str(ROOT / "recipes")),
                         "改了 tool/entries.py 或机型脚本后重新生成：python3 tool/entries.py > docs/清单/入口速查.md")


class GenTests(unittest.TestCase):
    """#1270：`adapt gen` 默认产出的是页面树骨架，起点形状就对（能过校验器）。"""

    def test_catalog_draft_is_valid_schema(self):
        import adapt
        from tomllib import loads
        src = adapt.render_catalog_draft(
            [("com.bbk.appstore", "我的>设置>关于", ["个性化推荐", "服务管理"])],
            model="TEST01", build="OS1", source="探路-TEST01.tsv")
        data = loads(src)
        catalog.validate(data)
        self.assertEqual(data["models"], ["TEST01"])
        self.assertEqual([s["name"] for s in data["segment"]], ["com.bbk.appstore · 我的>设置>关于"])
        kinds = [op["kind"] for op in data["segment"][0]["ops"]]
        self.assertEqual(kinds, ["start", "entry", "entry", "off"])


class OpKindDeclarationTests(unittest.TestCase):
    """#1357：一种 op 的词汇是 `OPS` 里的一条记录，新增 kind 漏登记即红（沿用 #1354 的分区）。

    允许键、必填键、子 op 键、不产出事实、抽词条的键都在同一条 `OpSpec` 上，代码里剩下的三张
    名单（`_HANDLERS` 处理器、事实层降级分支、装载期点名核对）与声明之间没有任何守卫——漏 handler
    要等真机走到那条 op 才 `KeyError`，漏事实层登记会让词库与入口速查静默少一条记录。七条用例各守
    一个分区，红了就能定位是哪一处漂了。判据只看声明与 `scan_catalog` 的公开行为，不 import 投影
    函数的私有分支。
    """

    # 事实类条件分支（if_find / if_entry / if_focus / if_tap）靠子 op 产出事实；给一个稳定产出
    # `p.shell` 的子 op，占位 op 才判得出「这个 kind 会不会产出事实」。
    _SUB_OP = {"kind": "shell", "command": "x"}

    def _probe_value(self, key):
        """按允许键的键名造值：不给每种 kind 写「最小合法 op」表（那又是一份会漂的名单）。

        新键需要新类型时测试会红（该 kind 落到不产出事实那一侧），不是静默。"""
        if key in ("name", "only_code"):
            return "x"                      # 合法标识符：lib 名 / 本机策略名
        if key == "calls":
            return [{"name": "x"}]          # if_lib_any 的短路调用至少要一个助手名
        if key in ("ops", "else_ops"):
            return [dict(self._SUB_OP)]
        if key in ("args", "entries", "names", "keep", "only"):
            return ["x"]                    # 列表型键：gated 的 entries / close_listed 的 names 要非空
        return "x"

    def probe_op(self, kind):
        """一个 kind 的占位 op：键取 `OP_KEYS[kind]`，值按 `_probe_value` 给。"""
        from catalog.schema import OP_KEYS
        op = {"kind": kind}
        for key in OP_KEYS[kind]:
            if key == "kind":
                continue
            op[key] = self._probe_value(key)
        return op

    def _data(self, kind):
        return {"segment": [{"name": "a", "ops": [self.probe_op(kind)]}]}

    def test_every_declared_kind_has_a_handler(self):
        """`OP_KEYS` 与 `_HANDLERS` 的键集合逐项相等：加一种 op 只改一处，另一处静默漏掉。

        旧树也绿（基线两张表本来就相等），守的是不回退：任一侧新增 kind 漏改另一侧即红。"""
        from catalog.schema import OP_KEYS
        import catalog.interpreter as interpreter
        self.assertTrue(OP_KEYS, "OP_KEYS 是空的，这条守卫会空转")
        self.assertEqual(set(OP_KEYS), set(interpreter._HANDLERS),
                         "OP_KEYS 与 _HANDLERS 必须逐项相等：漏 handler 要等真机走到那条 op 才 KeyError")

    def test_nested_keys_are_exactly_the_sub_op_keys(self):
        """`nested` 必须等于「允许键里出现的 ops / else_ops」：写漏一处，那个键里的子 op 就不受校验。"""
        from catalog.schema import OPS
        self.assertTrue(OPS, "OPS 是空的，这条守卫会空转")
        for kind, spec in sorted(OPS.items()):
            with self.subTest(kind):
                self.assertEqual(set(spec.nested), spec.keys & {"ops", "else_ops"},
                                 f"{kind} 的 nested 与允许键不一致：子 op 列表不会被递归校验")

    def test_word_keys_are_allowed_keys(self):
        """抽词条的键必须在这个 op 的允许键里：声明一条读不到的键，词库会静默少词。"""
        from catalog.schema import OPS
        self.assertTrue(OPS, "OPS 是空的，这条守卫会空转")
        for kind, spec in sorted(OPS.items()):
            with self.subTest(kind):
                self.assertLessEqual({key for key, _source in spec.word_keys}, spec.keys,
                                     f"{kind} 的 word_keys 里有允许键之外的键")

    def test_required_keys_are_allowed_keys(self):
        """#1360：必填键必须在这个 op 的允许键里。

        落到名单外时这条 op 无论如何都写不对：给了那个键是「出现名单外的键」，不给是「缺那个键」。
        `nested` 与 `word_keys` 两条只管另外两个字段，`probe_op` 又只按 `keys` 造占位 op，都碰不到
        这一格。"""
        from catalog.schema import OPS
        self.assertTrue(OPS, "OPS 是空的，这条守卫会空转")
        for kind, spec in sorted(OPS.items()):
            with self.subTest(kind):
                self.assertLessEqual(set(spec.required), spec.keys,
                                     f"{kind} 的 required 里有允许键之外的键")

    def test_unregistered_kind_raises(self):
        """未登记的 kind 让投影函数报错，不静默丢数据。

        这条才把 `_catalog_src` 末尾的 `else: raise` 钉住：改回静默跳过它立刻红（基线就是这么
        穿透的，那 20 种 kind 靠隐式落到循环末尾什么也不做）。文案要点名这个 kind 并给出两条出路。"""
        import recipe_source
        data = {"segment": [{"name": "a", "ops": [{"kind": "not_a_registered_kind"}]}]}
        with self.assertRaises(RuntimeError) as caught:
            recipe_source.scan_catalog(data)
        self.assertIn("not_a_registered_kind", str(caught.exception))
        self.assertIn("NO_FACT_KINDS", str(caught.exception))

    def test_every_kind_projects_without_raising(self):
        """逐 kind 造占位 op 喂事实层都不抛。

        旧树也绿——基线里没登记事实层的 kind 靠末尾无 `else` 静默穿透，照样不抛；守的是不回退：
        新增 kind 若既没降级分支也不在 `NO_FACT_KINDS`，这条会红。把 `else: raise` 本身钉住的是
        `test_unregistered_kind_raises`。"""
        from catalog.schema import OP_KINDS
        import recipe_source
        for kind in sorted(OP_KINDS):
            with self.subTest(kind):
                recipe_source.scan_catalog(self._data(kind))

    def test_fact_kinds_produce_facts_and_no_fact_kinds_do_not(self):
        """不产出事实集合里的 kind 产出为空，其余各自产出非空事实。

        判据只看 `scan_catalog` 的调用点数量：不比对降级出的源码行，也不认分支顺序。"""
        from catalog.schema import NO_FACT_KINDS, OP_KINDS
        import recipe_source
        for kind in sorted(OP_KINDS):
            with self.subTest(kind):
                facts = recipe_source.scan_catalog(self._data(kind))
                if kind in NO_FACT_KINDS:
                    self.assertFalse(facts.calls, f"{kind} 在 NO_FACT_KINDS 里却产出了事实：{facts.calls}")
                else:
                    self.assertTrue(facts.calls, f"{kind} 不在 NO_FACT_KINDS 里却没产出事实")


class CatalogLoweringDetailTests(unittest.TestCase):
    """数据降级出的源码行：每个分支的键与实参都照数据写出来，缺可选键时按空处理而不是崩。

    判据是 `_catalog_src()` 自己的输出（事实层唯一的中间表示），以及 `scan_catalog()` 补的归属。"""

    def lowered(self, ops):
        import recipe_source
        return recipe_source._catalog_src({"segment": [{"name": "a", "ops": ops}]})

    def test_close_all_keeps_its_page(self):
        self.assertEqual(self.lowered([{"kind": "close_all", "page": "广告"}]), 'p.off(page="广告")')

    def test_skip_unless_installed_keeps_its_command(self):
        op = {"kind": "skip_unless_installed", "command": "pm path com.a",
              "contains": "com.a", "text": "com.a"}
        self.assertEqual(self.lowered([op]), 'p.shell("pm path com.a")')

    def test_entry_keeps_its_text(self):
        self.assertEqual(self.lowered([{"kind": "entry", "text": "甲"}]), 'p.entry("甲")')

    def test_gated_lists_every_entry_as_a_maybe_call(self):
        self.assertEqual(self.lowered([{"kind": "gated", "entries": ["甲", "乙"], "ops": []}]),
                         'maybe(p, rt, "甲")\nmaybe(p, rt, "乙")')

    def test_a_non_mapping_op_is_skipped_not_the_end_of_the_list(self):
        lowered = self.lowered(["不是 op", {"kind": "off", "only": ["甲"], "page": "p"}])
        self.assertEqual(lowered, 'p.off(only=["甲"], page="p")')

    def test_off_writes_only_and_keep_together(self):
        lowered = self.lowered([{"kind": "off", "only": ["甲"], "keep": ["乙"], "page": "p"}])
        self.assertIn('only=["甲"], ', lowered)
        self.assertIn('keep=["乙"], ', lowered)

    def test_off_required_writes_only_code_and_keep_together(self):
        op = {"kind": "off", "only_code": "system_ads", "keep": ["乙"], "page": "p"}
        lowered = self.lowered([op])
        self.assertIn("only=system_ads(), ", lowered)
        self.assertIn('keep=["乙"], ', lowered)

    def test_if_lib_without_arguments_has_no_trailing_comma(self):
        self.assertEqual(self.lowered([{"kind": "if_lib", "name": "gear"}]), "gear(p, rt)")

    def test_if_lib_keeps_its_arguments(self):
        self.assertEqual(self.lowered([{"kind": "if_lib", "name": "gear", "args": ["甲"]}]),
                         'gear(p, rt, "甲")')

    def test_if_lib_any_writes_each_short_circuit_call(self):
        lowered = self.lowered([{"kind": "if_lib_any", "calls": [
            {"name": "gear", "args": ["甲"]},
            {"name": "off_one"},
            {"method": "enter", "args": ["乙"]},
        ]}])
        self.assertEqual(lowered, 'gear(p, rt, "甲")\noff_one(p, rt)\np.enter("乙")')

    def test_lib_without_arguments_has_no_trailing_comma(self):
        self.assertEqual(self.lowered([{"kind": "lib", "name": "gear"}]), "gear(p, rt)")

    def test_lib_keeps_its_arguments(self):
        self.assertEqual(self.lowered([{"kind": "lib", "name": "gear", "args": ["甲"]}]),
                         'gear(p, rt, "甲")')

    def test_close_listed_writes_the_names_and_the_page(self):
        op = {"kind": "close_listed", "names": ["甲", "乙"], "page": "页", "miss_print": "m"}
        self.assertEqual(self.lowered([op]), 'close_named(p, rt, ["甲", "乙"], "页")')

    def test_close_listed_without_names_writes_an_empty_list(self):
        """`scan_catalog()` 也收未经校验的映射：缺 `names` 时按空名单降级，不抛。"""
        self.assertEqual(self.lowered([{"kind": "close_listed", "page": "页", "miss_print": "m"}]),
                         'close_named(p, rt, [], "页")')

    def test_ops_inside_an_argument_block_are_walked(self):
        op = {"kind": "lib", "name": "gear", "args": [{"ops": [{"kind": "entry", "text": "甲"}]}]}
        self.assertEqual(self.lowered([op]), "gear(p, rt, {'ops': [{'kind': 'entry', 'text': '甲'}]})\n"
                                            'p.entry("甲")')

    def test_a_missing_sub_op_list_is_treated_as_empty(self):
        cases = [
            ({"kind": "gated", "entries": ["甲"]}, 'maybe(p, rt, "甲")'),
            ({"kind": "gated"}, "pass"),
            ({"kind": "scoped"}, "pass"),
            ({"kind": "if_lib_any"}, "pass"),
            ({"kind": "if_find", "text": "甲"}, "pass"),
        ]
        for op, expected in cases:
            with self.subTest(op["kind"]):
                self.assertEqual(self.lowered([op]), expected)

    def test_data_without_segments_lowers_to_pass(self):
        import recipe_source
        self.assertEqual(recipe_source._catalog_src({}), "pass")

    def test_a_segment_without_ops_lowers_to_pass(self):
        import recipe_source
        self.assertEqual(recipe_source._catalog_src({"segment": [{"name": "a"}]}), "pass")

    def test_the_unregistered_kind_message_is_verbatim(self):
        import recipe_source
        data = {"segment": [{"name": "a", "ops": [{"kind": "not_a_registered_kind"}]}]}
        with self.assertRaises(RuntimeError) as caught:
            recipe_source._catalog_src(data)
        self.assertEqual(str(caught.exception),
                         "catalog 事实层不认识 kind='not_a_registered_kind'：给它加一条降级分支"
                         "（产出词条 / 入口事实），或在 catalog.schema 的 OPS 里声明 no_fact=True"
                         "（它本来就不产出事实，派生出 NO_FACT_KINDS）")


class CatalogAttributionTests(unittest.TestCase):
    """`scan_catalog()` 按名字补库调用的归属：`imports` / `import_lines` / `Call.module` 三处一起。"""

    DATA = {"segment": [{"name": "a", "ops": [{"kind": "lib", "name": "gear"}]}]}

    def test_a_library_call_gets_its_module_and_its_lowered_line(self):
        import recipe_source
        module = recipe_source._lib_modules()["gear"]
        facts = recipe_source.scan_catalog(self.DATA)
        self.assertEqual(facts.imports, {"gear": module})
        self.assertEqual(facts.import_lines, {"gear": 1})
        self.assertEqual([call.module for call in facts.calls], [module])

    def test_the_exception_file_imports_are_merged_with_the_data_side(self):
        import recipe_source
        module = recipe_source._lib_modules()["gear"]
        facts = recipe_source.scan_catalog(self.DATA, "from recipe_nav import gear as other\n")
        self.assertEqual(facts.imports, {"gear": module, "other": "recipe_nav"})
        self.assertEqual(facts.import_lines, {"gear": 1, "other": 1})

    def test_the_exception_file_definitions_are_merged_not_intersected(self):
        import recipe_source
        facts = recipe_source.scan_catalog(self.DATA, "def helper(p, rt):\n    p.entry('甲')\n")
        self.assertEqual(facts.defines, {"helper"})
        self.assertEqual([call.name for call in facts.calls], ["gear", "p.entry"])

    def test_an_exception_file_without_a_companion_is_not_merged(self):
        """`scan_catalog_file()` 读不到同名 `.py` 时走的是同一条数据事实，不额外合并空源码。"""
        import recipe_source
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "M1.toml"
            toml_path.write_text('[[segment]]\nname="a"\nops=[{kind="lib", name="gear"}]\n',
                                 encoding="utf-8")
            facts = recipe_source.scan_catalog_file(str(toml_path))
        self.assertEqual([call.name for call in facts.calls], ["gear"])


class _Flushed(io.StringIO):
    """记 flush 次数：客户端按行读引擎的进度输出，`print(..., flush=True)` 是唯一让它立刻看见的手段。"""

    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


def runtime_stand_in():
    """一台不连手机的 Phone 加这次执行：段包装与落点判据的用例共用这一份装配。"""
    phone = fixtures.phone_stub("test", fast_mod=fast, W=1080, H=2340)
    return phone, recipe_runtime.Runtime(phone, [], fixtures.Clock())


def wrapped(rt, body, name="甲"):
    """跑一次段包装，连同 stdout 原文与 flush 次数一起交出。"""
    out = _Flushed()
    with contextlib.redirect_stdout(out):
        result = rt.run_step(name, body)
    return result, out.getvalue(), out.flushes


class RuntimeStateTests(unittest.TestCase):
    """一次执行的初值与回读台账（#1543）：脚本读的默认值、`confirm()` 的唯一写入口与 Counter 的四种读数。"""

    def setUp(self):
        self.phone, self.rt = runtime_stand_in()

    def test_a_fresh_run_has_empty_ledgers_and_no_page_landing(self):
        rt = self.rt
        self.assertEqual(rt.only, [])
        self.assertIsNone(rt.namespace)
        self.assertIs(rt.halted, False)
        self.assertEqual(dict(rt.constants), {})
        self.assertEqual(rt.target, "")
        self.assertEqual(rt.bindings, {})
        self.assertEqual(rt.steps, [])
        self.assertEqual(rt.results, [])
        self.assertEqual(rt.failed_steps, [])
        self.assertEqual(rt.skipped_steps, [])
        self.assertEqual(rt.halted_steps, [])
        self.assertEqual(rt.verified, 0)

    def test_confirm_defaults_to_one_and_only_counts_truthy_batches(self):
        self.rt.confirm()
        self.assertEqual(self.rt.verified, 1)
        self.rt.confirm(4)
        self.assertEqual(self.rt.verified, 5)
        self.rt.confirm(0)
        self.assertEqual(self.rt.verified, 5)

    def test_the_counter_reads_and_writes_the_runtime_ledger(self):
        counter = self.rt.counter
        counter += 3
        self.assertEqual(self.rt.verified, 3)
        self.assertEqual(int(counter), 3)
        self.assertEqual(repr(counter), "3")
        self.assertEqual(hash(counter), hash(3))
        self.assertEqual(counter, 3)
        other = recipe_runtime.Runtime(self.phone, [], fixtures.Clock())
        other.confirm(3)
        self.assertEqual(counter, other.counter)
        other.confirm(1)
        self.assertNotEqual(counter, other.counter)


class ActiveCredentialTests(unittest.TestCase):
    """`activate()` 的独占凭据（#1543）：返回的就是这次执行；第二个开始要报错，退出后可再进入。"""

    def setUp(self):
        self.phone, self.rt = runtime_stand_in()

    def test_activate_hands_back_this_runtime_and_blocks_a_second_one(self):
        with self.rt.activate() as held:
            self.assertIs(held, self.rt)
            with self.assertRaises(RuntimeError) as caught:
                self.rt.activate().__enter__()
        self.assertEqual(str(caught.exception), "同一时刻只允许一个活动执行：上一个机型脚本还没跑完")
        with self.rt.activate() as again:
            self.assertIs(again, self.rt)


class StepRegistrationTests(unittest.TestCase):
    """段装饰器（#1543）：只登记、不执行；两个段按声明顺序排队，段名重复在装饰那一刻报错。"""

    def setUp(self):
        self.phone, self.rt = runtime_stand_in()

    def test_decorating_registers_without_running_and_keeps_the_action(self):
        def body():
            return "ran"

        decorated = self.rt.step("甲")(body)
        self.assertIs(decorated, body)
        self.assertEqual(self.rt.steps,
                         [recipe_runtime.Step("甲", body, body.__code__.co_firstlineno)])

    def test_two_distinct_segments_queue_in_declaration_order(self):
        def first():
            pass

        def second():
            pass

        self.rt.step("甲")(first)
        self.rt.step("乙")(second)
        self.assertEqual([(step.name, step.action, step.line) for step in self.rt.steps],
                         [("甲", first, first.__code__.co_firstlineno),
                          ("乙", second, second.__code__.co_firstlineno)])

    def test_a_duplicate_name_is_rejected_at_decoration_time(self):
        self.rt.step("甲")(lambda: None)
        with self.assertRaises(recipe_runtime.DuplicateStep) as caught:
            self.rt.step("甲")(lambda: None)
        self.assertIn("段名重复：'甲'", str(caught.exception))


class TailHookTests(unittest.TestCase):
    """`run()` 的收尾钩子（#1543）：段跑完后把手机与这次执行交给命名空间里的 `tail`；没有就不做。"""

    def setUp(self):
        self.phone, self.rt = runtime_stand_in()
        self.phone.locked = lambda: False

    def test_tail_runs_after_every_segment_with_the_phone_and_this_run(self):
        seen, order = [], []
        self.rt.namespace = {"tail": lambda p, rt: seen.append((p, rt))}
        self.rt.step("甲")(lambda: order.append("甲"))
        with contextlib.redirect_stdout(_Flushed()):
            self.rt.run()
        self.assertEqual(order, ["甲"])
        self.assertEqual(seen, [(self.phone, self.rt)])

    def test_a_missing_or_non_callable_tail_is_skipped(self):
        for namespace in (None, {}, {"tail": "not-callable"}):
            with self.subTest(namespace=namespace):
                self.rt.namespace = namespace
                with contextlib.redirect_stdout(_Flushed()):
                    self.rt.run()


class StepWrapperTests(unittest.TestCase):
    """段包装（#1543）：结局、跳过出口、中止、可选钩子与每秒一次的进度行都只在这里定义。"""

    def setUp(self):
        self.phone, self.rt = runtime_stand_in()
        self.phone.locked = lambda: False

    def test_a_normal_segment_records_done_resets_misses_and_reports_seconds(self):
        clock = self.rt.clock
        clock.t = 1.0

        def body():
            clock.t = 4.0

        result, text, flushes = wrapped(self.rt, body)
        self.assertIs(result, body)
        self.assertEqual(self.rt.results, [("甲", "完成")])
        self.assertIn("== 甲", text)
        self.assertIn("(3 秒)", text)
        self.assertEqual(self.phone.miss, 0)
        self.assertEqual(flushes, 2)

    def test_the_observer_sees_every_segment_name_even_when_filtered_out(self):
        seen = []
        self.rt.only = ["乙"]
        with patch.object(recipe_runtime, "OBSERVER", seen.append):
            with contextlib.redirect_stdout(_Flushed()):
                self.rt.run_step("甲", lambda: seen.append("body"))
        self.assertEqual(seen, ["甲"])

    def test_after_a_halt_the_remaining_segments_are_recorded_not_run(self):
        self.rt.halted = True
        ran = []

        def body():
            ran.append(1)

        result, text, flushes = wrapped(self.rt, body)
        self.assertIs(result, body)
        self.assertEqual(ran, [])
        self.assertEqual(self.rt.results, [("甲", "未执行")])
        self.assertEqual(self.rt.failed_steps, ["甲"])
        self.assertEqual(self.rt.halted_steps, ["甲"])
        self.assertIn("== 甲", text)
        self.assertIn("  · 未执行：前一段中止了整批", text.splitlines())
        self.assertEqual(flushes, 2)

    def test_a_declared_skip_records_the_segment_as_skipped(self):
        def body():
            self.rt.skip("型号不符")

        result, text, flushes = wrapped(self.rt, body)
        self.assertEqual(self.rt.results, [("甲", "跳过")])
        self.assertEqual(self.rt.skipped_steps, ["甲"])
        self.assertIn("跳过：型号不符", text)
        self.assertEqual(flushes, 3)

    def test_a_failed_segment_saves_the_scene_and_lists_the_step(self):
        saves = []
        self.phone.screen.save_capture = lambda: saves.append(True)

        def body():
            raise RuntimeError("开关没找到")

        result, text, flushes = wrapped(self.rt, body)
        self.assertEqual(saves, [True])
        self.assertEqual(self.rt.results, [("甲", "未完成")])
        self.assertEqual(self.rt.failed_steps, ["甲"])
        self.assertIs(self.rt.halted, False)
        self.assertIn("✗ 未完成：开关没找到", text)
        self.assertEqual(flushes, 3)

    def test_the_detail_hook_gets_the_phone_and_this_run_after_a_failure(self):
        seen = []
        self.rt.namespace = {"detail": lambda p, rt: seen.append((p, rt)) or "下一轮看这里"}

        def body():
            raise RuntimeError("断了")

        result, text, flushes = wrapped(self.rt, body)
        self.assertEqual(seen, [(self.phone, self.rt)])
        self.assertIn("· 下一轮看这里", text)
        self.assertEqual(flushes, 4)

    def test_the_wrap_hook_wraps_the_segment_body_and_gets_the_runtime(self):
        seen = []

        @contextlib.contextmanager
        def wrap(p, rt):
            seen.append(("enter", p, rt))
            yield
            seen.append(("exit",))

        self.rt.namespace = {"wrap": wrap}
        ran = []

        def body():
            ran.append(1)

        wrapped(self.rt, body)
        self.assertEqual(ran, [1])
        self.assertEqual([item[0] for item in seen], ["enter", "exit"])
        self.assertEqual(seen[0][1:], (self.phone, self.rt))
        self.assertEqual(self.rt.results, [("甲", "完成")])

    def test_the_script_may_swap_the_skip_class(self):
        class Mine(RuntimeError):
            pass

        self.rt.namespace = {"SkipStep": Mine}

        def body():
            raise Mine("按宿主约定跳过")

        wrapped(self.rt, body)
        self.assertEqual(self.rt.results, [("甲", "跳过")])
        self.assertEqual(self.rt.skipped_steps, ["甲"])
        self.assertEqual(self.rt.failed_steps, [])

    def test_a_locked_screen_halts_the_batch_with_the_lock_message(self):
        self.phone.locked = lambda: True
        ran = []

        def body():
            ran.append(1)

        _, text, _ = wrapped(self.rt, body)
        self.assertEqual(ran, [])
        self.assertIs(self.rt.halted, True)
        self.assertEqual(self.rt.results, [("甲", "未完成")])
        self.assertIn("  ✗ 未完成：手机锁屏了，请机主解锁后重跑", text.splitlines())


class PageContractTests(unittest.TestCase):
    """`Runtime.page()` 的落点判据（#1543）：三段判据各自的现场行、标题逐字、协议 / 权限弹窗与锁屏。"""

    def setUp(self):
        self.phone, self.rt = runtime_stand_in()
        self.awaits, self.finds, self.misses, self.dismissed = [], [], [], []
        self.phone.await_page = lambda **kw: self.awaits.append(kw)
        self.phone.focus = lambda: "com.android.settings/.Settings"
        self.phone.find = lambda text, exact=False, **kw: self.finds.append((text, exact)) or True
        self.phone.texts = lambda root=None: []
        self.phone.locked = lambda: False
        self.phone.note_miss = lambda text: self.misses.append(text)
        self.phone.dismiss = lambda: self.dismissed.append(True)

    def test_landing_on_the_expected_page_reads_titles_with_exact_match(self):
        self.rt.page("设置", "com.android.settings", ".Settings")
        self.assertEqual(self.awaits, [{"budget": 6}])
        self.assertEqual(self.finds, [("设置", True)])
        self.assertEqual(self.misses, [])
        self.assertEqual(self.dismissed, [])

    def test_a_wrong_package_reports_where_it_stopped_and_names_the_package(self):
        self.phone.focus = lambda: "com.other/.Settings"
        with self.assertRaises(RuntimeError) as caught:
            self.rt.page("设置", "com.android.settings", ".Settings")
        self.assertEqual(str(caught.exception), "未进入目标应用，未操作开关")
        self.assertEqual(self.misses, ["com.android.settings"])

    def test_a_wrong_activity_names_the_activity_in_the_scene_line(self):
        self.phone.focus = lambda: "com.android.settings/.Other"
        with self.assertRaises(RuntimeError) as caught:
            self.rt.page("设置", "com.android.settings", ".Settings")
        self.assertEqual(str(caught.exception), "未进入目标设置页，未操作开关")
        self.assertEqual(self.misses, [".Settings"])

    def test_the_package_is_the_first_segment_of_a_deeper_window_name(self):
        """`focus()` 的窗口名正常是 `包名/页面名`，但读屏正则允许更多段：包名仍按第一个 `/` 前那一段判。"""
        self.phone.focus = lambda: "com.android.settings/.Settings/extra"
        self.rt.page("设置", "com.android.settings")
        self.assertEqual(self.misses, [])

    def test_the_activity_check_reads_the_whole_segment_after_the_first_slash(self):
        """三段窗口名里 Activity 判据看第一个 `/` 之后的整段；只取最后一段（`rsplit`）会漏判。"""
        self.phone.focus = lambda: "com.android.settings/.Settings/extra"
        self.rt.page("设置", "com.android.settings", ".Settings")
        self.assertEqual(self.misses, [])

    def test_a_missing_title_lists_every_wanted_wording(self):
        self.phone.find = lambda text, exact=False, **kw: self.finds.append((text, exact)) or False
        with self.assertRaises(RuntimeError) as caught:
            self.rt.page(["设置", "设定"], "com.android.settings")
        self.assertEqual(str(caught.exception), "未确认页面「设置、设定」，未操作开关")
        self.assertEqual(self.misses, ["设置 / 设定"])

    def test_each_consent_wording_on_a_button_dismisses_and_skips(self):
        for wording in ("同意", "同意并继续", "同意并使用", "允许", "仅在使用中允许"):
            with self.subTest(wording=wording):
                self.dismissed.clear()
                self.phone.texts = lambda root=None, text=wording: [
                    (text, "", {"class": "android.widget.Button"})]
                with self.assertRaises(recipe_runtime.SkipStep) as caught:
                    self.rt.page("设置", "com.android.settings")
                self.assertEqual(self.dismissed, [True])
                self.assertEqual(str(caught.exception), "出现协议或权限申请，不代为同意")

    def test_a_consent_wording_that_is_not_a_button_is_ignored(self):
        self.phone.texts = lambda root=None: [("同意", "", {})]
        self.rt.page("设置", "com.android.settings")
        self.assertEqual(self.dismissed, [])

    def test_a_button_with_another_wording_does_not_count_as_consent(self):
        self.phone.texts = lambda root=None: [("确定", "", {"class": "android.widget.Button"})]
        self.rt.page("设置", "com.android.settings")
        self.assertEqual(self.dismissed, [])

    def test_a_locked_screen_raises_screen_locked_with_the_unlock_instruction(self):
        self.phone.locked = lambda: True
        with self.assertRaises(recipe_runtime.ScreenLocked) as caught:
            self.rt.page("设置", "com.android.settings")
        self.assertEqual(str(caught.exception), "手机锁屏，请机主解锁")


class StartOrSkipLandingTests(unittest.TestCase):
    """`start_or_skip()` 的落点豁免（#1543）：只有「停在死胡同」与「落点不对」同时成立才按跳过。"""

    def setUp(self):
        self.phone, self.rt = runtime_stand_in()

    def test_a_dead_end_landing_with_a_wrong_page_marker_skips(self):
        def start(pkg, activity=None, **kw):
            raise RuntimeError("停在 com.android.vending；没有进入前台")

        self.phone.start = start
        with self.assertRaises(recipe_runtime.SkipStep) as caught:
            self.rt.start_or_skip("com.pkg", ".X", {"com.android.vending"}, "缺商店")
        self.assertEqual(str(caught.exception), "缺商店（停在 com.android.vending）")

    def test_a_plain_start_failure_still_raises_instead_of_skipping(self):
        def start(pkg, activity=None, **kw):
            raise RuntimeError("停在 com.android.vending；启动失败")

        self.phone.start = start
        with self.assertRaises(RuntimeError) as caught:
            self.rt.start_or_skip("com.pkg", ".X", {"com.android.vending"}, "缺商店")
        self.assertNotIsInstance(caught.exception, recipe_runtime.SkipStep)


class FlushCountingStdout(io.StringIO):
    """数 flush：解释器打人话的每一句都要 `flush=True`，客户端按行读管道才立刻看得见。"""

    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


def _spy_py():
    """本机例外 `.py`：不在 `LIBRARY` 里的助手，名字只能经装载器给的命名空间解析。"""
    return (
        "def seed_lib(p, rt):\n"
        "    return 'SEED'\n"
        "def empty_lib(p, rt):\n"
        "    return ''\n"
        "def spy_let(p, rt, *args, **kwargs):\n"
        "    p.let_seen = (rt, args, kwargs)\n"
        "    return 'GOT'\n"
        "def spy_lib(p, rt, *args, **kwargs):\n"
        "    p.lib_seen = (rt, args, kwargs)\n"
        "def spy_req(p, rt, *args, **kwargs):\n"
        "    p.req_seen = (rt, args, kwargs)\n"
        "    return False\n"
        "def spy_ret(p, rt, *args, **kwargs):\n"
        "    p.ret_seen = (rt, args, kwargs)\n"
        "    return getattr(p, 'ret_result', True)\n"
        "def spy_code(p, rt, *args):\n"
        "    p.code_seen = (rt, args)\n"
        "def spy_if(p, rt, *args, **kwargs):\n"
        "    p.if_seen = (rt, args, kwargs)\n"
        "    return getattr(p, 'if_result', True)\n"
        "def spy_any(p, rt, *args, **kwargs):\n"
        "    p.any_seen = (rt, args, kwargs)\n"
        "    return getattr(p, 'any_result', True)\n"
        "def hit(p, rt):\n"
        "    p.hits = getattr(p, 'hits', 0) + 1\n"
        "    p.hit_rt = rt\n"
    )


class ArgExpressionTests(unittest.TestCase):
    """实参里的动态取值在每个收实参的 op 上都照原样求值（#1373、#1371）。

    `{expr = "focus"}` 读手机、`{expr = "var"}` 读本段绑定、`{ops = […]}` 包成回调交给库——
    这三样是解释器唯一会去读 `p` / `rt` / 命名空间的地方，换成别的东西都不该通过。库助手一律
    写成例外 `.py` 里的函数：名字先查 `LIBRARY` 再查命名空间的那条路才走得到。"""

    PY = _spy_py()

    def _run(self, toml, **patches):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml, self.PY)
            phone.focus = lambda *a, **k: "焦点"
            phone.tree = lambda: "树"
            for name, value in patches.items():
                setattr(phone, name, value)
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        return recipe, phone

    LET = ('[[segment]]\nname="a"\nops=[\n'
           '{kind="let", name="seed", lib="seed_lib"},\n'
           '{kind="let", name="got", lib="spy_let", args=["字面", {expr="focus"},'
           ' {expr="var", name="seed"}, {ops=[{kind="code", name="hit"}]}],'
           ' kwargs={page={expr="tree"}, bound={expr="var", name="seed"},'
           ' cb={ops=[{kind="code", name="hit"}]}, size=3}},\n'
           '{kind="lib", name="spy_lib", args=[{expr="var", name="got"},'
           ' {ops=[{kind="code", name="hit"}]}],'
           ' kwargs={cb={ops=[{kind="code", name="hit"}]}}},\n'
           ']\n')

    def test_let_binds_the_return_of_every_argument_form(self):
        recipe, phone = self._run(self.LET)
        rt, args, kwargs = phone.let_seen
        self.assertIs(rt, recipe.rt)
        self.assertEqual(args[:3], ("字面", "焦点", "SEED"))
        callback = kwargs.pop("cb")
        self.assertEqual(kwargs, {"page": "树", "bound": "SEED", "size": 3})
        args[3]()
        callback()
        self.assertEqual(phone.hits, 2, "实参块回调没跑到，或块里的 op 拿不到命名空间")

    def test_lib_forwards_variable_references_and_callback_blocks(self):
        recipe, phone = self._run(self.LET)
        rt, args, kwargs = phone.lib_seen
        self.assertIs(rt, recipe.rt)
        self.assertEqual(args[0], "GOT")
        args[1]()
        kwargs["cb"]()
        self.assertEqual(phone.hits, 2)

    def test_code_forwards_the_same_argument_forms(self):
        toml = ('[[segment]]\nname="a"\nops=[\n'
                '{kind="let", name="seed", lib="seed_lib"},\n'
                '{kind="code", name="spy_code", args=["字面", {expr="focus"},'
                ' {expr="var", name="seed"}, {ops=[{kind="code", name="hit"}]}]},\n]\n')
        recipe, phone = self._run(toml)
        rt, args = phone.code_seen
        self.assertIs(rt, recipe.rt)
        self.assertEqual(args[:3], ("字面", "焦点", "SEED"))
        args[3]()
        self.assertEqual(phone.hits, 1)

    REQUIRE_LIB = ('[[segment]]\nname="a"\nops=[\n'
                   '{kind="let", name="seed", lib="seed_lib"},\n'
                   '{kind="require_lib", name="spy_req", args=["字面", {expr="focus"},'
                   ' {expr="var", name="seed"}, {ops=[{kind="code", name="hit"}]}],'
                   ' kwargs={page={expr="tree"}, bound={expr="var", name="seed"},'
                   ' cb={ops=[{kind="code", name="hit"}]}},'
                   ' miss_print="不成立", miss_back=2},\n]\n')

    def test_require_lib_forwards_arguments_and_backs_out_on_miss(self):
        backs = []
        recipe, phone = self._run(self.REQUIRE_LIB, back=lambda n=1: backs.append(n))
        rt, args, kwargs = phone.req_seen
        self.assertIs(rt, recipe.rt)
        self.assertEqual(args[:3], ("字面", "焦点", "SEED"))
        callback = kwargs.pop("cb")
        self.assertEqual(kwargs, {"page": "树", "bound": "SEED"})
        args[3]()
        callback()
        self.assertEqual(phone.hits, 2)
        self.assertEqual(backs, [2])
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    RETURN_LIB = ('[[segment]]\nname="a"\nops=[\n'
                  '{kind="let", name="seed", lib="seed_lib"},\n'
                  '{kind="return_lib", name="spy_ret", args=["字面", {expr="focus"},'
                  ' {expr="var", name="seed"}, {ops=[{kind="code", name="hit"}]}],'
                  ' kwargs={page={expr="tree"}, bound={expr="var", name="seed"},'
                  ' cb={ops=[{kind="code", name="hit"}]}}},\n]\n')

    def test_return_lib_forwards_arguments_and_takes_the_result(self):
        recipe, phone = self._run(self.RETURN_LIB, ret_result=True)
        rt, args, kwargs = phone.ret_seen
        self.assertIs(rt, recipe.rt)
        self.assertEqual(args[:3], ("字面", "焦点", "SEED"))
        callback = kwargs.pop("cb")
        self.assertEqual(kwargs, {"page": "树", "bound": "SEED"})
        args[3]()
        callback()
        self.assertEqual(phone.hits, 2)
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_return_lib_without_arguments_takes_the_result_as_the_outcome(self):
        recipe, _phone = self._run(
            '[[segment]]\nname="a"\nops=[{kind="return_lib", name="spy_ret"}]\n',
            ret_result=True)
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    START_OR_SKIP = ('[[segment]]\nname="a"\nops=[\n'
                     '{kind="let", name="seed", lib="seed_lib"},\n'
                     '{kind="start_or_skip", pkg="p", activity="a", dead_ends=%s,'
                     ' reason="r"},\n]\n')

    def test_start_or_skip_forwards_dead_ends_built_from_expressions(self):
        cases = (
            ('{expr="focus"}', "焦点", 0),
            ('{expr="var", name="seed"}', "SEED", 0),
            ('{ops=[{kind="code", name="hit"}]}', None, 1),
        )
        for dead_ends, expected, hits in cases:
            with self.subTest(dead_ends=dead_ends):
                seen = []
                with tempfile.TemporaryDirectory() as tmp:
                    recipe, phone, _calls = _load_tmp(
                        tmp, self.START_OR_SKIP % dead_ends, self.PY)
                    phone.focus = lambda *a, **k: "焦点"
                    recipe.rt.start_or_skip = lambda pkg, activity, _seen=seen, **kw: _seen.append(
                        (pkg, activity, kw))
                    with contextlib.redirect_stdout(io.StringIO()):
                        recipe.run()
                pkg, activity, kw = seen[0]
                self.assertEqual((pkg, activity), ("p", "a"))
                self.assertEqual(kw["reason"], "r")
                if expected is None:
                    kw["dead_ends"]()
                    self.assertEqual(phone.hits, hits)
                else:
                    self.assertEqual(kw["dead_ends"], expected)

    PAGE = ('[[segment]]\nname="a"\nops=[\n'
            '{kind="let", name="seed", lib="seed_lib"},\n'
            '{kind="page", args=["落点", {expr="focus"}, {expr="var", name="seed"},'
            ' {ops=[{kind="code", name="hit"}]}], kwargs={timeout={expr="tree"},'
            ' pkg={expr="var", name="seed"}, cb={ops=[{kind="code", name="hit"}]}}},\n]\n')

    def test_page_forwards_positional_and_keyword_forms(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.PAGE, self.PY)
            phone.focus = lambda *a, **k: "焦点"
            phone.tree = lambda: "树"
            recipe.rt.page = lambda *a, **kw: seen.append((a, kw))
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        args, kwargs = seen[0]
        self.assertEqual(args[:3], ("落点", "焦点", "SEED"))
        callback = kwargs.pop("cb")
        self.assertEqual(kwargs, {"timeout": "树", "pkg": "SEED"})
        args[3]()
        callback()
        self.assertEqual(phone.hits, 2)

    EXPECT = ('[[segment]]\nname="a"\nops=[\n'
              '{kind="let", name="seed", lib="seed_lib"},\n'
              '{kind="require_expect", calls=[{args=[{expr="focus"}, {expr="var", name="seed"},'
              ' {ops=[{kind="code", name="hit"}]}],'
              ' kwargs={timeout={expr="tree"}, bound={expr="var", name="seed"},'
              ' cb={ops=[{kind="code", name="hit"}]}}}],'
              ' miss_print="没开"},\n]\n')

    def test_require_expect_forwards_arguments_built_from_expressions(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, self.EXPECT, self.PY)
            phone.focus = lambda *a, **k: "焦点"
            phone.tree = lambda: "树"
            phone.expect_page = lambda *a, **kw: seen.append((a, kw)) or True
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        args, kwargs = seen[0]
        self.assertEqual(args[:2], ("焦点", "SEED"))
        self.assertEqual((kwargs["timeout"], kwargs["bound"]), ("树", "SEED"))
        args[2]()
        kwargs["cb"]()
        self.assertEqual(phone.hits, 2)

    IF_LIB = ('[[segment]]\nname="a"\nops=[\n'
              '{kind="let", name="seed", lib="seed_lib"},\n'
              '{kind="if_lib", name="spy_if", args=["字面", {expr="focus"},'
              ' {expr="var", name="seed"}, {ops=[{kind="code", name="hit"}]}],'
              ' kwargs={page={expr="tree"}, bound={expr="var", name="seed"},'
              ' cb={ops=[{kind="code", name="hit"}]}}, ops=[{kind="code", name="hit"}],'
              ' else_ops=[{kind="code", name="hit"}]},\n]\n')

    def test_if_lib_forwards_arguments_and_runs_the_else_block(self):
        recipe, phone = self._run(self.IF_LIB, if_result=False)
        rt, args, kwargs = phone.if_seen
        self.assertIs(rt, recipe.rt)
        self.assertEqual(args[:3], ("字面", "焦点", "SEED"))
        callback = kwargs.pop("cb")
        self.assertEqual(kwargs, {"page": "树", "bound": "SEED"})
        args[3]()
        callback()
        self.assertEqual(phone.hits, 3, "实参回调一次 + 关键字回调一次 + else 块一次")
        self.assertIs(phone.hit_rt, recipe.rt)

    IF_ANY = ('[[segment]]\nname="a"\nops=[\n'
              '{kind="let", name="seed", lib="seed_lib"},\n'
              '{kind="if_lib_any", calls=[{name="spy_any", args=["字面", {expr="focus"},'
              ' {expr="var", name="seed"}, {ops=[{kind="code", name="hit"}]}],'
              ' kwargs={page={expr="tree"}, bound={expr="var", name="seed"},'
              ' cb={ops=[{kind="code", name="hit"}]}}}], ops=[{kind="code", name="hit"}],'
              ' else_ops=[{kind="code", name="hit"}]},\n]\n')

    def test_if_lib_any_forwards_arguments_and_runs_the_else_block(self):
        recipe, phone = self._run(self.IF_ANY, any_result=False)
        rt, args, kwargs = phone.any_seen
        self.assertIs(rt, recipe.rt)
        self.assertEqual(args[:3], ("字面", "焦点", "SEED"))
        callback = kwargs.pop("cb")
        self.assertEqual(kwargs, {"page": "树", "bound": "SEED"})
        args[3]()
        callback()
        self.assertEqual(phone.hits, 3, "实参回调一次 + 关键字回调一次 + else 块一次")
        self.assertIs(phone.hit_rt, recipe.rt)

    def test_an_unknown_expression_names_itself_in_the_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="lib", name="spy_lib",'
                     ' args=[{expr="bogus"}]}]\n', _spy_py())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                recipe.run()
        self.assertEqual(recipe.rt.failed_steps, ["a"])
        self.assertIn("未知的实参表达式 expr='bogus'", out.getvalue())


class InterpreterDefaultsTests(unittest.TestCase):
    """op 的缺省形态：不写 `scrolls` / `ops` / `else_ops` 时下发什么、走哪一支。"""

    def _run(self, toml, py_text=None, **patches):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml, py_text)
            for name, value in patches.items():
                setattr(phone, name, value)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                recipe.run()
        return recipe, phone, out.getvalue()

    def test_entry_defaults_its_scrolls_to_six(self):
        seen = []
        self._run('[[segment]]\nname="a"\nops=[{kind="entry", text="设置"},'
                  ' {kind="entry", text="隐私", scrolls=4}]\n',
                  entry=lambda text, **kw: seen.append((text, kw)) or True)
        self.assertEqual(seen, [("设置", {"scrolls": 6}), ("隐私", {"scrolls": 4})])

    def test_require_entry_misses_with_the_default_scrolls_and_backs_out(self):
        seen, backs = [], []
        recipe, _phone, out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_entry", text="设置",'
            ' miss_print="没有设置", miss_back=2}, {kind="back", n=1}]\n',
            entry=lambda text, **kw: seen.append((text, kw)) or False,
            back=lambda n=1: backs.append(n))
        self.assertEqual(seen, [("设置", {"scrolls": 6})])
        self.assertEqual(backs, [2])
        self.assertEqual(recipe.rt.results, [("a", "完成")])
        self.assertIn("没有设置", out)

    def test_gated_stops_at_the_first_missing_entry(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="gated", entries=["甲", "乙"],'
                ' ops=[{kind="code", name="hit"}]}]\n')
        seen = []
        recipe, phone, _out = self._run(
            toml, _spy_py(), entry=lambda text, **kw: seen.append((text, kw)) or text == "甲")
        self.assertEqual(seen, [("甲", {"scrolls": 6}), ("乙", {"scrolls": 6})])
        self.assertFalse(hasattr(phone, "hits"), "有一处没认到就不该进块")
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_gated_runs_the_block_when_every_entry_is_found(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="gated", entries=["甲", "乙"], scrolls=3,'
                ' ops=[{kind="code", name="hit"}]}]\n')
        seen = []
        recipe, phone, _out = self._run(
            toml, _spy_py(), entry=lambda text, **kw: seen.append((text, kw)) or True)
        self.assertEqual(seen, [("甲", {"scrolls": 3}), ("乙", {"scrolls": 3})])
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)

    def test_gated_without_ops_is_harmless(self):
        recipe, _phone, _out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="gated", entries=["甲"]}]\n',
            entry=lambda text, **kw: True)
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_scoped_without_ops_only_restores_the_attribute(self):
        recipe, phone, _out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="scoped", systemui_text=true}]\n')
        self.assertEqual(recipe.rt.results, [("a", "完成")])
        self.assertEqual(phone.screen.systemui_text, False)

    def test_scoped_runs_a_body_that_reads_the_runtime(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="scoped", systemui_text=true,'
                ' ops=[{kind="code", name="hit"}]}]\n')
        recipe, phone, _out = self._run(toml, _spy_py())
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)
        self.assertEqual(phone.screen.systemui_text, False)

    def test_if_var_takes_the_hit_branch_without_a_block(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="let", name="v", lib="seed_lib"},'
                ' {kind="if_var", name="v"}]\n')
        recipe, _phone, _out = self._run(toml, _spy_py())
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_if_var_takes_the_miss_branch_without_else_ops(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="let", name="v", lib="empty_lib"},'
                ' {kind="if_var", name="v", ops=[{kind="code", name="hit"}]}]\n')
        recipe, phone, _out = self._run(toml, _spy_py())
        self.assertFalse(hasattr(phone, "hits"))
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_if_var_blocks_run_with_the_runtime(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="let", name="v", lib="seed_lib"},'
                ' {kind="if_var", name="v", not_none=true, ops=[{kind="code", name="hit"}],'
                ' else_ops=[{kind="code", name="hit"}]}]\n')
        recipe, phone, _out = self._run(toml, _spy_py())
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)

    def test_if_tap_miss_runs_the_else_block(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_tap", text="设置",'
                ' else_ops=[{kind="code", name="hit"}]}]\n')
        recipe, phone, _out = self._run(toml, _spy_py(), tap=lambda text, **kw: False)
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)

    def test_if_setting_miss_takes_the_else_block(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_setting", kw="广告服务",'
                ' ops=[{kind="code", name="hit"}], else_ops=[{kind="code", name="hit"}]}]\n')
        recipe, phone, _out = self._run(toml, _spy_py(), setting=lambda kw, entry=None: False)
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)

    def test_if_setting_hit_runs_the_block_with_the_runtime(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_setting", kw="广告服务",'
                ' ops=[{kind="code", name="hit"}], else_ops=[{kind="code", name="hit"}]}]\n')
        recipe, phone, _out = self._run(toml, _spy_py(), setting=lambda kw, entry=None: True)
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)

    def test_if_setting_without_blocks_is_harmless(self):
        recipe, _phone, _out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="if_setting", kw="广告服务"}]\n',
            setting=lambda kw, entry=None: False)
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_if_lib_else_block_runs_with_the_runtime(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_lib", name="spy_if",'
                ' ops=[{kind="code", name="hit"}], else_ops=[{kind="code", name="hit"}]}]\n')
        recipe, phone, _out = self._run(toml, _spy_py(), if_result=False)
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)

    def test_if_lib_any_hit_runs_the_block_and_else_runs_the_other(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_lib_any", calls=[{name="spy_any"}],'
                ' ops=[{kind="code", name="hit"}], else_ops=[{kind="code", name="hit"}]}]\n')
        _recipe, phone, _out = self._run(toml, _spy_py(), any_result=True)
        self.assertEqual(phone.hits, 1)
        hit_recipe, phone, _out = self._run(toml, _spy_py(), any_result=False)
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, hit_recipe.rt)

    def test_if_find_forwards_nav_and_runs_both_blocks(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_find", text="城市管理", nav=true,'
                ' ops=[{kind="code", name="hit"}], else_ops=[{kind="code", name="hit"}]}]\n')
        seen = []
        recipe, phone, _out = self._run(
            toml, _spy_py(), find=lambda text, **kw: seen.append((text, kw)) or True)
        self.assertEqual(seen, [("城市管理", {"nav": True})])
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)
        miss_recipe, phone, _out = self._run(toml, _spy_py(), find=lambda text, **kw: False)
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, miss_recipe.rt)

    def test_if_focus_body_runs_with_the_runtime(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_focus", text="设置",'
                ' ops=[{kind="code", name="hit"}], else_ops=[{kind="code", name="hit"}]}]\n')
        recipe, phone, _out = self._run(toml, _spy_py(), focus=lambda *a, **k: "设置页")
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)

    def test_if_entry_defaults_scrolls_and_runs_both_blocks(self):
        toml = ('[[segment]]\nname="a"\nops=[{kind="if_entry", text="设置",'
                ' ops=[{kind="code", name="hit"}], else_ops=[{kind="code", name="hit"}]}]\n')
        seen = []
        recipe, phone, _out = self._run(
            toml, _spy_py(), entry=lambda text, **kw: seen.append((text, kw)) or True)
        self.assertEqual(seen, [("设置", {"scrolls": 6})])
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, recipe.rt)
        miss_recipe, phone, _out = self._run(toml, _spy_py(), entry=lambda text, **kw: False)
        self.assertEqual(phone.hits, 1)
        self.assertIs(phone.hit_rt, miss_recipe.rt)


class ToggleAndStartOpDefaultsTests(unittest.TestCase):
    """开关与拉起那几支 op 的实参形状：缺省按钮 / `max_screens` / `only_code` / 等待键 / `n`。"""

    def _run(self, toml, py_text=None, **patches):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml, py_text)
            for name, value in patches.items():
                setattr(phone, name, value)
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        return recipe, phone

    def _close_all(self, op):
        taps, confirms = [], []
        recipe, _phone = self._run(
            f'[[segment]]\nname="a"\nops=[{op}]\n',
            tap=lambda text, **kw: taps.append((text, kw)),
            confirm=lambda: confirms.append(True))
        self.assertEqual(recipe.rt.results, [("a", "完成")])
        self.assertEqual(confirms, [True], "全部关闭之后要回读确认一次")
        return taps

    def test_close_all_defaults_to_the_named_button(self):
        self.assertEqual(self._close_all('{kind="close_all", page="广告"}'),
                         [("全部关闭", {"exact": True})])

    def test_close_all_honours_a_custom_button(self):
        self.assertEqual(self._close_all('{kind="close_all", page="广告", button="全部关闭服务"}'),
                         [("全部关闭服务", {"exact": True})])

    def test_off_forwards_max_screens_and_keep_and_counts_the_readback(self):
        calls = []
        recipe, _phone = self._run(
            '[[segment]]\nname="a"\nops=[{kind="off", page="首页", only=["乙"], keep=["甲"],'
            ' max_screens=2}]\n',
            off=lambda **kw: calls.append(kw) or 3)
        self.assertEqual(calls, [{"page": "首页", "only": ["乙"], "keep": ["甲"], "max_screens": 2}])
        self.assertEqual(recipe.rt.verified, 3, "回读确认到 3 项要记进这次执行")

    def test_off_only_code_calls_the_policy_with_the_runtime(self):
        toml = ('[const]\nONLY = ["乙"]\n'
                '[[segment]]\nname="a"\nops=[{kind="off", page="首页", only_code="policy"}]\n')
        calls = []
        self._run(toml, "def policy(p, rt):\n    return list(rt.constants['ONLY'])\n",
                  off=lambda **kw: calls.append(kw))
        self.assertEqual(calls, [{"page": "首页", "only": ["乙"]}])

    def test_start_forwards_the_wait_keys(self):
        seen = []
        self._run('[[segment]]\nname="a"\nops=[{kind="start", pkg="com.x", settle=1,'
                  ' foreground=["广告"], expect="广告页", budget=5}]\n',
                  start=lambda *a, **kw: seen.append((a, kw)))
        self.assertEqual(seen, [(("com.x",), {"settle": 1, "foreground": ["广告"],
                                              "expect": "广告页", "budget": 5})])

    def test_top_forwards_n_and_takes_none(self):
        seen = []
        self._run('[[segment]]\nname="a"\nops=[{kind="top", n=2}, {kind="top"}]\n',
                  top=lambda *a: seen.append(a))
        self.assertEqual(seen, [(2,), ()])

    def test_tap_forwards_the_extra_kwargs(self):
        seen = []
        self._run('[[segment]]\nname="a"\nops=[{kind="tap", text="设置", exact=true,'
                  ' kwargs={scrolls=0, edge_ok="tab"}}]\n',
                  tap=lambda text, **kw: seen.append((text, kw)))
        self.assertEqual(seen, [("设置", {"exact": True, "scrolls": 0, "edge_ok": "tab"})])


class MinorOpTests(unittest.TestCase):
    """单句 op 的转发与锁屏门：`press` / `app_stop` / `miss_reset` / `print` / `require_*`。"""

    def _run(self, toml, py_text=None, **patches):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml, py_text)
            for name, value in patches.items():
                setattr(phone, name, value)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                recipe.run()
        return recipe, phone, out.getvalue()

    def test_press_forwards_the_key(self):
        seen = []
        recipe, _phone, _out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="press", key="HOME"}]\n',
            press=lambda key: seen.append(key))
        self.assertEqual(seen, ["HOME"])
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_app_stop_forwards_the_package(self):
        seen = []
        self._run('[[segment]]\nname="a"\nops=[{kind="app_stop", pkg="com.x"}]\n',
                  app_stop=lambda pkg: seen.append(pkg))
        self.assertEqual(seen, ["com.x"])

    def test_miss_reset_zeroes_the_counter(self):
        _recipe, phone, _out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="miss_reset"}]\n')
        self.assertEqual(phone.miss, 0)

    def test_print_appends_the_foreground_only_when_asked(self):
        _recipe, _phone, out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="print", text="文案"},'
            ' {kind="print", text="文案", focus=true}]\n',
            focus=lambda *a, **k: "焦点")
        lines = [line for line in out.splitlines() if line.startswith("文案")]
        self.assertEqual(lines, ["文案", "文案焦点"])

    def test_require_unlocked_passes_when_the_phone_is_not_locked(self):
        recipe, _phone, _out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_unlocked"}]\n',
            locked=lambda: False)
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_require_unlocked_raises_with_the_default_text(self):
        # 段包装先查一次锁屏（放行），op 自己再查一次（锁上）：两次读数要给不同的答案。
        states = iter([False, True])
        recipe, _phone, out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_unlocked"}]\n',
            locked=lambda: next(states))
        self.assertEqual(recipe.rt.failed_steps, ["a"])
        self.assertIn("  ✗ 未完成：手机锁屏，请机主解锁", out)

    def test_require_unlocked_uses_a_custom_text(self):
        states = iter([False, True])
        recipe, _phone, out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_unlocked", miss_print="请先解锁"}]\n',
            locked=lambda: next(states))
        self.assertEqual(recipe.rt.failed_steps, ["a"])
        self.assertIn("请先解锁", out)

    def test_require_setting_forwards_the_entry(self):
        seen = []
        self._run('[[segment]]\nname="a"\nops=[{kind="require_setting", kw="广告服务",'
                  ' entry="隐私", miss_print="没找到"}]\n',
                  setting=lambda kw, entry=None: seen.append((kw, entry)) or True)
        self.assertEqual(seen, [("广告服务", "隐私")])

    def test_require_setting_miss_fails_with_the_text(self):
        recipe, _phone, out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_setting", kw="广告服务",'
            ' miss_print="没找到广告服务"}]\n',
            setting=lambda kw, entry=None: False)
        self.assertEqual(recipe.rt.failed_steps, ["a"])
        self.assertIn("没找到广告服务", out)

    def test_require_focus_asserts_the_contains(self):
        recipe, _phone, _out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_focus", contains="Settings",'
            ' miss_print="不在设置"}]\n',
            focus=lambda *a, **k: "com.android.Settings/.Main")
        self.assertEqual(recipe.rt.results, [("a", "完成")])
        recipe, _phone, out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_focus", contains="Settings",'
            ' miss_print="不在设置"}]\n',
            focus=lambda *a, **k: "com.android.browser/.Main")
        self.assertEqual(recipe.rt.failed_steps, ["a"])
        self.assertIn("不在设置", out)

    def test_require_find_forwards_exact_and_uses_it(self):
        seen = []
        recipe, _phone, _out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_find", text="广告", exact=true,'
            ' miss_print="没有广告"}]\n',
            find=lambda text, **kw: seen.append((text, kw)) or True)
        self.assertEqual(seen, [("广告", {"exact": True})])
        self.assertEqual(recipe.rt.results, [("a", "完成")])

    def test_require_find_miss_fails_with_the_text(self):
        recipe, _phone, out = self._run(
            '[[segment]]\nname="a"\nops=[{kind="require_find", text="广告", miss_print="没有广告"}]\n',
            find=lambda text, **kw: False)
        self.assertEqual(recipe.rt.failed_steps, ["a"])
        self.assertIn("没有广告", out)


class AtFocusMessageTests(unittest.TestCase):
    """`at_focus=true` 的现场尾巴（`…；停在 <前台>`）：五个 `require_*` 都要接上。"""

    CASES = {
        "require_lib": ('{kind="require_lib", name="spy_req", miss_print="文案", at_focus=true}',
                        ""),
        "require_tab": ('{kind="require_tab", name="我的", miss_print="文案", at_focus=true}',
                        "  ✗ 未完成："),
        "require_go": ('{kind="require_go", text="我的", expect="页面", miss_print="文案",'
                       ' at_focus=true}', "  ✗ 未完成："),
        "require_tap": ('{kind="require_tap", text="我的", miss_print="文案", at_focus=true}',
                        "  ✗ 未完成："),
        "require_expect": ('{kind="require_expect", calls=[{args=["X"]}], miss_print="文案",'
                           ' at_focus=true}', "  ✗ 未完成："),
    }

    def test_every_require_op_appends_the_foreground_to_its_message(self):
        for kind, (op, prefix) in self.CASES.items():
            with self.subTest(kind=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    recipe, phone, _calls = _load_tmp(
                        tmp, f'[[segment]]\nname="a"\nops=[{op}]\n', _spy_py())
                    phone.focus = lambda *a, **k: "com.x/.Main"
                    phone.tab = lambda name: False
                    phone.go = lambda text, expect: False
                    phone.tap = lambda text, **kw: False
                    phone.expect_page = lambda *a, **kw: False
                    with contextlib.redirect_stdout(io.StringIO()) as out:
                        recipe.run()
                self.assertIn(prefix + "文案；停在 com.x/.Main", out.getvalue(), kind)
                if kind == "require_lib":
                    self.assertEqual(recipe.rt.results, [("a", "完成")], kind)
                else:
                    self.assertEqual(recipe.rt.failed_steps, ["a"], kind)

    def test_require_expect_reads_the_foreground_even_when_a_call_hits(self):
        """`break` 在 `at_focus` 下要落到那句读取上：提前 `return` 会让对拍少一条前台读。"""
        reads = []
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="require_expect", calls=[{args=["X"]}],'
                     ' miss_print="文案", at_focus=true}]\n')
            phone.focus = lambda *a, **k: reads.append(1) or "com.x/.Main"
            phone.expect_page = lambda *a, **kw: True
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        self.assertEqual(reads, [1])
        self.assertEqual(recipe.rt.results, [("a", "完成")])


class OutputFlushTests(unittest.TestCase):
    """解释器打人话的每一句都 `flush=True`：管道按行读，攒在缓冲里客户端就卡住。

    每段固定三次 flush：段标题、op 那一句、耗时行；解释器少打一次 flush 就只剩两次。"""

    def _flushes(self, toml, py_text=None, **patches):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml, py_text)
            for name, value in patches.items():
                setattr(phone, name, value)
            sink = FlushCountingStdout()
            with contextlib.redirect_stdout(sink):
                recipe.run()
        return sink.flushes

    def test_the_print_op_flushes_its_line(self):
        self.assertEqual(
            self._flushes('[[segment]]\nname="a"\nops=[{kind="print", text="一行"}]\n'), 3)

    def test_require_lib_miss_flushes(self):
        self.assertEqual(self._flushes(
            '[[segment]]\nname="a"\nops=[{kind="require_lib", name="spy_req",'
            ' miss_print="没找到"}]\n', _spy_py()), 3)

    def test_skip_unless_installed_flushes(self):
        self.assertEqual(self._flushes(
            '[[segment]]\nname="a"\nops=[{kind="skip_unless_installed", command="pm path com.x",'
            ' contains="package:", text="  · 没有主题管理包"}]\n',
            shell=lambda command, timeout=None: ""), 3)

    def test_require_entry_miss_flushes(self):
        self.assertEqual(self._flushes(
            '[[segment]]\nname="a"\nops=[{kind="require_entry", text="设置",'
            ' miss_print="没有设置"}]\n', entry=lambda text, **kw: False), 3)

    def test_tap_id_miss_flushes(self):
        self.assertEqual(self._flushes(
            '[[segment]]\nname="a"\nops=[{kind="tap_id", resource_id="com.x:id/none",'
            ' miss_print="  ✗ 没找到"}]\n'), 3)


class ReadbackAndConfirmTests(unittest.TestCase):
    """回读确认与名单核对（`off_required` / `close_listed`）：跨翻页读数、`contains` 与 `rt.confirm`。"""

    def _run(self, toml, py_text=None, **patches):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(tmp, toml, py_text)
            for name, value in patches.items():
                setattr(phone, name, value)
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        return recipe, phone

    def test_off_required_stops_scanning_at_the_bottom(self):
        scans = []
        self._run(
            '[[segment]]\nname="a"\nops=[{kind="off_required", only=["甲"], page="主题·设置"}]\n',
            switches=lambda root=None: scans.append(1) or [("甲", True, (0, 0))],
            scroll_more=lambda: False, top=lambda *a: None, off=lambda **kw: 2)
        self.assertEqual(len(scans), 1, "到底之后不该再扫一遍")

    def test_off_required_scans_at_most_twice(self):
        scans = []
        self._run(
            '[[segment]]\nname="a"\nops=[{kind="off_required", only=["甲"], page="主题·设置"}]\n',
            switches=lambda root=None: scans.append(1) or [("甲", True, (0, 0))],
            scroll_more=lambda: True, top=lambda *a: None, off=lambda **kw: 2)
        self.assertEqual(len(scans), 2, "两屏读齐就够：再扫一遍说明循环次数写宽了")

    def test_off_required_forwards_the_checked_names_and_confirms(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="off_required", only=["甲"], keep=["乙"],'
                     ' page="主题·设置"}]\n')
            phone.switches = lambda root=None: [("甲", True, (0, 0))]
            phone.scroll_more = lambda: False
            phone.top = lambda *a: None
            phone.off = lambda **kw: 2
            recipe.rt.require_switches = lambda before, names, title, **kw: seen.append(
                (before, names, title, kw))
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        self.assertEqual(seen, [({"甲": True}, ["甲"], "主题·设置", {"contains": False})])
        self.assertEqual(recipe.rt.verified, 2)

    def test_require_switches_hands_the_bound_table_names_and_title_to_the_runtime(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="let", name="s", lib="seed_lib"},'
                     ' {kind="require_switches", before={expr="var", name="s"},'
                     ' names=["甲"], title="资讯服务"}]\n', _spy_py())
            recipe.rt.require_switches = lambda before, names, title, **kw: seen.append(
                (before, names, title))
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        self.assertEqual(seen, [("SEED", ["甲"], "资讯服务")])

    def test_off_required_forwards_contains(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="off_required", only=["甲"],'
                     ' page="主题·设置", contains=true}]\n')
            phone.switches = lambda root=None: [("甲", True, (0, 0))]
            phone.scroll_more = lambda: False
            phone.top = lambda *a: None
            phone.off = lambda **kw: 2
            recipe.rt.require_switches = lambda before, names, title, **kw: seen.append(kw)
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        self.assertEqual(seen, [{"contains": True}])

    def test_close_listed_hands_the_phone_and_runtime_to_the_library(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            recipe, phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="close_listed", names=["甲"],'
                     ' page="服务管理", miss_print="没识别到"}]\n')

            def read_switches(p, rt, page):
                seen.append(("read", p, rt))
                return {"甲": True}

            def close_named(p, rt, names, page, **kw):
                seen.append(("close", p, rt))

            patch_library(self, read_switches=read_switches, close_named=close_named)
            with contextlib.redirect_stdout(io.StringIO()):
                recipe.run()
        self.assertEqual([item[0] for item in seen], ["read", "close"])
        for item in seen:
            self.assertIs(item[1], phone)
            self.assertIs(item[2], recipe.rt)

    def test_close_listed_empty_filter_prints_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe, _phone, _calls = _load_tmp(
                tmp, '[[segment]]\nname="a"\nops=[{kind="close_listed", names=["甲"],'
                     ' page="服务管理", miss_print="没识别到「甲」"}]\n')
            patch_library(self, read_switches=lambda p, rt, page: {},
                          close_named=lambda p, rt, *a, **k: None)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                recipe.run()
        self.assertIn("没识别到「甲」", out.getvalue())
        self.assertEqual(recipe.rt.failed_steps, ["a"])


if __name__ == "__main__":
    unittest.main()
