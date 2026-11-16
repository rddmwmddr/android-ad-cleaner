"""族容器自身的用例（#1395）。

这里每条用例都跑一个虚构的小族（`sequence`），从不跑真实族：容器不该知道任何具体族的数据形状，
这些用例同样不该依赖某一个。
"""
import importlib
import io
import json
import re
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import family  # noqa: E402
import catalog_family  # noqa: E402
import channel_policy_family  # noqa: E402
import entries_family  # noqa: E402
import vocab_family  # noqa: E402


# 本仓库承载的四个族。各自的测试文件还会断言自己那份 ``FAMILY.violations() == []``；
# 这个元组是 ``dev.tests.family-carries-cases`` 指向的聚合，一个族丢了快照或与快照漂移，
# 在这里一次看得见，不依赖那个族自己还留着检查。
FAMILIES = (
    catalog_family.FAMILY,
    vocab_family.FAMILY,
    entries_family.FAMILY,
    channel_policy_family.FAMILY,
)

# ``tests/family.py`` 里不许出现的具体族名字。用词边界而不是子串：``loops`` / ``stops``
# 这类将来会出现的词不该被误判成容器提了 ``ops``。
CONCRETE_FAMILY_WORDS = re.compile(r"\b(ops|catalog|vocab|entries|channel_policy)\b")


CASES = [
    {"id": "size-one", "size": 1},
    {"id": "size-two", "size": 2},
]
STRUCTURE = {("sequence", 1), ("sequence", 2)}


def handles(case):
    """句柄从 case 正文现算，从不写成字面量。"""
    return [("sequence", n) for n in range(1, case["size"] + 1)]


def produce(case):
    return "x" * case["size"]


def toy(root=None, cases=None, structure=STRUCTURE, expected=STRUCTURE, with_output=True):
    return family.Family(
        "sequence",
        list(CASES if cases is None else cases),
        handles=handles,
        structure=lambda: set(structure),
        produce=produce if with_output else None,
        expected=None if expected is None else (lambda: set(expected)),
        root=root,
    )


def snapshot_of(cases=None, with_output=True):
    """一个已完整更新过的虚构族该有的快照。"""
    return toy(cases=cases, with_output=with_output).snapshot("seed")


class IdViolationsTests(unittest.TestCase):
    def test_matching_ids_are_green(self):
        fam = toy()
        self.assertEqual(fam.id_violations(snapshot_of()), [])

    def test_a_deleted_case_is_reported_with_the_missing_id(self):
        snapshot = snapshot_of()
        fam = toy(cases=[CASES[0]])                       # size-two 被删了
        found = fam.id_violations(snapshot)
        self.assertTrue(found)
        self.assertIn("sequence", "\n".join(found))
        self.assertIn("size-two", "\n".join(found))

    def test_an_added_case_is_reported_with_its_id(self):
        snapshot = snapshot_of(cases=[CASES[0]])          # 快照早于 size-two
        fam = toy()
        found = fam.id_violations(snapshot)
        self.assertTrue(found)
        self.assertIn("size-two", "\n".join(found))

    def test_duplicate_ids_are_reported(self):
        fam = toy(cases=[CASES[0], CASES[0]])
        self.assertIn("size-one", "\n".join(fam.id_violations(snapshot_of())))

    def test_a_case_without_an_id_is_reported(self):
        fam = toy(cases=[{"size": 1}])
        found = fam.id_violations(snapshot_of())
        self.assertTrue(found)
        self.assertIn("sequence", "\n".join(found))


class HandleViolationsTests(unittest.TestCase):
    def test_declared_handles_all_exist_is_green(self):
        self.assertEqual(toy().handle_violations(), [])

    def test_a_handle_absent_from_the_structure_is_reported(self):
        fam = toy(structure={("sequence", 1)})            # ("sequence", 2) 不在了
        found = fam.handle_violations()
        self.assertTrue(found)
        text = "\n".join(found)
        self.assertIn("sequence", text)
        self.assertIn("size-two", text)
        self.assertIn("('sequence', 2)", text)


