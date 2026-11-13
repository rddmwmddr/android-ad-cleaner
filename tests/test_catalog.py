"""catalog 内核（#1259）：页面树数据经唯一装载入口跑出与旧脚本逐条相同的调用序列，校验器在装载期
拒绝非法数据，`only` 两态（字面量 / 本机策略）与 UI「全部关闭」单列 page-wide。

判据只看外部行为：同一台合成手机、同一组读屏观察下的调用序列（复用 `compare_recipe_calls` 的记录
机制），以及数据经校验器后的接受 / 报错。不看解释器内部函数，也不看数据文件内部结构。
"""
import ast
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tool"))

import compare_recipe_calls as driver  # noqa: E402
import fixtures  # noqa: E402

fixtures.load_tool()
import catalog  # noqa: E402
import fast  # noqa: E402
import recipe_kit  # noqa: E402

SCRIPT = "tests/fixtures/vivo_v1986a/recipe.py"
DATA = "recipes/vivo/V1986A/V1986A.toml"


class EquivalenceTests(unittest.TestCase):
    """第一刀：一份手写转换的数据，在两场景下的调用序列与旧脚本逐条一致。"""

    def test_converted_data_reproduces_the_script_call_sequence(self):
        for scenario in driver.SCENARIOS:
            old = driver.run_script(fast, recipe_kit, fixtures, ROOT / SCRIPT, scenario)
            new = driver.run_script(fast, recipe_kit, fixtures, ROOT / DATA, scenario)
            self.assertTrue(old, f"{scenario}：旧脚本一条调用都没记到，对拍会空转")
            self.assertEqual(old, new, f"{scenario}：数据与旧脚本的调用序列不同")


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
                "def targets():\n    return ['A', 'B']\n",
            )
            recipe.run()
        self.assertEqual(calls, [("off", {"page": "p", "only": ["A", "B"]})])


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
        scope = "def try_off(name):\n    return ok\n"
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
            recipe.namespace["page"] = lambda *a, **k: seen.append((a, k))
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

    def _project(self, keep):
        """把 V1986A 的指定形态放进临时 recipes 目录，返回 (词库投影, 计数, 入口投影)。"""
        import shutil

        import entries
        import vocab
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "vivo" / "V1986A"
            model_dir.mkdir(parents=True)
            shutil.copy(ROOT / keep, model_dir / Path(keep).name)
            scan = vocab.scan(tmp)
            words = sorted((w.text, w.kind, w.family, w.group, w.page) for w in scan.words)
            counts = (scan.whole_page, len(scan.unresolved_only), len(scan.unresolved_close),
                      len(scan.unresolved_keep), sorted(scan.silent))
            return words, counts, entries.used_by(tmp)

    def test_toml_projects_the_same_words_as_py(self):
        self.assertEqual(self._project(SCRIPT), self._project(DATA))

    def test_scan_dir_handles_a_toml_model(self):
        import recipe_source
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "vivo" / "V1986A"
            model_dir.mkdir(parents=True)
            (model_dir / "V1986A.toml").write_text((ROOT / DATA).read_text(encoding="utf-8"), encoding="utf-8")
            facts = recipe_source.scan_dir(tmp)
            self.assertEqual(list(facts), ["vivo/V1986A/V1986A.toml"])
            self.assertTrue(any(call.name == "p.off" for call in facts["vivo/V1986A/V1986A.toml"].calls))

    def test_recipe_files_prefers_py_then_falls_back_to_toml(self):
        import recipe_meta
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "vivo" / "V1986A"
            model_dir.mkdir(parents=True)
            (model_dir / "recipe.py").write_text("MODELS = ['x']\n", encoding="utf-8")
            (model_dir / "V1986A.toml").write_text((ROOT / DATA).read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual([Path(p).name for p in recipe_meta.recipe_files(tmp)], ["recipe.py"])
            (model_dir / "recipe.py").unlink()
            self.assertEqual([Path(p).name for p in recipe_meta.recipe_files(tmp)], ["V1986A.toml"])

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
        """`.toml` 里每个 lib / require_lib 名都要经事实层解析到实现（入口归属的根因守护，#1263）。

        归属靠 `scan_catalog` 给 `Call.module` 盖章；漏盖时 `imported_sources()` 拿不到实现，
        入口速查会把这台机从「用过的机型」里静默删掉（`com.iqoo.secure` / `com.vivo.weather` 那次）。
        覆盖全部已转型号，不是抽查一份。"""
        import tomllib
        import recipe_source

        surface = recipe_source.surface_sources()

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
            facts = recipe_source.scan_catalog_file(str(toml))
            missing = wanted - set(recipe_source.imported_sources(facts, surface))
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
