"""The family container's own behaviour (#1395).

Every case here is driven by a fictional toy family (`sequence`), never by a real one:
the container must not know any concrete family's data shape, and these tests must not
depend on one either.
"""
import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import family  # noqa: E402


CASES = [
    {"id": "size-one", "size": 1},
    {"id": "size-two", "size": 2},
]
STRUCTURE = {("sequence", 1), ("sequence", 2)}


def handles(case):
    """Handles are derived from the case body, never written as literals."""
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
    """The snapshot a fully-updated toy family would have on disk."""
    return toy(cases=cases, with_output=with_output).snapshot("seed")


class IdViolationsTests(unittest.TestCase):
    def test_matching_ids_are_green(self):
        fam = toy()
        self.assertEqual(fam.id_violations(snapshot_of()), [])

    def test_a_deleted_case_is_reported_with_the_missing_id(self):
        snapshot = snapshot_of()
        fam = toy(cases=[CASES[0]])                       # size-two was deleted
        found = fam.id_violations(snapshot)
        self.assertTrue(found)
        self.assertIn("sequence", "\n".join(found))
        self.assertIn("size-two", "\n".join(found))

    def test_an_added_case_is_reported_with_its_id(self):
        snapshot = snapshot_of(cases=[CASES[0]])          # snapshot predates size-two
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
        fam = toy(structure={("sequence", 1)})            # ("sequence", 2) is gone
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
            fam = toy(root=root, cases=[CASES[1], CASES[0]])   # deliberately unsorted
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
            code, out, _err = self.run_cli(["--update", "--reason", "first seed"], fam)
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

    def test_plain_run_reports_each_check_and_its_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            fam = toy(root=Path(tmp))
            code, out, _err = self.run_cli([], fam)        # no snapshot on disk yet
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
                    code = family.cli(["--update", "--reason", "via main"])
            finally:
                sys.modules["__main__"] = original
            self.assertEqual(code, 0)
            self.assertTrue(fam.snapshot_path().exists())


PURE_GOOD = '''\
CASES = [
    {"id": "a", "value": 1, "tags": ["x", "y"], "flag": True, "none": None},
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

    def test_a_module_object_is_accepted_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "toy_cases.py"
            path.write_text(PURE_GOOD, encoding="utf-8")
            module = types.ModuleType("toy_cases")
            module.__file__ = str(path)
            self.assertEqual(family.pure_data_violations(module), [])


class NoConcreteFamilyTests(unittest.TestCase):
    """The container carries no concrete family's data shape or assertion method."""

    def test_the_container_names_no_real_family(self):
        source = (ROOT / "tests" / "family.py").read_text(encoding="utf-8").lower()
        for word in ("catalog", "vocab", "entries", "channel", "ops"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
