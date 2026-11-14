"""机型脚本的调用序列快照（#1239）：同一份合成手机、同一组读屏观察下，每份脚本发出的调用
（段名 + 方法名 + 参数 + 顺序，含绕过门面的 `p.d.shell` 命令）记成数据文件入库，回归里逐条比对。

比对当前树与入库快照（回归默认走这条，不建基线 worktree、不起子进程）：

    python tests/compare_recipe_calls.py

重写快照是显式动作，只在行为确实该变时做，规则见 docs/agents/recipe-snapshots.md：

    python tests/compare_recipe_calls.py --write

纯重构要「改前改后」证据时仍有对拍模式：基线取本分支的基点，驱动自己拉临时 worktree、跑完删掉
（两边各起一个子进程：模块名相同，同进程里 import 不了两份 `fast`）：

    git fetch origin main
    python tests/compare_recipe_calls.py --baseline <git merge-base HEAD origin/main>

也可以手工备好一份 worktree，把它的根目录传进来：

    git worktree add /tmp/aac-baseline <基点 SHA>
    python tests/compare_recipe_calls.py /tmp/aac-baseline

每份脚本按两个场景各跑一遍：

- `present`：入口、拉起、落点与读屏观察一律算「在」，脚本沿主路径走到底；
- `absent`：同一批观察一律算「不在」，脚本退到备用分支（菜单、翻页、重试那几圈循环）。

两个场景都记，备用分支才不是空的。型号守卫读到的 shell 输出一律算「对得上」。记录的是脚本
发出的动作：门面方法，以及不经门面的 `p.d.shell(...)` 命令 —— 有几份被收口的助手整段只有一条
`p.d.shell`，只记门面的话它们搬动前后都是零调用。空页面上「要点名开关」的深支与只认特定控件
的助手（单选按钮之类）走不到，那部分不在快照范围内。

守卫：每份脚本的每个场景都要记到调用，全部加起来不到 MIN_CALLS 条就算没测到 —— 只报「一样」
而没有调用量，说明记录是空转的。`--write` 同样要过这道守卫，空转的一轮写不出快照。
"""
import functools
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT))  # recipe_lib 在仓库根
import fixtures  # noqa: E402
from stdio import use_utf8_console  # noqa: E402  出口取当前副本的，不对拍基线那一份

use_utf8_console()

# 43 份 `recipe.py` 加 4 份变体、两个场景实测约 1.3 万条调用；低于这个数说明记录或装载退化了
MIN_CALLS = 4000
SCENARIOS = ("present", "absent")
SNAPSHOTS = TESTS / "snapshots" / "recipe_calls"


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


