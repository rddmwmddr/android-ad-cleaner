"""跑一个模块的 mutation（#1411）：准备一个工作目录，跑 mutmut，把结局读回来。

用法：

    python3 devtools/mutation.py tool/catalog/schema.py [更多模块…]
    python3 devtools/mutation.py --since origin/main [--summary <文件>]

退出码：0 全部杀死、1 有存活 / 无测试 / 可疑 / 段错误、2 用错或 mutmut 自己没跑完。
`--summary <文件>` 把一节 markdown（含 pragma 计数）追加进去，CI 用它写 job summary。

`--since <ref>` 只跑 `git diff --name-only <ref>` 里落进映射表的模块；改动落在表外时
逐条报出来（数据改动与未立项的模块不在判据范围内，但要看得到）。行级筛选交给 mutmut 自己：
它按文件内容哈希重算 mutant、按 span 比对新旧，有缓存时只重测试改动行产生的那些（实测单行
0.75 s）；冷缓存时退化成该模块的全量（实测 schema 8.1 s）。

三条约束沿用 #1410 的实测结论：

- mutmut 3.8 的 mutant 名是「相对路径去掉 `src.` 前缀」，而测试按顶层模块名 import
  （`from catalog.schema import …`、`from gui import tasks`）。工作目录里的 `src` 是 `tool/`
  与 `gui/` 的镜像（目录真建、文件逐条链接），两边在同一视角上对齐，测试一行不改。
- mutmut 把 cwd 切到 `mutants/` 再跑 pytest，而测试要读仓库根的 `recipes/`、`docs/` 等
  数据目录，所以它们得进 `also_copy`。
- 缓存落在工作目录的 `mutants/` 下，跟着 `.mutmut/` 一起忽略，不在仓库根留下痕迹。

与覆盖率的分工是两层，缺一层就漏一类问题：覆盖率回答「新增代码有没有被执行到」，没测的代码
生成不出可杀的 mutant；mutation 回答「执行到的代码有没有断言守得住」，空覆盖只有它看得见。
PR 判据是两条都过，等价变异体是 mutation 侧唯一的豁免。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from collections.abc import Sequence

try:
    from . import mutation_scope
except ImportError:             # 直接跑文件时 sys.path[0] 就是 devtools/
    import mutation_scope

# 一个模块组一个工作目录：mutmut 用 mtime 判「这份副本还没变异」，共用目录时上一轮拷成
# 普通副本的文件会被当成都已变异，直接跑出 0 个 mutant。
WORKDIR = Path(".mutmut")
# 仓库根：`src` 镜像按它生成链接，测试传临时目录时仍然指回真源码。
ROOT = Path(__file__).resolve().parents[1]
# 进 `src` 视角的三个包（#1429、#1430）：`tool` 落在 `src/` 根上，`gui` 落在 `src/gui/`，
# `aac_android` 落在 `src/aac_android/`。手机版替换层不在仓库根（Chaquopy 的 sourceSets 要求它留在
# `android/app/src/main/python/` 下），这里只把它的基目录映射过来。
PACKAGE_BASES = {
    "tool": Path("tool"),
    "gui": Path("gui"),
    "aac_android": Path("android/app/src/main/python/aac_android"),
}
# 保持 tool、gui、aac_android 的顺序：字典按插入序迭代，镜像与映射都以这个顺序遍历。
SOURCE_PACKAGES = tuple(PACKAGE_BASES)
# 仓库根的数据目录，副本里要按 `src` 视角放一份：`gui/app.py` 用 `__file__` 的两级 dirname
# 定 `toolpath.BASE`，在副本里那是 `mutants/src`，读根目录数据的用例（`Api.env()` 的
# `images/dev-*`）才会在那里找。数据本身由 `ALSO_COPY` 拷进 `mutants/src/`。
ROOT_DATA = ("images",)
# 工作目录里指向仓库根的符号链接：mutmut 只认识 cwd 下的相对路径。
LINKS = {
    "tool": "tool",
    "tests": "tests",
    "recipes": "recipes",
    "docs": "docs",
    "devtools": "devtools",
    "recipe_lib": "recipe_lib",
    "gui": "gui",
    # 开发者模式的引导截图：`app.Api.env()` 从 `images/` 列出 `dev-*`，副本里缺它就会红
    "images": "images",
}
# 变异副本里跑测试要读到的东西。`mutants/` 下的测试会以它为根，缺一项就在收集期报错。
# `images` 拷两份：一份落在 `mutants/`（`toolpath.BASE` 按 `mutants/gui` 算时的视角），
# 一份落在 `mutants/src/`（按 `mutants/src/gui` 算时的视角），见 `ROOT_DATA`。
ALSO_COPY = ["recipe_lib", "recipes", "docs", "devtools", "gui", "images", "src/images"]
# `on_dependency_change` 必须是 `rerun`（默认 `warn`）：mutmut 用 git 比上次全量跑时的提交，
# 非 `.py` 文件变了只警告、保留旧裁决。本仓测试大量读 `recipes/`、`docs/`、`recipe_lib/`，
# 改了 recipe 却不重跑，`catalog/schema` 与 `recipe_source` 会拿旧结论报绿。
CONFIG = """\
# devtools/mutation.py 生成，改那里。
[tool.mutmut]
source_paths = ["src"]
only_mutate = [{}]
pytest_add_cli_args_test_selection = [{}]
also_copy = [{}]
on_dependency_change = "rerun"
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


