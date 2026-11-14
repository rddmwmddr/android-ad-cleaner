"""机型库的拆分守卫（#1269）：实现按家族住在 `recipe_lib/<家族>.py` 与 `shared.py`。

两条判据，都按**实际调用点**算：

1. 升格（正向）：机型例外 `.py` 里的助手不许复制到第二台机。数据用 `code=` / `tail` / `guard`
   点名的过程化段体与水印钩子是这一台机的知识，不算助手；其余同名函数出现在 ≥2 台机型、
   或本地重定义了库实现，即红——它该升格进 `recipe_lib/<家族>.py` 或 `shared.py`。
2. 共享（反向）：`shared.py` 里的每个实现必须被 ≥2 个家族使用（家族取自 `entries.FAMILY`）；
   只服务一个家族的实现放该家族的家族文件。

家族文件里的实现不会收到从分派器进来的家族：分派器（`browser_settings` 等）按机型常量选家族
实现，那些实现各按自己所在的家族文件算。调用序列对拍驱动自己管基线 worktree（`DriverTests`）。
"""
import ast
import collections
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))          # recipe_lib 在仓库根

import entries  # noqa: E402
import recipe_audit  # noqa: E402
import recipe_lib  # noqa: E402
import recipe_source  # noqa: E402

RECIPES = ROOT / "recipes"
FAMILIES = set(entries.LABEL)
# 数据按名字点名的过程化钩子（`tail` / `guard` / `wrap` / `detail`）：它们是这一台机的知识。
# 名单的单一来源是 `recipe_audit.HOOK_NAMES`——另写一份时漏掉的名字（如 `wrap`）会被当成
# 「必须升格的助手」误报。
HOOK_KEYS = recipe_audit.HOOK_NAMES


def library_nodes():
    """{实现名: (家族 或 None, AST 节点)}。家族文件给家族名，`shared.py` 给 None。"""
    out = {}
    for module in recipe_lib.MODULES:
        name = module.__name__.rsplit(".", 1)[-1]
        family = name if name in FAMILIES else None
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[node.name] = (family, node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = (family, node)
    return out


def references(node, names):
    """一个实现里引用到的库实现名：调用与裸名取值都算，排除函数内自己绑定/嵌套定义的名字。"""
    assigned = {t.id for t in ast.walk(node)
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
    assigned |= {s.name for s in ast.walk(node)
                 if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    found = {sub.id for sub in ast.walk(node)
             if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load)
             and sub.id in names and sub.id not in assigned}
    found.discard(getattr(node, "name", ""))
    return found


def dispatched_hooks(model_dir):
    """这一台机的数据用 `code=` / `tail` / `guard` / `wrap` / `detail` 点名的过程化钩子名。"""
    hooks = set()
    for path in model_dir.glob("*.toml"):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        hooks |= {segment["code"] for segment in data.get("segment", []) if "code" in segment}
        hooks |= {data[key] for key in HOOK_KEYS if isinstance(data.get(key), str)}
    return hooks


def local_functions(model_dir):
    """例外 `.py` 里的模块级函数名（同一台机可能有多个变体文件）。"""
    out = set()
    for path in model_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out |= {node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return out


class PromotionTests(unittest.TestCase):
    def test_no_helper_is_copied_across_models(self):
        library = set(library_nodes())
        seen = collections.defaultdict(set)
        offenders = []
        for model_dir in sorted(path for path in RECIPES.glob("*/*") if path.is_dir()):
            model = model_dir.name
            hooks = dispatched_hooks(model_dir)
            for name in sorted(local_functions(model_dir) - hooks):
                if name in library:
                    offenders.append(f"{model}: 本地重定义了库实现 `{name}`，改用 recipe_lib")
                seen[name].add(model)
        for name, models in sorted(seen.items()):
            if len(models) >= 2:
                offenders.append(f"`{name}` 出现在 {len(models)} 台机型（{', '.join(sorted(models))}）"
                                 "却没进 recipe_lib：升格进家族库或 shared.py")
        self.assertEqual(offenders, [])

    def test_wrap_is_recognized_as_a_hook(self):
        """`wrap = "safe_ui"` 是声明式钩子（`recipe_audit.HOOK_NAMES`），不是要升格的助手。

        钩子名单另写一份时漏掉 `wrap`，`safe_ui` 就会被算成普通本机函数；它一旦被第二台机
        复用，上面那条会误报「出现在 ≥2 台机型却没进 recipe_lib」（#1269）。
        """
        self.assertIn("safe_ui", dispatched_hooks(RECIPES / "honor" / "WKL-AN20"))


class SharedLibraryTests(unittest.TestCase):
    def test_shared_impls_are_used_by_at_least_two_families(self):
        home = library_nodes()
        names = set(home)
        graph = {name: references(node, names) for name, (_family, node) in home.items()}
        usage = collections.defaultdict(set)
        for rel, facts in recipe_source.scan_dir(str(RECIPES), entries.FAMILY).items():
            family = entries.FAMILY[rel.split("/", 1)[0].lower()]
            for call in facts.calls:
                if call.injected and call.name in names:
                    usage[call.name].add(family)
        for name, (family, _node) in home.items():
            if family:
                usage[name].add(family)     # 家族实现至少被自己这个家族用到
        changed = True
        while changed:                      # 调用图闭包：分派器不把调用方的家族传给家族实现
            changed = False
            for name in names:
                for callee in graph[name]:
                    if home[callee][0]:
                        continue
                    added = usage[name] - usage[callee]
                    if added:
                        usage[callee] |= added
                        changed = True
        offenders = [f" shared.py 的 `{name}` 只被 {sorted(usage[name])} 用（需 ≥2 个家族）"
                     for name in sorted(names)
                     if home[name][0] is None and len(usage[name]) < 2]
        self.assertEqual(offenders, [])


DRIVER = ROOT / "tests" / "compare_recipe_calls.py"


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
        import fixtures
        import recipe_kit
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
