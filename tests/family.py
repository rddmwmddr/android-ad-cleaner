"""The family container (#1395).

A family is a table of case rows plus a few callables that tie each row to the code
under test:

* ``handles(case)``  -> the structural items the case depends on,
* ``structure()``    -> the structural items that exist right now,
* ``produce(case)``  -> an optional comparable outcome per case,
* ``expected()``     -> an optional set derived from the structure, used to demand a
                        case for every structural item ("a new item needs a case").

The container owns only the lifecycle: case ids against a snapshot, declared handles
against the structure, outcomes against the snapshot, and gaps in the structure. It
knows nothing about how to run the code under test, and nothing about any concrete
family's data shape or assertion method.

A family module looks like this::

    import sys
    from family import Family, cli

    CASES = [{"id": "...", ...}, ...]
    FAMILY = Family("name", CASES, handles=..., structure=..., produce=..., expected=...)

    if __name__ == "__main__":
        sys.exit(cli())

The snapshot lives at ``tests/snapshots/<name>.json`` and is written only through
``python3 tests/<family module>.py --update --reason "..."``. The reason is mandatory:
updating a snapshot must never become a rubber stamp. Running the module without
arguments prints the four checks for a human read.
"""
import ast
import json
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]

_PURE_SCALARS = (str, int, float, bool, type(None))


class Family:
    """One table of case rows and the checks that keep it honest."""

    def __init__(self, name, cases, *, handles, structure, produce=None, expected=None, root=None):
        self.name = name
        self.cases = list(cases)
        self._handles = handles
        self._structure = structure
        self._produce = produce
        self._expected = expected
        self.root = DEFAULT_ROOT if root is None else Path(root)

    # ---------- snapshot file ----------

    def snapshot_path(self):
        return self.root / "tests" / "snapshots" / f"{self.name}.json"

    def snapshot(self, reason):
        """The document that should be on disk for the current rows (sorted, stable)."""
        ordered = sorted(self.cases, key=lambda case: case["id"])
        document = {"reason": reason, "ids": [case["id"] for case in ordered]}
        if self._produce is not None:
            document["outputs"] = {case["id"]: self._produce(case) for case in ordered}
        return document

    def read(self):
        path = self.snapshot_path()
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, reason):
        path = self.snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.snapshot(reason), ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        return path

    # ---------- the four checks: each returns a list of violations ----------

    def id_violations(self, snapshot=None):
        snapshot = self.read() if snapshot is None else snapshot
        if snapshot is None:
            return [self._no_snapshot()]
        found = []
        seen = set()
        for index, case in enumerate(self.cases):
            case_id = case.get("id")
            if not isinstance(case_id, str) or not case_id:
                found.append(f"{self.name}: case at index {index} has no stable string id")
            elif case_id in seen:
                found.append(f"{self.name}: duplicate case id {case_id!r}")
            else:
                seen.add(case_id)
        recorded = set(snapshot.get("ids", []))
        for case_id in sorted(seen - recorded):
            found.append(f"{self.name}: case id {case_id!r} is not in the snapshot "
                         "(new case: update the snapshot with --reason ...)")
        for case_id in sorted(recorded - seen):
            found.append(f"{self.name}: snapshot id {case_id!r} has no matching case "
                         "(case deleted: update the snapshot with --reason ...)")
        return found

    def handle_violations(self):
        actual = set(self._structure())
        found = []
        for case in self.cases:
            case_id = case.get("id")
            for handle in self._handles(case):
                if handle not in actual:
                    found.append(f"{self.name}: case {case_id!r} declares handle {handle!r} "
                                 "which the structure does not have")
        return found

    def output_violations(self, snapshot=None):
        if self._produce is None:
            return []
        snapshot = self.read() if snapshot is None else snapshot
        if snapshot is None:
            return [self._no_snapshot()]
        recorded = snapshot.get("outputs", {})
        found = []
        for case in self.cases:
            case_id = case.get("id")
            if not isinstance(case_id, str):
                continue
            if case_id not in recorded:
                found.append(f"{self.name}: case {case_id!r} has no outcome in the snapshot")
                continue
            produced = self._produce(case)
            if produced != recorded[case_id]:
                found.append(f"{self.name}: case {case_id!r} produced {produced!r} "
                             f"but the snapshot has {recorded[case_id]!r}")
        return found

    def gap_violations(self):
        if self._expected is None:
            return []
        covered = set()
        for case in self.cases:
            covered.update(self._handles(case))
        missing = self._expected() - covered
        return [f"{self.name}: structure handle {handle!r} has no case (add one)"
                for handle in sorted(missing, key=repr)]

    def violations(self):
        snapshot = self.read()
        return (self.id_violations(snapshot) + self.handle_violations()
                + self.output_violations(snapshot) + self.gap_violations())

    def _no_snapshot(self):
        return (f"{self.name}: no snapshot at {self.snapshot_path()} "
                "(create it with --update --reason ...)")