def workdir_for(modules: Sequence[str]) -> Path:
    """一个模块组一个工作目录：`tool/catalog/schema.py` → `.mutmut/catalog_schema`。

    `gui/` 的模块保留前缀（`.mutmut/gui_tasks`）：两侧可能出现同名模块，共用目录会让上一轮的
    副本被当成已变异。
    """
    return WORKDIR / "-".join(_slug(module) for module in modules)


def _slug(module: str) -> str:
    name = module.removesuffix(".py")
    if name.startswith("tool/"):
        name = name[len("tool/"):]
    elif name.startswith("gui/"):
        name = "gui_" + name[len("gui/"):]
    elif name.startswith(mutation_scope.ANDROID_PREFIX):
        name = "aac_" + name[len(mutation_scope.ANDROID_PREFIX):]
    return name.replace("/", "_")


def link_sources(workdir: Path) -> None:
    """在工作目录里放好 `src` 镜像与测试 / 数据目录的链接。"""
    workdir.mkdir(parents=True, exist_ok=True)
    for name, target in LINKS.items():
        _link(workdir / name, Path("..") / ".." / target)
    _mirror_sources(workdir / "src")


def _mirror_sources(src: Path) -> None:
    """`tool/`、`gui/` 与手机版 `aac_android/` 的镜像：目录真建、文件逐条链接，跳过 `__pycache__`。

    mutmut 的 `os.walk` 不跟随目录符号链接（`followlinks=False`），所以不能放一条 `src -> tool`
    或 `src -> gui`：目录链接下它会报「0 files mutated」。镜像把三个包放进同一个视角——`tool/`
    的条目落在 `src/` 根上（测试按顶层包名 import），`gui/` 的条目落在 `src/gui/`（测试按
    `from gui import …`），`aac_android/` 的条目落在 `src/aac_android/`（测试按
    `from aac_android import …`；产品路径在 `android/app/src/main/python/` 下，见 `PACKAGE_BASES`）。
    每次按目录列表现生成，新增顶层模块自动进来。
    """
    if src.is_symlink() or src.is_file():
        src.unlink()
    elif src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True)
    for name in ROOT_DATA:
        (src / name).symlink_to(_relative(ROOT / name, src))
    for package in SOURCE_PACKAGES:
        base = ROOT / PACKAGE_BASES[package]
        top = src if package == "tool" else src / package
        for path in sorted(base.rglob("*")):
            if "__pycache__" in path.relative_to(base).parts:
                continue
            destination = top / path.relative_to(base)
            if path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(_relative(path, destination.parent))


def _relative(path: Path, folder: Path) -> str:
    """链接目标按物理路径算：macOS 的 `/var` 与 `/Volumes` 在逻辑路径上可能没有同一前缀。

    跨盘符（Windows 上仓库与临时目录各在一个盘）没有相对路径，退回绝对路径。
    """
    try:
        return os.path.relpath(path, folder.resolve())
    except ValueError:
        return str(path)


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


def stats(workdir: Path) -> dict[str, int] | None:
    """读回这次运行的结局计数。

    mutmut 只在真有 mutant 判定记录时才写这个 JSON：整份模块没有可变异节点、或者映射表里留着一个
    已经不存在的模块时，`export-cicd-stats` 只打一行提示就正常退出，不落盘。这里返回 `None`
    而不是让调用方在 `read_text` 上崩掉。
    """
    subprocess.run(
        [sys.executable, "-m", "mutmut", "export-cicd-stats"],
        cwd=workdir,
        capture_output=True,
    )
    path = workdir / "mutants" / "mutmut-cicd-stats.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def nothing_to_mutate(workdir: Path, modules: Sequence[str]) -> bool:
    """这些模块里没有一个可变异的函数。

    `reader.py` 是 `Protocol`，方法体只有 `...`，mutmut 生成不出 mutant，于是统计阶段收起
    0 条关联、退出码 1 并说「找不到任何测试」。那不是失败而是「没有东西可判」：用它的
    `hash_by_function_name` 空表认这一种，别把收集期真红掉的情况也放过。
    """
    for module in modules:
        meta = workdir / "mutants" / (mutation_scope.source_path(module) + ".meta")
        if not meta.exists():
            return False
        data = json.loads(meta.read_text(encoding="utf-8"))
        if data.get("hash_by_function_name"):
            return False
    return True


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
    """改动面分成两份：落进映射表的模块，以及没落的 `tool/` / `gui/` / 手机版模块（后者只作可见性提示）。

    `gui/` 里界壳文件、harmony 三份、手机版替换层里还没有行的模块都会逐条报出来：缺席要看得见
    （#1429、#1430）。
    """
    paths = changed_paths(ref)
    modules = mutation_scope.modules_in_paths(paths)
    roots = ("tool/", "gui/", mutation_scope.ANDROID_PREFIX)
    unmapped = [path for path in paths
                if path.startswith(roots) and path.endswith(".py")
                and path not in modules]
    return modules, unmapped


