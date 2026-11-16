"""跑一个模块的 mutation（#1411）：准备一个工作目录，跑 mutmut，把结局读回来。

用法：

    python3 devtools/mutation.py tool/catalog/schema.py [更多模块…]
    python3 devtools/mutation.py --since origin/main

退出码：0 全部杀死、1 有存活或「no tests」、2 用的是错。

`--since <ref>` 只跑 `git diff --name-only <ref>` 里落进映射表的模块；改动落在表外时
逐条报出来（数据改动与未立项的模块不在判据范围内，但要看得到）。行级筛选交给 mutmut 自己：
它按文件内容哈希重算 mutant、按 span 比对新旧，有缓存时只重测试改动行产生的那些（实测单行
0.75 s）；冷缓存时退化成该模块的全量（实测 schema 8.1 s）。

三条约束来自 #1410 的实测：

- mutmut 3.8 的 mutant 名是「相对路径去掉 `src.` 前缀」，而测试按顶层模块名 import
  （`from catalog.schema import …`）。工作目录里放一个 `src -> tool` 符号链接，两边在同一
  视角上对齐，测试一行不改。
- mutmut 把 cwd 切到 `mutants/` 再跑 pytest，而测试要读仓库根的 `recipes/`、`docs/` 等
  数据目录，所以它们得进 `also_copy`。
- 缓存落在工作目录的 `mutants/` 下，跟着 `.mutmut/` 一起忽略，不在仓库根留下痕迹。
"""
import json
import subprocess
import sys
from pathlib import Path

try:
    from . import mutation_scope
except ImportError:             # 直接跑文件时 sys.path[0] 就是 devtools/
    import mutation_scope

WORKDIR = Path(".mutmut") / "work"
# 工作目录里指向仓库根的符号链接：mutmut 只认识 cwd 下的相对路径。
LINKS = ("tool", "tests", "recipes", "docs", "devtools", "recipe_lib")
# 变异副本里跑测试要读到的东西。`mutants/` 下的测试会以它为根，缺一项就在收集期报错。
ALSO_COPY = ["recipe_lib", "recipes", "docs", "devtools"]
CONFIG = """\
# devtools/mutation.py 生成，改那里。
[tool.mutmut]
source_paths = ["src"]
only_mutate = [{}]
pytest_add_cli_args_test_selection = [{}]
also_copy = [{}]
"""


def _toml_list(values) -> str:
    return ", ".join(f'"{value}"' for value in values)


def write_config(workdir: Path, modules: list[str]) -> None:
    """把这次要跑的模块与测试写成 mutmut 的配置。"""
    text = CONFIG.format(
        _toml_list(mutation_scope.only_mutate(modules)),
        _toml_list(mutation_scope.tests_for(modules)),
        _toml_list(ALSO_COPY),
    )
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "pyproject.toml").write_text(text, encoding="utf-8")


def link_sources(workdir: Path) -> None:
    """在工作目录里放好 `src -> tool` 与测试 / 数据目录的链接。"""
    workdir.mkdir(parents=True, exist_ok=True)
    for name in LINKS:
        _link(workdir / name, Path("..") / ".." / name)
    _link(workdir / "src", Path("..") / ".." / "tool")


def _link(path: Path, target: Path) -> None:
    if path.is_symlink() or path.exists():
        if path.is_symlink() and path.readlink() == target:
            return
        if path.is_symlink():
            path.unlink()
        else:
            return
    path.symlink_to(target)


def run(workdir: Path, extra: list[str] | None = None) -> int:
    """在 workdir 里跑 mutmut；返回它的退出码。"""
    completed = subprocess.run(
        [sys.executable, "-m", "mutmut", "run", *(extra or [])],
        cwd=workdir,
    )
    return completed.returncode


def stats(workdir: Path) -> dict[str, int]:
    """读回这次运行的结局计数。mutmut 自己的 summary 只在有 `export-cicd-stats` 时才落盘。"""
    subprocess.run(
        [sys.executable, "-m", "mutmut", "export-cicd-stats"],
        cwd=workdir,
        check=True,
        capture_output=True,
    )
    return json.loads((workdir / "mutants" / "mutmut-cicd-stats.json").read_text(encoding="utf-8"))


def survivors(workdir: Path) -> list[str]:
    """存活 mutant 的名字，逐条列出——补测试时要知道是哪一行、哪种变异。"""
    completed = subprocess.run(
        [sys.executable, "-m", "mutmut", "results"],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    found = []
    for line in completed.stdout.splitlines():
        name, _, status = line.strip().rpartition(": ")
        if status == "survived":
            found.append(name)
    return found


def changed_paths(ref: str) -> list[str]:
    """相对 `ref` 改过的文件，相对仓库根。用两点形式，未提交的改动也算进来。"""
    completed = subprocess.run(
        ["git", "diff", "--name-only", ref],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line for line in completed.stdout.splitlines() if line]


def scope_of(ref: str) -> tuple[list[str], list[str]]:
    """改动面分成两份：落进映射表的模块，以及没落的 `tool/` 模块（后者只作可见性提示）。"""
    paths = changed_paths(ref)
    modules = mutation_scope.modules_in_paths(paths)
    unmapped = [path for path in paths
                if path.startswith("tool/") and path.endswith(".py") and path not in modules]
    return modules, unmapped


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    unmapped: list[str] = []
    if args[:1] == ["--since"]:
        if len(args) != 2:
            print("--since 要带一个 ref", file=sys.stderr)
            return 2
        modules, unmapped = scope_of(args[1])
        if unmapped:
            print(f"改动里有不在映射表的模块（本次不判）：{' '.join(unmapped)}", file=sys.stderr)
        if not modules:
            print("改动没有落在映射表里的模块，没有要跑的 mutant")
            return 0
    else:
        modules = args
    if not modules:
        print(__doc__.split("用法：")[1].split("\n")[1].strip(), file=sys.stderr)
        return 2
    missing = mutation_scope.unknown(modules)
    if missing:
        print(f"不在映射表里：{' '.join(missing)}", file=sys.stderr)
        return 2

    link_sources(WORKDIR)
    write_config(WORKDIR, modules)
    code = run(WORKDIR)
    if code != 0:
        return code

    counts = stats(WORKDIR)
    alive = survivors(WORKDIR)
    print(
        f"共 {counts['total']} 个 mutant：杀死 {counts['killed']}、存活 {counts['survived']}、"
        f"pragma 跳过 {counts['skipped']}、超时 {counts['timeout']}、无测试 {counts['no_tests']}"
    )
    for name in alive:
        print(f"  存活 {name}")
    return 0 if counts["survived"] == 0 and counts["no_tests"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