def _family_from_main():
    main = sys.modules.get("__main__")
    return getattr(main, "FAMILY", None) if main is not None else None


def _parse(argv):
    """Return (update, reason, error); error is a message or None."""
    update, reason, index = False, None, 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--update":
            update = True
        elif argument == "--reason":
            index += 1
            if index >= len(argv):
                return update, reason, "--reason needs a value"
            reason = argv[index]
        elif argument.startswith("--reason="):
            reason = argument[len("--reason="):]
        else:
            return update, reason, f"unknown argument {argument!r} (only --update / --reason)"
        index += 1
    return update, reason, None


def cli(argv=None, family=None):
    """Update or inspect one family's snapshot; returns a process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    chosen = family if family is not None else _family_from_main()
    if chosen is None:
        print("family: no family to work on; run this through a family module that "
              "defines FAMILY at module level", file=sys.stderr)
        return 2
    update, reason, error = _parse(argv)
    if error:
        print(f"family: {error}", file=sys.stderr)
        return 2
    if update:
        if reason is None or not reason.strip():
            print("family: --update needs a non-empty --reason", file=sys.stderr)
            return 2
        path = chosen.write(reason.strip())
        print(f"family: wrote {path}")
        return 0
    checks = (
        ("ids", chosen.id_violations()),
        ("handles", chosen.handle_violations()),
        ("outputs", chosen.output_violations()),
        ("gaps", chosen.gap_violations()),
    )
    failures = 0
    for label, found in checks:
        print(f"[{label}]")
        if not found:
            print(f"{chosen.name}: {label} ok")
        for line in found:
            print(line)
        failures += len(found)
    return 0 if not failures else 1


def _is_family_construction(node):
    if not isinstance(node, ast.Call):
        return False
    target = node.func
    return ((isinstance(target, ast.Name) and target.id == "Family")
            or (isinstance(target, ast.Attribute) and target.attr == "Family"))


def _impure(node):
    """A short reason if `node` is not a pure-data literal, else None."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, _PURE_SCALARS):
            return None
        return f"a constant of type {type(node.value).__name__}"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for item in node.elts:
            if isinstance(item, ast.Starred):
                return "a starred value"
            bad = _impure(item)
            if bad:
                return bad
        return None
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                return "a dict unpacking"
            bad = _impure(key) or _impure(value)
            if bad:
                return bad
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = node.operand
        if (isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float))
                and not isinstance(operand.value, bool)):
            return None
        return "a unary operation on a non-number"
    if isinstance(node, ast.Name):
        return f"a reference to the name {node.id!r}"
    return f"a {type(node).__name__} node"


def pure_data_violations(module_or_path):
    """Case rows must be plain literals: no lambda, no call, no name reference.

    Every module-level assignment except the ``Family(...)`` construction itself is
    checked, so a row cannot smuggle behaviour in through a helper constant either.
    """
    path = Path(getattr(module_or_path, "__file__", module_or_path))
    label = getattr(module_or_path, "__name__", path.stem)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        return [f"{label}: cannot read {path}: {exc}"]
    found = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not all(isinstance(target, ast.Name) for target in node.targets):
                continue
            names = [target.id for target in node.targets]
            value = node.value
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
              and node.value is not None):
            names = [node.target.id]
            value = node.value
        else:
            continue
        if _is_family_construction(value):
            continue
        reason = _impure(value)
        if reason:
            for name in names:
                found.append(f"{label}: row data {name!r} at line {node.lineno} holds "
                             f"{reason}; case rows must be plain literals")
    return found