PRAGMA = "# pragma: no mutate"
USAGE = "python3 devtools/mutation.py tool/<模块>.py | --since <ref> [--summary <文件>]"
# 这些结局同样不该放行：mutmut 把认不出的退出码记成 suspicious，段错误单独一栏。
FAILING = ("survived", "no_tests", "suspicious", "segfault")


def pragmas(modules: Sequence[str]) -> int:
    """模块源码里 `# pragma: no mutate` 的条数。

    mutmut 3.8 不把 pragma 抑制记进 `skipped`（`__main__.py` 里还是 TODO），所以自己数——
    pragma 必须出现在 summary 里，否则它会变成藏污纳垢的地方。
    """
    return sum(Path(module).read_text(encoding="utf-8").count(PRAGMA) for module in modules)


def section(counts: dict[str, int], modules: list[str], pragma_total: int = 0) -> str:
    """CI summary 的一节：一行结论 + 全局计数。pragma 数必须在这里可见。"""
    if counts["survived"]:
        verdict = "有存活"
    elif counts["no_tests"]:
        verdict = "有 mutant 没有测试覆盖到"
    elif counts.get("suspicious") or counts.get("segfault"):
        verdict = "有未归类的结局"
    else:
        verdict = "全绿"
    lines = [
        "### 变异测试",
        "",
        f"{verdict}：{counts['total']} 个 mutant，杀死 {counts['killed']}、存活 {counts['survived']}、"
        f"无测试 {counts['no_tests']}、pragma 豁免 {pragma_total}、超时 {counts['timeout']}、"
        f"可疑 {counts.get('suspicious', 0)}、段错误 {counts.get('segfault', 0)}",
        "",
        f"模块：{' '.join(modules)}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    summary_path: Path | None = None
    if "--summary" in args:
        at = args.index("--summary")
        if at + 1 >= len(args):
            print("--summary 要带一个文件路径", file=sys.stderr)
            return 2
        summary_path = Path(args[at + 1])
        del args[at:at + 2]
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
        print(f"用法：{USAGE}", file=sys.stderr)
        return 2
    missing = mutation_scope.unknown(modules)
    if missing:
        print(f"不在映射表里：{' '.join(missing)}", file=sys.stderr)
        return 2
    gone = [module for module in modules if not Path(module).is_file()]
    if gone:
        print(f"映射表里的模块在仓库里不存在（表要跟着改）：{' '.join(gone)}", file=sys.stderr)
        return 2

    workdir = workdir_for(modules)
    link_sources(workdir)
    write_config(workdir, modules)
    code = run(workdir)
    if code != 0:
        if nothing_to_mutate(workdir, modules):
            print(f"无可变异节点：{' '.join(modules)} 里没有函数体可改，没有要判的 mutant")
            return 0
        # mutmut 自己的失败（没装、变异副本上收集就红）不是「有存活」，别让退出码骗人
        print(f"mutmut 没跑完（退出码 {code}），上面的日志里是原因", file=sys.stderr)
        return 2

    counts = stats(workdir)
    if counts is None:
        print("mutmut 没有产出任何 mutant 判定，检查 only_mutate 与模块是否还有可变异的函数",
              file=sys.stderr)
        return 2
    alive = survivors(workdir)
    pragma_total = pragmas(modules)
    print(
        f"共 {counts['total']} 个 mutant：杀死 {counts['killed']}、存活 {counts['survived']}、"
        f"无测试 {counts['no_tests']}、pragma 豁免 {pragma_total}、超时 {counts['timeout']}"
    )
    for name in alive:
        print(f"  存活 {name}")
    if summary_path is not None:
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(section(counts, modules, pragma_total) + "\n")
    return 1 if any(counts.get(key) for key in FAILING) else 0


if __name__ == "__main__":
    sys.exit(main())