class OutputViolationsTests(unittest.TestCase):
    def test_matching_outputs_are_green(self):
        fam = toy()
        self.assertEqual(fam.output_violations(snapshot_of()), [])

    def test_changed_output_is_reported_with_the_case_id(self):
        snapshot = snapshot_of()
        snapshot["outputs"]["size-two"] = "wrong"
        fam = toy()
        found = fam.output_violations(snapshot)
        self.assertTrue(found)
        text = "\n".join(found)
        self.assertIn("sequence", text)
        self.assertIn("size-two", text)

    def test_missing_output_entry_is_reported(self):
        snapshot = snapshot_of()
        del snapshot["outputs"]["size-one"]
        found = toy().output_violations(snapshot)
        self.assertTrue(found)
        self.assertIn("size-one", "\n".join(found))

    def test_no_output_mode_is_always_green(self):
        fam = toy(with_output=False)
        snapshot = snapshot_of(with_output=False)
        self.assertEqual(fam.output_violations(snapshot), [])
        self.assertNotIn("outputs", snapshot)


class GapViolationsTests(unittest.TestCase):
    def test_a_fully_covered_structure_is_green(self):
        self.assertEqual(toy().gap_violations(), [])

    def test_a_new_structure_item_without_a_case_is_reported(self):
        grown = STRUCTURE | {("sequence", 3)}
        fam = toy(structure=grown, expected=grown)
        found = fam.gap_violations()
        self.assertTrue(found)
        text = "\n".join(found)
        self.assertIn("sequence", text)
        self.assertIn("('sequence', 3)", text)

    def test_no_expected_callable_means_no_gap_check(self):
        self.assertEqual(toy(expected=None).gap_violations(), [])


class SnapshotFormatTests(unittest.TestCase):
    def test_ids_are_sorted_and_serialization_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fam = toy(root=root, cases=[CASES[1], CASES[0]])   # 故意无序
            snapshot = fam.snapshot("order")
            self.assertEqual(snapshot["ids"], ["size-one", "size-two"])
            self.assertEqual(list(snapshot["outputs"]), ["size-one", "size-two"])
            first = fam.write("order")
            before = first.read_bytes()
            fam.write("order")
            self.assertEqual(first.read_bytes(), before)
            self.assertEqual(first.parent, root / "tests" / "snapshots")
            self.assertTrue(before.endswith(b"\n"))

    def test_the_file_holds_reason_ids_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            path = fam.write("seed reason")
            doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["reason"], "seed reason")
        self.assertEqual(doc["ids"], ["size-one", "size-two"])
        self.assertEqual(doc["outputs"], {"size-one": "x", "size-two": "xx"})


