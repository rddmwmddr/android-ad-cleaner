"""公共导航搬动前后的调用序列对拍（#1148 / #1150）：同一份机型脚本分别用基点与工作区装载一次，
比较脚本在 `p.*` 上发出的调用（方法名 + 参数 + 顺序）。零差异才算搬动没改行为。

基线取本分支的基点，不入库快照文件。驱动自己拉临时 worktree、跑完删掉：

    git fetch origin main
    python tests/compare_recipe_calls.py --baseline <git merge-base HEAD origin/main>

也可以手工备好一份 worktree，把它的根目录传进来：

    git worktree add /tmp/aac-baseline <基点 SHA>
    python tests/compare_recipe_calls.py /tmp/aac-baseline

两边各起一个子进程：模块名相同，同进程里 import 不了两份 `fast`。脚本用 `fixtures.fake_phone()`
装载（空页面 + 假钟），型号守卫读到的 shell 输出一律算「对得上」；入口、拉起与落点这几处
门面观察再换成都成功（`rehearsal()`），脚本才会沿自己的分支走到底、真的调到它本地的助手 ——
否则 `p.start` 一失败整段就停，被搬动的助手一次也不会被调用，对拍等于空转。
记录的是脚本调用门面的动作；`p.d.shell(...)` 这类不经门面的命令不在内。空页面上「要点名开关」
的深支也走不到（名单读不到就按失败结束），所以开关拨动本身不在对拍范围内 —— 它盯的是脚本与
公共导航在门面上的调用序列。

守卫：每份脚本都要记到至少一条调用，全部脚本加起来不到 MIN_CALLS 条就算没测到 —— 只报「两边
一样」而没有调用量，说明对拍是空转的。
"""
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path.insert(0, str(ROOT / "tool"))
from stdio import use_utf8_console  # noqa: E402  出口取当前副本的，不对拍基线那一份

use_utf8_console()

# 43 份 `recipe.py` 加 4 份变体实测约 7000 条调用；低于这个数说明记录或装载退化了
MIN_CALLS = 1000


class AnyText(str):
    """型号 / 版本读数：脚本拿它比对时一律算对得上（这里不比各家族的判据）。"""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__

    def startswith(self, prefix, *args, **kwargs):
        return True

    def strip(self, *args, **kwargs):
        return self


def probe_shell(command, timeout=None):
    return SimpleNamespace(output=AnyText("package: probe"), exit_code=0)


def rehearsal(phone):
    """把挡住段首的几处观察换成「都成功」，脚本才会走到它自己的助手。

    `p.start`、按文字找入口与点按在空页面上都会失败，段体随即 return；对拍要比的是脚本自身
    调用门面的顺序，不是引擎在这台空手机上做得对不对，所以这几处一律算成功（落点跟着
    `start()` 的包名走，脚本里 `p.focus().split("/")[0] == package` 那类判据才过得了）。
    观察类的 `tree` / `texts` / `switches` 不换 —— 它们给出真实但空的一页，循环照样会停。
    """
    state = {"focus": "com.example.app/.MainActivity"}

    def start(pkg, activity=None, *args, **kwargs):
        state["focus"] = f"{pkg}/{activity or '.MainActivity'}"

    for name, value in {
            "start": start,
            "focus": lambda *a, **k: state["focus"],
            "entry": lambda *a, **k: True,
            "tap": lambda *a, **k: True,
            "go": lambda *a, **k: True,
            "enter": lambda *a, **k: True,
            "tab": lambda *a, **k: True,
            "tap_icon": lambda *a, **k: True,
            "find": lambda *a, **k: True,
            "settle": lambda *a, **k: True,
            "has_text": lambda *a, **k: True,
            "expect_page": lambda *a, **k: True,
    }.items():
        setattr(phone, name, value)