def rehearsal(phone, scenario):
    """把挡住段首的几处观察换成一律成功或一律失败，脚本才会走到它自己的助手。

    `p.start`、按文字找入口与点按在空页面上都会失败，段体随即 return；对拍要比的是脚本自身
    调用的顺序，不是引擎在这台空手机上做得对不对。落点跟着 `start()` 的包名走，脚本里
    `p.focus().split("/")[0] == package` 那类判据才过得了。两个场景各写一遍：`present` 走主路径，
    `absent` 让备用分支（「更多」菜单、翻页重试）真的跑起来。
    观察类的 `tree` / `texts` / `switches` 不换 —— 它们给出真实但空的一页，循环照样会停。
    """
    hit = scenario == "present"
    state = {"focus": "com.example.app/.MainActivity"}

    def start(pkg, activity=None, *args, **kwargs):
        state["focus"] = f"{pkg}/{activity or '.MainActivity'}"

    def answer(*args, **kwargs):
        return hit

    for name, value in {
            "start": start,
            "focus": lambda *a, **k: state["focus"],
            "find": answer,
            "entry": answer,
            "tap": answer,
            "go": answer,
            "enter": answer,
            "tab": answer,
            "tap_icon": answer,
            "settle": answer,
            "has_text": answer,
            "expect_page": answer,
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


def recording(phone, state):
    """包住门面上的公开方法与 `p.d.shell`，记下 (段名, 名字, 参数, 关键字参数) 的调用顺序。"""
    log = []

    def wrap(name, call):
        def recorder(*args, **kwargs):
            log.append([state["step"], name, norm(list(args)),
                        {k: norm(v) for k, v in kwargs.items()}])
            return call(*args, **kwargs)
        return recorder

    for name in dir(phone):
        if name.startswith("_") or isinstance(getattr(type(phone), name, None), property):
            continue
        call = getattr(phone, name)
        if callable(call):
            setattr(phone, name, wrap(name, call))
    phone.d.shell = wrap("d.shell", phone.d.shell)
    return log


@contextmanager
def segment_names(recipe_kit):
    """把每条调用归属到当时正在跑的段。

    `@step` 现在是声明式：段名只在 `rt.run_step()` 进入那一刻存在。执行上下文暴露一个
    `OBSERVER`，段包装在跑段体前把名字递给它；没跑任何段时（模块体里的收尾代码）记空串。
    """
    import recipe_runtime
    state = {"step": ""}
    runtime = recipe_runtime

    def observe(name):
        state["step"] = name

    old = runtime.OBSERVER
    runtime.OBSERVER = observe
    try:
        yield state
    finally:
        runtime.OBSERVER = old


@contextmanager
def fake_until(clock):
    """脚本自己调 `until()` 而没传钟时用假钟。

    `until()` 的默认参数 `now=time.monotonic` / `sleep=time.sleep` 在定义那一刻就绑成了真函数，
    `load_recipe` 换掉 `time` 模块的属性也换不动它们：V2417A 那份脚本在空页面上因此真等 3 秒，
    采样轮数还随机器快慢变。假钟下轮数由「超时 / 轮询」的封顶决定，快照才可比。
    """
    import wait
    bound = functools.partial(wait.until, now=clock.time, sleep=clock.sleep)
    # 直接 `from wait import until` 的模块持有另一份绑定：只换 `wait.until` 换不到它，
    # 那些调用仍用定义时绑死的真时钟，采样轮数随机器快慢变（Windows CI 因此多出两轮）。
    # #1269 拆库后这些绑定在 `recipe_lib` 各模块里，逐一替换。
    import recipe_lib
    with ExitStack() as stack:
        stack.enter_context(patch.object(wait, "until", bound))
        for module in recipe_lib.MODULES:
            if hasattr(module, "until"):
                stack.enter_context(patch.object(module, "until", bound))
        yield


def run_script(fast, recipe_kit, fixtures, path, scenario):
    """装载一份脚本（全部段都跑），返回这个场景下它发出的调用序列。"""
    phone = fixtures.fake_phone(clock=fixtures.Clock(), fast_mod=fast, shell=probe_shell)
    rehearsal(phone, scenario)
    with segment_names(recipe_kit) as state, fake_until(fixtures.RecipeClock()):
        log = recording(phone, state)
        fixtures.load_recipe(phone, path, only=[])
    return log


def scripts(root=ROOT):
    """当前树里的机型脚本，按相对路径排序：`recipe*.py` 加 catalog 的 `<型号>.toml`。

    一个型号目录要么是 `.py`（迁移期仍是活的）、要么是 `<型号>.toml`（已转页面树）；同目录两者都在时
    `.py` 优先（迁移期的等价副本，如 V1986A），不让一份机型记两遍（#1262）。"""
    root = Path(root).resolve()
    found = [path.relative_to(root).as_posix()
             for path in sorted((root / "recipes").rglob("recipe*.py"))]
    for toml in sorted((root / "recipes").glob("*/*/*.toml")):
        if any(toml.parent.glob("recipe*.py")):
            continue
        found.append(toml.relative_to(root).as_posix())
    return sorted(found)


def dump(root):
    """给定仓库根，装载它自己的 `recipes/` 与 `tool/`，交出 {脚本: {场景: 调用序列}}。"""
    root = Path(root).resolve()
    fixtures.load_tool()                    # 先让当前树的 tool 就位，load_recipe 不再把它插到最前
    if str(root / "tool") not in sys.path:  # 目标树压过它：脚本与引擎都取这一份
        sys.path.insert(0, str(root / "tool"))
    import fast
    import recipe_kit
    for module in (fast, recipe_kit):
        if not Path(module.__file__).resolve().is_relative_to(root):
            sys.exit(f"{module.__name__} 取到的不是 {root} 那份：sys.path 上有别的 tool/")
    return {path:
            {scenario: run_script(fast, recipe_kit, fixtures, root / path, scenario)
             for scenario in SCENARIOS}
            for path in scripts(root)}


def collect(root):
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--dump", str(root)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        sys.exit(f"跑不通 {root}：\n{proc.stderr}")
    return json.loads(proc.stdout)


def snapshot_name(script):
    """`recipes/<家族>/<型号>/<脚本名>.py` → `<家族>__<型号>__<脚本名>.json`。"""
    family, model, name = Path(script).parts[-3:]
    return f"{family}__{model}__{Path(name).stem}.json"


def snapshot_text(script, scenarios):
    """一份快照的文本形态：一次调用一行，PR 里按行审阅、按行 diff。"""
    lines = ["{", f' "script": {json.dumps(script, ensure_ascii=False)},', ' "scenarios": {']
    for i, scenario in enumerate(SCENARIOS):
        lines.append(f'  {json.dumps(scenario)}: [')
        rendered = [f"   {json.dumps(call, ensure_ascii=False)}" for call in scenarios[scenario]]
        lines.extend(f"{line}," for line in rendered[:-1])
        lines.extend(rendered[-1:])
        lines.append("  ]," if i < len(SCENARIOS) - 1 else "  ]")
    lines += [" }", "}", ""]
    return "\n".join(lines)


def read_snapshots(folder=SNAPSHOTS):
    """入库快照：{脚本: {场景: 调用序列}}，键取文件里写的脚本路径。

    目录不存在时给空表（回归里就是「一份脚本都没有快照」那几条红），不在这里退进程：
    这条函数也被用例直接调用。
    """
    return {data["script"]: data["scenarios"]
            for data in (json.loads(path.read_text(encoding="utf-8"))
                         for path in sorted(Path(folder).glob("*.json")))}


def hollow(data, total=None):
    """「没测到」的两种形态：有脚本的某个场景一条调用都没有，或者总量低于下限。

    返回 [(摘要, 细节)]；`--write` 与比对都先用它把空转挡下来，否则一轮坏掉的记录会变成
    一份同样坏掉的快照，从此两边一样、永远绿。
    """
    found, silent, count = [], [], 0
    for name in sorted(data):
        for scenario in SCENARIOS:
            calls = data[name].get(scenario, [])
            count += len(calls)
            if not calls:
                silent.append(f"{name}[{scenario}]")
    if silent:
        found.append(("一条调用都没记到", "、".join(silent)))
    total = count if total is None else total
    if total < MIN_CALLS:
        found.append(("没测到东西", f"总共只有 {total} 条调用，低于 {MIN_CALLS}"))
    return found


def context(calls, at, span=2):
    """第 `at` 条前后各 `span` 条的原文，行首带序号（从 1 起，与报错的「第几条」一致）。"""
    lo, hi = max(0, at - span), min(len(calls), at + span + 1)
    return "\n".join(f"      {i + 1}: {json.dumps(calls[i], ensure_ascii=False)}"
                     for i in range(lo, hi))


def problems(before, after):
    """差异与「没测到」的守卫：返回 (问题列表, 改后调用总数)，空列表表示零差异且有量。

    每条问题先给「哪一份脚本、哪个场景、哪一段」，再给两边的上下文：只报条数不同的话，
    评审还得自己把两份记录对齐才看得出改的是哪一段。
    """
    found = []
    if before.keys() != after.keys():
        found.append(("脚本清单不同",
                      f"只在快照 {sorted(before.keys() - after.keys())}，"
                      f"只在当前树 {sorted(after.keys() - before.keys())}"))
    total = 0
    for name in sorted(before.keys() & after.keys()):
        for scenario in SCENARIOS:
            b, a = before[name].get(scenario, []), after[name].get(scenario, [])
            total += len(a)
            if b == a:
                continue
            # 一边比另一边长本身就是差异，所以不要求等长
            here = next((i for i, (x, y) in enumerate(zip(b, a, strict=False)) if x != y),
                        min(len(b), len(a)))
            segment = next((call[0] for call in (a[here:here + 1] or b[here:here + 1])), "")
            found.append((f"{name}[{scenario}] 段「{segment}」起不同：快照 {len(b)} 条、当前 {len(a)} 条",
                          f"第 {here + 1} 条起不同\n"
                          f"    快照：\n{context(b, here)}\n"
                          f"    当前：\n{context(a, here)}"))
    found += hollow(after, total)
    return found, total


def compare(baseline):
    before, after = collect(baseline), collect(ROOT)
    found, total = problems(before, after)
    for summary, detail in found:
        print(f"{summary}\n    {detail}")
    print(f"{len(before)} 份脚本 × {len(SCENARIOS)} 个场景，改后共 {total} 条调用，"
          f"问题 {len(found)} 处")
    return 1 if found else 0


def compare_snapshots(data=None):
    """当前树与入库快照比对：回归默认走这条。"""
    if not SNAPSHOTS.is_dir():
        sys.exit(f"没有快照目录 {SNAPSHOTS}：先 python tests/compare_recipe_calls.py --write")
    data = dump(ROOT) if data is None else data
    before = read_snapshots()
    found, total = problems(before, data)
    for summary, detail in found:
        print(f"{summary}\n    {detail}")
    print(f"{len(before)} 份脚本 × {len(SCENARIOS)} 个场景，当前树共 {total} 条调用，"
          f"问题 {len(found)} 处")
    return 1 if found else 0


def write_snapshots(data=None, folder=SNAPSHOTS):
    """重写入库快照。空转的一轮拒绝落盘，并把不再有脚本对应的旧文件删掉。"""
    data = dump(ROOT) if data is None else data
    broken = hollow(data)
    if broken:
        for summary, detail in broken:
            print(f"{summary}\n    {detail}")
        print("记录是空转的，不写快照：先查装载与记录，别把一份坏记录固化成基线")
        return 1
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    keep = set()
    for script in sorted(data):
        path = folder / snapshot_name(script)
        path.write_text(snapshot_text(script, data[script]), encoding="utf-8", newline="\n")
        keep.add(path.name)
    removed = [path.name for path in sorted(folder.glob("*.json")) if path.name not in keep]
    for name in removed:
        (folder / name).unlink()
    total = sum(len(calls) for scenarios in data.values() for calls in scenarios.values())
    print(f"写入 {len(keep)} 份快照，共 {total} 条调用"
          + (f"；删掉 {len(removed)} 份不再对应的旧快照：{'、'.join(removed)}" if removed else ""))
    return 0


def main(argv=()):
    if len(argv) == 2 and argv[0] == "--dump":
        print(json.dumps(dump(argv[1]), ensure_ascii=False, sort_keys=True))
        return 0
    if len(argv) == 2 and argv[0] == "--baseline":
        with fixtures.baseline_worktree(argv[1], ROOT) as root:
            return compare(root)
    if argv == ["--write"]:
        return write_snapshots()
    if not argv:
        return compare_snapshots()
    if len(argv) == 1 and not argv[0].startswith("-"):
        return compare(argv[0])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
