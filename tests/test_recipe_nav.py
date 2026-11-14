"""公共导航的注入面（#1150）：`preamble()` 调 `recipe_nav.install()`，实现从执行作用域取前导
名字；脚本本地不许再留与注入面逐字相同的副本；调用序列对拍驱动自己管基线 worktree。

副本守卫的判据是代码逐字（AST 归一后再比）：注入面为空时全绿，搬进一个簇而脚本没删副本即红。
注释与文档串不算差异；同名多簇照旧合法 —— 代码写得不一样的是机型知识。
"""
import ast
import inspect
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fixtures  # noqa: E402
import recipe_kit  # noqa: E402
import recipe_nav  # noqa: E402
import recipe_source  # noqa: E402
import recipe_strategies  # noqa: E402
from fixtures import normalize, phone_mock  # noqa: E402

RECIPES = tuple(sorted((ROOT / "recipes").rglob("*.py")))


def families_missing_scripts(rel_paths, recipes_dir):
    """`recipes/` 下每个「含 .py」的家族目录，至少要在 rel_paths 里出现一份。

    这是发现口径的判据（#1263）：某个家族整块没扫到时这里红，而不是拿一个拍出来的总数下限兜底。
    返回「磁盘上有 .py、但 rel_paths 里一份都没有」的家族集合。"""
    on_disk = {d.name for d in recipes_dir.iterdir() if d.is_dir() and any(d.rglob("*.py"))}
    seen = set()
    for rel in rel_paths:
        parts = Path(rel).parts
        seen.add(parts[1] if parts and parts[0] == "recipes" else parts[0])
    return on_disk - seen


DRIVER = ROOT / "tests" / "compare_recipe_calls.py"
# 两张注入面各自的共享分节清单：recipe_nav / recipe_strategies 的 `SHARED` 由本文件消费（#1247）。
SURFACES = ((recipe_nav, recipe_source.NAV_MODULE, "NAV"),
            (recipe_strategies, recipe_source.STRATEGIES_MODULE, "STRATEGIES"))


def surface():
    """注入面此刻写进执行作用域的 {名字: 实现源码}。"""
    phone = phone_mock()
    scope = {}
    recipe_kit.preamble(phone, scope)
    return {name: normalize(inspect.getsource(scope[name])) for name in recipe_nav.NAV}


def kept_copies(scripts, injected):
    """脚本里与注入面逐字相同的模块级函数：{脚本相对路径: [名字]}。"""
    offenders = {}
    for label, source in scripts:
        local = {}
        for node in ast.parse(source, label).body:
            if isinstance(node, ast.FunctionDef):
                local[node.name] = normalize(ast.get_source_segment(source, node) or "")
        dup = sorted(name for name, text in local.items()
                     if name in injected and text == injected[name])
        if dup:
            offenders[label] = dup
    return offenders





class DriverTests(unittest.TestCase):
    def setUp(self):
        probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        if probe.returncode:
            self.skipTest("git archive 出来的干净副本没有 .git；这条只在 git 工作区里跑")

    def worktrees(self):
        return subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", check=True).stdout

    def test_unknown_sha_fails_without_leaving_a_worktree(self):
        before = self.worktrees()
        # 驱动自己把 stdio 转成 UTF-8；这里只负责按 UTF-8 解码（Windows 管道默认 cp1252）
        proc = subprocess.run([sys.executable, str(DRIVER), "--baseline", "0" * 40],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("找不到提交", proc.stderr)     # 守卫：走到了「拉基线失败」这一支
        self.assertEqual(self.worktrees(), before)

    def test_the_recorder_catches_a_script_calling_the_phone(self):
        """记录器真的记到了门面方法与 `p.d.shell`：一份脚本装载后既有段首的拉起，也有直发命令。"""
        import compare_recipe_calls as driver
        import fast
        calls = driver.run_script(fast, recipe_kit, fixtures,
                                  ROOT / "recipes" / "xiaomi/24090RA29C" / "24090RA29C.toml", "present")
        names = [call[1] for call in calls]
        self.assertIn("start", names)
        self.assertIn("entry", names)
        self.assertIn("d.shell", names)
        self.assertIn("系统广告", {call[0] for call in calls})
        self.assertGreater(len(calls), 40)

    def test_the_comparison_reports_drift_and_the_empty_comparison(self):
        """驱动自己的三条结论：序列不同、某个场景一条都没记到、总量低于下限 —— 都要报出来。"""
        import compare_recipe_calls as driver
        calls = [["段甲", "start", ["com.example.app"], {}]]
        base = {"a.py": {"present": calls, "absent": calls}}
        drifted = {"a.py": {"present": calls + [["段甲", "click", [1, 2], {}]], "absent": calls}}
        found, _ = driver.problems(base, drifted)
        self.assertTrue(any(summary.startswith("a.py[present]") for summary, _ in found), found)

        silent = {"a.py": {"present": calls, "absent": []}}
        found, _ = driver.problems(silent, silent)
        self.assertIn("一条调用都没记到", [summary for summary, _ in found])

        found, total = driver.problems(base, base)
        self.assertIn("没测到东西", [summary for summary, _ in found])
        self.assertLess(total, driver.MIN_CALLS)


if __name__ == "__main__":
    unittest.main()