def norm(value):
    """调用参数的可比形态：页面节点按原文比，容器递归，认不出的只记类型名（地址不可比）。"""
    if isinstance(value, ET.Element):
        return ET.tostring(value, encoding="unicode")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [norm(v) for v in value]
    if isinstance(value, dict):
        return {str(k): norm(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    return f"<{type(value).__name__}>"


def recording(phone):
    """包住门面上的公开方法，记下 (名字, 参数, 关键字参数) 的调用顺序。"""
    log = []

    def wrap(name, call):
        def recorder(*args, **kwargs):
            log.append([name, norm(list(args)), {k: norm(v) for k, v in kwargs.items()}])
            return call(*args, **kwargs)
        return recorder

    for name in dir(phone):
        if name.startswith("_") or isinstance(getattr(type(phone), name, None), property):
            continue
        call = getattr(phone, name)
        if callable(call):
            setattr(phone, name, wrap(name, call))
    return log


def run_script(fast, recipe_kit, fixtures, path):
    """装载一份脚本（全部段都跑），返回它在门面上留下的调用序列。"""
    phone = fixtures.fake_phone(clock=fixtures.Clock(), fast_mod=fast)
    phone.d.shell = probe_shell
    phone.link = fast.adb_link.Connection("fake", transport=probe_shell)
    rehearsal(phone)
    log = recording(phone)
    fixtures.load_recipe(phone, path, only=[])
    return log


def dump(root):
    """给定仓库根，装载它自己的 `recipes/` 与 `tool/`，交出 {脚本相对路径: 调用序列}。"""
    root = Path(root).resolve()
    sys.path.insert(0, str(TESTS))
    import fixtures
    fixtures.load_tool()                    # 先让当前树的 tool 就位，load_recipe 不再把它插到最前
    sys.path.insert(0, str(root / "tool"))  # 目标树压过它：脚本与引擎都取这一份
    import fast
    import recipe_kit
    for module in (fast, recipe_kit):
        if not Path(module.__file__).resolve().is_relative_to(root):
            sys.exit(f"{module.__name__} 取到的不是 {root} 那份：sys.path 上有别的 tool/")
    return {path.relative_to(root).as_posix(): run_script(fast, recipe_kit, fixtures, path)
            for path in sorted((root / "recipes").rglob("recipe*.py"))}


@contextmanager
def baseline_root(sha):
    """把 <sha> 解到临时 worktree，交出它的根目录；退出时删掉 worktree 与临时目录。"""
    tmp = Path(tempfile.mkdtemp(prefix="aac-baseline-"))
    tree = tmp / "tree"
    added = False
    try:
        try:
            subprocess.run(["git", "worktree", "add", "--detach", str(tree), sha],
                           cwd=ROOT, check=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        except subprocess.CalledProcessError as e:
            sys.exit(f"找不到提交 {sha}：先 git fetch origin {sha}\n{e.stderr.strip()}")
        added = True
        yield tree
    finally:
        if added:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)],
                           cwd=ROOT, check=False, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def collect(root):
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--dump", str(root)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        sys.exit(f"跑不通 {root}：\n{proc.stderr}")
    return json.loads(proc.stdout)


def compare(baseline):
    before, after = collect(baseline), collect(ROOT)
    bad = 0
    if before.keys() != after.keys():
        print(f"脚本清单不同：只在基线 {sorted(before.keys() - after.keys())}，"
              f"只在工作区 {sorted(after.keys() - before.keys())}")
        bad += 1
    total, silent = 0, []
    for name in sorted(before.keys() & after.keys()):
        b, a = before[name], after[name]
        total += len(a)
        if not a:
            silent.append(name)
        if b != a:
            bad += 1
            # 一边比另一边长本身就是差异，所以不要求等长
            here = next((i for i, (x, y) in enumerate(zip(b, a, strict=False)) if x != y),
                        min(len(b), len(a)))
            print(f"{name}: 改前 {len(b)} 条，改后 {len(a)} 条，第 {here + 1} 条起不同")
            for item in (b[here:here + 3], a[here:here + 3]):
                print(f"    {json.dumps(item, ensure_ascii=False)}")
    print(f"{len(before)} 份脚本，改后共 {total} 条调用，不一致 {bad} 份")
    if silent:
        print(f"守卫：这 {len(silent)} 份脚本一条调用都没记到：{'、'.join(silent)}")
        bad += len(silent)
    if total < MIN_CALLS:
        print(f"守卫：总共只有 {total} 条调用，低于 {MIN_CALLS}，对拍没测到东西")
        bad += 1
    return 1 if bad else 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        print(json.dumps(dump(sys.argv[2]), ensure_ascii=False, sort_keys=True))
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--baseline":
        with baseline_root(sys.argv[2]) as root:
            return compare(root)
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    return compare(sys.argv[1])


if __name__ == "__main__":
    sys.exit(main())
