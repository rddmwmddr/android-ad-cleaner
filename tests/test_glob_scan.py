"""发现式 glob 的反空转守卫（#1280）。

`for x in <发现>: ...` + `assertEqual(offenders, [])` 在发现集为空时与「全仓合规」不可区分：
B 段把 `recipe*.py` 换成 `<型号>.toml` 之后，三处守卫静默空转，CI 全绿而它们保护的东西
一件都没人看着。判据正文与豁免清单在 `devtools/glob_scan.py`。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

from devtools import glob_scan  # noqa: E402

# 探针文件替身：与真实测试同一副骨架（ROOT 由 __file__ 推），后面接一段发现式扫描。
PREAMBLE = "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ScanTests(unittest.TestCase):
    """扫描器自己的行为：什么算空转、什么还原得出来。"""

    def test_a_discovery_that_reaches_nothing_is_reported(self):
        """模式对真实仓库求值一次，0 份就是 offender——这一条就是票面要的那件事。"""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE + "hits = list((ROOT / 'recipes').glob('gone*.py'))\n")
            (Path(tmp) / "recipes").mkdir()
            report = glob_scan.scan(tmp)
            self.assertEqual([(f.where, f.pattern) for f in report.offenders],
                             [("tool/probe.py", "gone*.py")])
            self.assertEqual(report.checked, 1, "扫描器没把这一条算进覆盖数，覆盖数是它自己的护栏")

    def test_a_discovery_that_reaches_something_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE + "hits = list((ROOT / 'recipes').glob('*.toml'))\n")
            write(tmp, "recipes/model.toml", "[meta]\n")
            self.assertEqual(glob_scan.scan(tmp).offenders, [])

    def test_module_level_glob_function_is_not_mistaken_for_a_method(self):
        """`glob.glob(os.path.join(ROOT, ...))` 一直是仓库里的主流写法：它的第一个实参是
        完整模式，不能被读成「接收者叫 glob」而整个跳过。"""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE
                  + "import glob, os\nhits = glob.glob(os.path.join(ROOT, 'recipes', '*', '*.toml'))\n")
            write(tmp, "recipes/a/model.toml", "[meta]\n")
            report = glob_scan.scan(tmp)
            self.assertEqual(report.offenders, [])
            self.assertEqual(report.checked, 1)

    def test_loop_variables_expand_to_every_literal_folder(self):
        """`for folder in ('tool', 'gui')` 里每个值都要单独求值：只认第一个会把另一半放过。"""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE
                  + "for folder in ('tool', 'gui'):\n    hits = list((ROOT / folder).rglob('*.toml'))\n")
            write(tmp, "tool/a.toml", "")
            report = glob_scan.scan(tmp)
            self.assertEqual([f.base for f in report.offenders], [str(Path(tmp).resolve() / "gui")])

    def test_function_local_constant_and_its_default_are_resolved(self):
        """`root = Path(folder or ROOT) / 'recipes'`：形参取不到时跑的就是默认值，
        函数内的这个局部常量在仓库里是能算出来的。"""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tests/probe.py", PREAMBLE
                  + "def scan(folder=None):\n"
                    "    root = Path(folder or ROOT) / 'recipes'\n"
                    "    return sorted(root.glob('*/*/recipe*.py'))\n")
            write(tmp, "recipes/a/b/model.toml", "[meta]\n")
            report = glob_scan.scan(tmp)
            self.assertEqual([(f.where, f.pattern) for f in report.offenders],
                             [("tests/probe.py", "*/*/recipe*.py")])

    def test_a_runtime_default_is_not_guessed(self):
        """`root_from_env() or <默认>` 的运行时值可能根本不在仓库里，猜默认只会造误报。"""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE
                  + "import glob, os\n"
                    "def root_from_env():\n    return None\n"
                    "BACKUPS = root_from_env() or os.path.join(ROOT, 'backups')\n"
                    "hits = glob.glob(os.path.join(BACKUPS, '*', 'x.json'))\n")
            report = glob_scan.scan(tmp)
            self.assertEqual(report.offenders, [])
            self.assertEqual([s.where for s in report.skipped], ["tool/probe.py"])

    def test_a_self_referential_constant_is_skipped_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE
                  + "BASE = Path(BASE)\nhits = list(BASE.glob('*.toml'))\n")
            report = glob_scan.scan(tmp)
            self.assertEqual(report.offenders, [])
            self.assertEqual([s.where for s in report.skipped], ["tool/probe.py"])

    def test_a_double_star_without_recursive_is_not_counted_as_a_match(self):
        """`glob.glob` 的 `recursive` 默认是 False，`**` 只等价一层。扫描器必须照实参求值，
        否则运行期 0 份、扫描器却算命中，正是本票要防的那个方向。"""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE
                  + "import glob, os\n"
                    "hits = glob.glob(os.path.join(ROOT, 'tests', '**', '*.py'))\n")
            write(tmp, "tests/a/b/c.py", "x = 1\n")
            report = glob_scan.scan(tmp)
            self.assertEqual([f.key for f in report.offenders], ["tests/**/*.py"])

    def test_a_double_star_with_recursive_true_is_evaluated_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE
                  + "import glob, os\n"
                    "hits = glob.glob(os.path.join(ROOT, 'tests', '**', '*.py'), recursive=True)\n")
            write(tmp, "tests/a/b/c.py", "x = 1\n")
            self.assertEqual(glob_scan.scan(tmp).offenders, [])

    def test_path_with_several_arguments_is_joined_not_truncated(self):
        """`Path(ROOT, 'tests')` 等价于 `Path(ROOT / 'tests')`；只取第一个实参会在仓库根上求值。"""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE
                  + "hits = list(Path(ROOT, 'tests').glob('*.toml'))\n")
            write(tmp, "tests/a.toml", "")
            self.assertEqual(glob_scan.scan(tmp).offenders, [])

    def test_offender_keys_are_repo_relative_for_both_call_styles(self):
        """豁免键不能写死本机路径：方法档与模块档都换回相对仓库根的写法。"""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE
                  + "import glob, os\n"
                    "a = list((ROOT / 'recipes').glob('gone*.py'))\n"
                    "b = glob.glob(os.path.join(ROOT, 'recipes', 'gone*.toml'))\n")
            (Path(tmp) / "recipes").mkdir()
            keys = sorted(f.key for f in glob_scan.scan(tmp).offenders)
            self.assertEqual(keys, ["recipes/gone*.py", "recipes/gone*.toml"])
            self.assertNotIn(str(Path(tmp).resolve()), " ".join(keys))


class ExemptionTests(unittest.TestCase):
    """豁免只在「这个模式就该匹配 0 份」时使用，而且清单自己要防腐烂。"""

    def test_an_exempt_pattern_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tool/probe.py", PREAMBLE + "hits = list((ROOT / 'recipes').glob('gone*.py'))\n")
            (Path(tmp) / "recipes").mkdir()
            with patch.dict(glob_scan.EXEMPT, {("tool/probe.py", "recipes/gone*.py"): "负例夹具"},
                            clear=True):
                self.assertEqual(glob_scan.scan(tmp).offenders, [])

    def test_every_exemption_still_matches_nothing_on_the_real_repo(self):
        """把豁免拿掉再跑一遍：每条豁免都必须落在一个真的空匹配上，否则它就烂了。"""
        with patch.dict(glob_scan.EXEMPT, {}, clear=True):
            bare = glob_scan.scan(ROOT)
        stale_keys = [(f.where, f.key) for f in bare.offenders]
        for key in glob_scan.EXEMPT:
            self.assertIn(key, stale_keys, f"{key} 已经不再空转，把它从 EXEMPT 里删掉")


class RepoTests(unittest.TestCase):
    """对真实仓库的终局：现在起没有空转的发现式扫描。"""

    def test_the_repository_itself_is_clean(self):
        report = glob_scan.scan(ROOT)
        self.assertEqual([(f.where, f.lineno, f.pattern) for f in report.offenders], [])

    def test_the_repository_wide_discoveries_are_actually_evaluated(self):
        """全仓源码扫描是这批守卫里最要紧的几条：它们必须真的被算进覆盖，而不是落到 skipped。"""
        covered = {where for where, _ in glob_scan.scan(ROOT).covered}
        for where in ("tests/test_source_text.py",
                      "tests/test_subprocess_text_mode.py",
                      "tests/fixtures.py",
                      "devtools/typecheck_recipes.py"):
            self.assertIn(where, covered)

    def test_a_broken_pattern_in_a_real_guard_is_reported(self):
        """把真实仓库里一个有效模式改坏（gui → gone），守卫必须把它报出来。"""
        text = (ROOT / "tests" / "test_source_text.py").read_text(encoding="utf-8")
        broken = text.replace('("tool", "devtools", "gui", "tests")', '("tool", "devtools", "gone", "tests")')
        self.assertNotEqual(broken, text, "锚点改了：这条用例要跟着换一份真实的全仓扫描")
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "tests/test_source_text.py", broken)
            for folder in ("tool", "devtools", "gui", "tests"):
                (Path(tmp) / folder).mkdir(exist_ok=True)
            write(tmp, "tests/sample.py", "x = 1\n")
            report = glob_scan.scan(tmp)
        self.assertIn(("tests/test_source_text.py", "*.py"),
                      [(f.where, f.pattern) for f in report.offenders])
        self.assertIn(str(Path(tmp).resolve() / "gone"),
                      [f.base for f in report.offenders],
                      "报出来的应当是被改坏的那一支，不是 tool/ 或 tests/")

    def test_skipped_calls_are_named_so_the_gap_is_visible(self):
        """还原不出的调用不算失败，但要看得见：它们不在判据范围内，原因逐条写出来。"""
        report = glob_scan.scan(ROOT)
        for skipped in report.skipped:
            self.assertTrue(skipped.why, f"{skipped.where}:{skipped.lineno} 没说为什么跳过")
        print(f"\n[glob_scan] 覆盖 {report.checked} 处；不在判据范围内 {len(report.skipped)} 处")
        for skipped in report.skipped:
            print(f"  {skipped.where}:{skipped.lineno} {skipped.how} — {skipped.why}")


if __name__ == "__main__":
    unittest.main()
