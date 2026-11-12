"""公共导航搬动前后的调用序列对拍（#1150）：同一份机型脚本分别用基点与工作区装载一次，
比较脚本发出的调用（方法名 + 参数 + 顺序）。零差异才算搬动没改行为。

基线取本分支的基点，不入库快照文件。驱动自己拉临时 worktree、跑完删掉：

    git fetch origin main
    python tests/compare_recipe_calls.py --baseline <git merge-base HEAD origin/main>

也可以手工备好一份 worktree，把它的根目录传进来：

    git worktree add /tmp/aac-baseline <基点 SHA>
    python tests/compare_recipe_calls.py /tmp/aac-baseline

两边各起一个子进程：模块名相同，同进程里 import 不了两份 `fast`。每份脚本按两个场景各跑一遍：

- `present`：入口、拉起、落点与读屏观察一律算「在」，脚本沿主路径走到底；
- `absent`：同一批观察一律算「不在」，脚本退到备用分支（菜单、翻页、重试那几圈循环）。

两个场景都记，备用分支才不是空的。型号守卫读到的 shell 输出一律算「对得上」。记录的是脚本
发出的动作：门面方法，以及不经门面的 `p.d.shell(...)` 命令 —— 有几份被收口的助手整段只有一条
`p.d.shell`，只记门面的话它们搬动前后都是零调用。空页面上「要点名开关」的深支与只认特定控件
的助手（单选按钮之类）走不到，那部分不在对拍范围内。

守卫：每份脚本的每个场景都要记到调用，全部加起来不到 MIN_CALLS 条就算没测到 —— 只报「两边
一样」而没有调用量，说明对拍是空转的。
"""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "tool"))
import fixtures  # noqa: E402
from stdio import use_utf8_console  # noqa: E402  出口取当前副本的，不对拍基线那一份

use_utf8_console()

# 43 份 `recipe.py` 加 4 份变体、两个场景实测约 1.3 万条调用；低于这个数说明记录或装载退化了
MIN_CALLS = 4000
SCENARIOS = ("present", "absent")


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


def recording(phone):
    """包住门面上的公开方法与 `p.d.shell`，记下 (名字, 参数, 关键字参数) 的调用顺序。"""
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
    phone.d.shell = wrap("d.shell", phone.d.shell)
    return log


def run_script(fast, recipe_kit, fixtures, path, scenario):
    """装载一份脚本（全部段都跑），返回这个场景下它发出的调用序列。"""
    phone = fixtures.fake_phone(clock=fixtures.Clock(), fast_mod=fast, shell=probe_shell)
    rehearsal(phone, scenario)
    log = recording(phone)
    fixtures.load_recipe(phone, path, only=[])
    return log


def dump(root):
    """给定仓库根，装载它自己的 `recipes/` 与 `tool/`，交出 {脚本: {场景: 调用序列}}。"""
    root = Path(root).resolve()
    fixtures.load_tool()                    # 先让当前树的 tool 就位，load_recipe 不再把它插到最前
    sys.path.insert(0, str(root / "tool"))  # 目标树压过它：脚本与引擎都取这一份
    import fast
    import recipe_kit
    for module in (fast, recipe_kit):
        if not Path(module.__file__).resolve().is_relative_to(root):
            sys.exit(f"{module.__name__} 取到的不是 {root} 那份：sys.path 上有别的 tool/")
    return {path.relative_to(root).as_posix():
            {scenario: run_script(fast, recipe_kit, fixtures, path, scenario)
             for scenario in SCENARIOS}
            for path in sorted((root / "recipes").rglob("recipe*.py"))}


def collect(root):
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--dump", str(root)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        sys.exit(f"跑不通 {root}：\n{proc.stderr}")
    return json.loads(proc.stdout)


def problems(before, after):
    """差异与「没测到」的守卫：返回 (问题列表, 改后调用总数)，空列表表示零差异且有量。"""
    found = []
    if before.keys() != after.keys():
        found.append(("脚本清单不同",
                      f"只在基线 {sorted(before.keys() - after.keys())}，"
                      f"只在工作区 {sorted(after.keys() - before.keys())}"))
    total, silent = 0, []
    for name in sorted(before.keys() & after.keys()):
        for scenario in SCENARIOS:
            b, a = before[name].get(scenario, []), after[name].get(scenario, [])
            total += len(a)
            if not a:
                silent.append(f"{name}[{scenario}]")
            if b != a:
                # 一边比另一边长本身就是差异，所以不要求等长
                here = next((i for i, (x, y) in enumerate(zip(b, a, strict=False)) if x != y),
                            min(len(b), len(a)))
                found.append((f"{name}[{scenario}] 改前 {len(b)} 条、改后 {len(a)} 条",
                              "第 {} 条起不同：基线 {}\n{} 工作区 {}".format(
                                  here + 1,
                                  json.dumps(b[here:here + 1], ensure_ascii=False),
                                  " " * 10,
                                  json.dumps(a[here:here + 1], ensure_ascii=False))))
    if silent:
        found.append(("一条调用都没记到", "、".join(silent)))
    if total < MIN_CALLS:
        found.append(("对拍没测到东西", f"总共只有 {total} 条调用，低于 {MIN_CALLS}"))
    return found, total


def compare(baseline):
    before, after = collect(baseline), collect(ROOT)
    found, total = problems(before, after)
    for summary, detail in found:
        print(f"{summary}\n    {detail}")
    print(f"{len(before)} 份脚本 × {len(SCENARIOS)} 个场景，改后共 {total} 条调用，"
          f"问题 {len(found)} 处")
    return 1 if found else 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        print(json.dumps(dump(sys.argv[2]), ensure_ascii=False, sort_keys=True))
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--baseline":
        with fixtures.baseline_worktree(sys.argv[2], ROOT) as root:
            return compare(root)
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    return compare(sys.argv[1])


if __name__ == "__main__":
    sys.exit(main())
