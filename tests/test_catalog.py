"""catalog 内核（#1259）：页面树数据经唯一装载入口跑出与旧脚本逐条相同的调用序列，校验器在装载期
拒绝非法数据，`only` 两态（字面量 / 本机策略）与 UI「全部关闭」单列 page-wide。

判据只看外部行为：同一台合成手机、同一组读屏观察下的调用序列（复用 `compare_recipe_calls` 的记录
机制），以及数据经校验器后的接受 / 报错。不看解释器内部函数，也不看数据文件内部结构。
"""
import ast
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tool"))

import fixtures  # noqa: E402

fixtures.load_tool()
import catalog  # noqa: E402
import fast  # noqa: E402

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


class ValidatorTests(unittest.TestCase):
    """种类白名单：未知键、非法形状在装载期就报，不等真机。"""

    def _bad(self, data, needle):
        with self.assertRaises(catalog.SchemaError) as caught:
            catalog.validate(data)
        self.assertIn(needle, str(caught.exception))

    def test_rejects_unknown_top_key(self):
        self._bad({"segment": [{"name": "a", "ops": []}], "surprise": 1}, "名单外的键")

    def test_rejects_unknown_op_kind(self):
        self._bad({"segment": [{"name": "a", "ops": [{"kind": "explode"}]}]}, "不在白名单")

    def test_rejects_off_without_naming(self):
        op = {"kind": "off", "page": "p"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "没点名")

    def test_rejects_off_with_only_and_keep_overlap(self):
        op = {"kind": "off", "only": ["x", "y"], "keep": ["y"], "page": "p"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "重叠")

    def test_rejects_duplicate_segment_names(self):
        data = {"segment": [{"name": "a", "ops": []}, {"name": "a", "ops": []}]}
        self._bad(data, "段名重复")

    def test_rejects_unknown_focus_match(self):
        op = {"kind": "if_focus", "text": "p", "match": "fnmatch"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "match='fnmatch' 认不出")

    def test_rejects_a_non_boolean_return_value(self):
        op = {"kind": "return", "value": "false"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "只能是 true / false")

    def test_rejects_page_without_args(self):
        op = {"kind": "page", "kwargs": {"activity": "X"}}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 args")

    def test_rejects_page_with_an_unknown_key(self):
        op = {"kind": "page", "args": ["X"], "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_rejects_skip_without_text(self):
        op = {"kind": "skip"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 text")

    def test_rejects_skip_with_an_unknown_key(self):
        op = {"kind": "skip", "text": "x", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_rejects_fail_without_text(self):
        op = {"kind": "fail"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 text")

    def test_rejects_fail_with_an_unknown_key(self):
        op = {"kind": "fail", "text": "x", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_rejects_require_tap_without_miss_print(self):
        op = {"kind": "require_tap", "text": "设置"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 miss_print")

    def test_rejects_require_tap_with_an_unknown_key(self):
        op = {"kind": "require_tap", "text": "x", "miss_print": "y", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_rejects_close_listed_without_names(self):
        op = {"kind": "close_listed", "page": "p", "miss_print": "y"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 names")

    def test_rejects_close_listed_with_an_unknown_key(self):
        op = {"kind": "close_listed", "names": ["a"], "page": "p", "miss_print": "y", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_accepts_the_shipped_data(self):
        import tomllib
        catalog.validate(tomllib.loads((ROOT / DATA).read_text(encoding="utf-8")))


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
    """`skip_unless_installed` op（#1266）：`if "package:" not in p.d.shell("pm path X").output: print; return`。

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
            phone.d.shell = lambda command, **kw: self._NS(output=output, exit_code=0)
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
    """新 op 的封闭清单（#1266）：缺键、名单外的键都在装载期报。"""

    def _bad(self, data, needle):
        with self.assertRaises(catalog.SchemaError) as caught:
            catalog.validate(data)
        self.assertIn(needle, str(caught.exception))

    def test_start_or_skip_requires_dead_ends(self):
        op = {"kind": "start_or_skip", "pkg": "p", "activity": "a", "reason": "r"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 dead_ends")

    def test_start_or_skip_rejects_an_unknown_key(self):
        op = {"kind": "start_or_skip", "pkg": "p", "activity": "a",
              "dead_ends": ["x"], "reason": "r", "surprise": 1}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "名单外的键")

    def test_skip_unless_installed_requires_the_marker(self):
        op = {"kind": "skip_unless_installed", "command": "pm path x", "text": "t"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 contains")

    def test_off_required_requires_only(self):
        op = {"kind": "off_required", "page": "p"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 only")

    def test_off_required_rejects_an_empty_only(self):
        op = {"kind": "off_required", "only": [], "page": "p"}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "非空")

    def test_if_setting_requires_the_keyword(self):
        op = {"kind": "if_setting", "ops": []}
        self._bad({"segment": [{"name": "a", "ops": [op]}]}, "缺 kw")

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
        self.assertIn('p.d.shell("am start -n com.android.settings/.ad.AdServiceSettings")', lowered)
        self.assertEqual([line for line in lowered.splitlines() if line.startswith("gear(")],
                         ["gear(p, rt)", "gear(p, rt)"])

    def test_if_setting_names_resolve_into_the_entry_facts(self):
        import recipe_source
        facts = recipe_source.scan_catalog(self.DATA)
        self.assertIn("p.setting", {call.name for call in facts.calls})


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
        import typecheck_recipes
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.toml"
            good.write_text((ROOT / DATA).read_text(encoding="utf-8"), encoding="utf-8")
            self.assertFalse(typecheck_recipes._check_catalog(str(good))[0])
            bad = Path(tmp) / "bad.toml"
            bad.write_text('model = "x"\n[[segment]]\nname = "s"\nops = [{kind = "nope"}]\n', encoding="utf-8")
            self.assertTrue(typecheck_recipes._check_catalog(str(bad))[0])

    def test_every_toml_lib_call_resolves_to_an_implementation(self):
        """`.toml` 里每个 lib / require_lib 名都要在库的 `__all__` 里（入口归属的根因守护）。

        数据显式点名实现，名字解析不到时入口速查会把这台机从「用过的机型」里静默删掉
        （`com.iqoo.secure` / `com.vivo.weather` 那次）。覆盖全部已转型号，不是抽查一份。"""
        import tomllib
        import recipe_source

        library = set(recipe_source.library_sources())

        def lib_names(ops):
            for op in ops:
                if op.get("kind") in ("lib", "require_lib") and "name" in op:
                    yield op["name"]
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


if __name__ == "__main__":
    unittest.main()