class CliTests(unittest.TestCase):
    def run_cli(self, argv, fam):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = family.cli(argv, family=fam)
        return code, out.getvalue(), err.getvalue()

    def test_update_writes_the_snapshot_and_turns_the_checks_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            code, out, _err = self.run_cli(["--update", "--reason", "first seed (#1395)"], fam)
            self.assertEqual(code, 0)
            self.assertTrue(fam.snapshot_path().exists())
            self.assertEqual(fam.violations(), [])
            self.assertIn(str(fam.snapshot_path()), out)

    def test_update_without_a_reason_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            code, _out, err = self.run_cli(["--update"], fam)
            self.assertNotEqual(code, 0)
            self.assertIn("--reason", err)
            self.assertFalse(fam.snapshot_path().exists())

    def test_update_with_a_blank_reason_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            code, _out, err = self.run_cli(["--update", "--reason", "   "], fam)
            self.assertNotEqual(code, 0)
            self.assertIn("--reason", err)
            self.assertFalse(fam.snapshot_path().exists())

    def test_update_with_a_reason_without_a_ticket_is_refused(self):
        """只有非空不够：`--reason "x"` 也能对不上任何票，等于橡皮图章。"""
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            code, _out, err = self.run_cli(["--update", "--reason", "x"], fam)
            self.assertEqual(code, 2)
            self.assertIn("--reason", err)
            self.assertIn("票号", err)
            self.assertFalse(fam.snapshot_path().exists())

    def test_update_accepts_a_reason_carrying_a_ticket(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            code, _out, _err = self.run_cli(["--update", "--reason", "seed (#1395)"], fam)
            self.assertEqual(code, 0)
            self.assertEqual(fam.read()["reason"], "seed (#1395)")

    def test_plain_run_reports_each_check_and_its_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            code, out, _err = self.run_cli([], fam)        # 盘上还没有快照
            self.assertEqual(code, 1)
            self.assertIn("ids", out)
            self.assertIn("handles", out)
            self.assertIn("outputs", out)
            self.assertIn("gaps", out)

    def test_plain_run_is_green_after_the_snapshot_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            fam.write("seed")
            code, _out, _err = self.run_cli([], fam)
            self.assertEqual(code, 0)

    def test_without_a_family_the_cli_fails_readably(self):
        original = sys.modules.get("__main__")
        sys.modules["__main__"] = types.ModuleType("__main__")
        try:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = family.cli([])
        finally:
            sys.modules["__main__"] = original
        self.assertNotEqual(code, 0)
        self.assertIn("FAMILY", err.getvalue())

    def test_a_main_module_holding_family_is_picked_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            original = sys.modules.get("__main__")
            main = types.ModuleType("__main__")
            main.FAMILY = fam
            sys.modules["__main__"] = main
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    code = family.cli(["--update", "--reason", "via main (#1395)"])
            finally:
                sys.modules["__main__"] = original
            self.assertEqual(code, 0)
            self.assertTrue(fam.snapshot_path().exists())


PURE_GOOD = '''\
CASES = [
    {"id": "a", "value": 1, "tags": ["x", "y"], "flag": True, "none": None, "pair": (1, 2)},
    {"id": "b", "value": -2.5, "nested": {"k": [1, 2]}},
]
'''

PURE_WITH_LAMBDA = '''\
CASES = [{"id": "a", "check": lambda value: value > 0}]
'''

PURE_WITH_NAME = '''\
LIMIT = 3
CASES = [{"id": "a", "value": LIMIT}]
'''

# 追加一行能绕过纯数据检查：新行的 lambda 不在任何模块级赋值里。
PURE_WITH_APPEND = '''\
CASES = [{"id": "a", "value": 1}]
CASES.append({"id": "b", "check": lambda value: value > 0})
'''

# 下标赋值同理：目标不是裸名字，旧的检查直接跳过它。
PURE_WITH_ITEM_ASSIGN = '''\
CASES = [{"id": "a", "value": 1}]
CASES[0]["evil"] = lambda: 42
'''

# 对导入模块调方法必须继续放行：族模块都靠它在 sys.path 上找 family 与 tool/。
PURE_WITH_IMPORT_CALL = '''\
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
'''

# set 不可 JSON 序列化，与快照写盘口径不一致（ADR-0042）。
PURE_WITH_SET = '''\
CASES = [{"id": "a", "tags": {"x", "y"}}]
'''


class PureDataTests(unittest.TestCase):
    def check(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "toy_cases.py"
            path.write_text(source, encoding="utf-8")
            return family.pure_data_violations(path)

    def test_pure_literals_are_green(self):
        self.assertEqual(self.check(PURE_GOOD), [])

    def test_a_lambda_is_reported(self):
        found = self.check(PURE_WITH_LAMBDA)
        self.assertTrue(found)
        self.assertIn("toy_cases", "\n".join(found))

    def test_a_reference_to_another_name_is_reported(self):
        found = self.check(PURE_WITH_NAME)
        self.assertTrue(found)
        self.assertIn("LIMIT", "\n".join(found))

    def test_a_module_level_append_is_reported(self):
        """`CASES.append({... "check": lambda ...})` 能往表里追加带行为的一行，必须判违规。"""
        found = self.check(PURE_WITH_APPEND)
        self.assertTrue(found)
        text = "\n".join(found)
        self.assertIn("append", text)
        self.assertIn("toy_cases", text)

    def test_an_assignment_through_a_subscript_is_reported(self):
        """`CASES[0]["evil"] = lambda: 42` 的目标不是裸名字，旧检查跳过它。"""
        found = self.check(PURE_WITH_ITEM_ASSIGN)
        self.assertTrue(found)
        self.assertIn("赋值目标不是裸名字", "\n".join(found))

    def test_a_call_on_an_imported_name_is_allowed(self):
        self.assertEqual(self.check(PURE_WITH_IMPORT_CALL), [])

    def test_a_set_literal_is_reported(self):
        found = self.check(PURE_WITH_SET)
        self.assertTrue(found)
        self.assertIn("set", "\n".join(found))

    def test_a_module_object_is_accepted_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "toy_cases.py"
            path.write_text(PURE_GOOD, encoding="utf-8")
            module = types.ModuleType("toy_cases")
            module.__file__ = str(path)
            self.assertEqual(family.pure_data_violations(module), [])


class NoConcreteFamilyTests(unittest.TestCase):
    """容器不承载任何具体族的数据形状或断言方法。"""

    def test_the_container_names_no_real_family(self):
        source = (ROOT / "tests" / "family.py").read_text(encoding="utf-8").lower()
        hit = CONCRETE_FAMILY_WORDS.search(source)
        self.assertIsNone(hit, f"tests/family.py 提到了具体族的名字：{hit.group(0) if hit else ''}")

    def test_the_pattern_still_catches_the_words_the_real_families_carry(self):
        """四个真实族模块里就是这么写这些名字的：守卫换成词边界后对它们仍然有效。

        子串口径会把 `loops` / `stops` 误判成 `ops`，词边界口径不会；这条同时钉住后者没有
        变松——名字真的出现时必须命中。"""
        for path in sorted((ROOT / "tests").glob("*_family.py")):
            if path.name.startswith("test_"):
                continue
            module = importlib.import_module(path.stem)
            source = Path(module.__file__).read_text(encoding="utf-8").lower()
            hit = CONCRETE_FAMILY_WORDS.search(source)
            self.assertIsNotNone(hit, f"{path.name} 里一个具体族名字都没命中，守卫的口径不对")


class FamilyRegistryTests(unittest.TestCase):
    """本仓库承载的每个族都与各自的快照对得上。

    ``violations()`` 一次查三件事：case id 集合对快照、每条声明的句柄对结构、产出对快照
    （可选的第四件是从结构反推的缺口）。这也是 ``dev.tests.family-carries-cases`` 背后的检查。
    """

    def test_every_family_matches_its_snapshot(self):
        self.assertEqual([v for f in FAMILIES for v in f.violations()], [])

    def test_every_family_has_a_snapshot_on_disk(self):
        self.assertEqual([f.name for f in FAMILIES if f.read() is None], [])

    def test_every_family_module_is_registered(self):
        """`FAMILIES` 是手写元组：新族漏登记会静默逃出 `dev.tests.family-carries-cases` 的检查。

        两个方向都查：盘上每个族模块都要有 `FAMILY` 且在元组里，元组里也不许有盘上找不到的族。
        """
        modules = sorted(path for path in (ROOT / "tests").glob("*_family.py")
                         if not path.name.startswith("test_"))
        self.assertTrue(modules, "tests/ 下一个族模块都没扫到：发现口径坏了")
        discovered = []
        for path in modules:
            module = importlib.import_module(path.stem)
            self.assertTrue(hasattr(module, "FAMILY"), f"{path.name} 没有模块级 FAMILY")
            discovered.append(module.FAMILY)
        self.assertEqual({id(item) for item in discovered}, {id(item) for item in FAMILIES},
                         "tests/*_family.py 与 FAMILIES 元组不是同一批族：新族要在 "
                         "tests/test_family.py 的 FAMILIES 里登记")


if __name__ == "__main__":
    unittest.main()
