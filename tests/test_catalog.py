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
