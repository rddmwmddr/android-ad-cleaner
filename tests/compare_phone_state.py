"""纯重构的对拍驱动：同一份页面样本喂给两份 `tool/`，比较可观察输出。

基线取改动前的提交，样本取本仓库 `tests/` 里的 `<hierarchy>` 字面量。驱动自己拉临时
worktree、跑完删掉：

    python tests/compare_phone_state.py --baseline <改动前的提交>

也可以手工备好一份 worktree，把它的 tool 目录传进来：

    git worktree add /tmp/aac-baseline <改动前的提交>
    python tests/compare_phone_state.py /tmp/aac-baseline/tool

比三处：`Phone.texts()`（页面 × 两种屏尺寸 × 读屏策略开 / 关）、
`explore.entries()`（页面 × 包名）、`Phone.off()`（两种屏尺寸 × 安全模式 × 三档 `only`）。
两边必须各起一个子进程：模块名相同，同进程里 import 不了两份 `fast`。

结论不只看「相等」——驱动同时打印守卫数字（策略 / 包名 / `off` 每个场景点到了哪些标题），
全是 0 或某一支退化了就说明对拍什么也没测到。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass

TESTS = Path(__file__).resolve().parent

SIZES = ((1080, 2340), (720, 1600))

TWO_WINDOWS = '''<hierarchy rotation="0">
  <node package="com.android.settings" text="隐私" bounds="[60,300][400,360]"/>
  <node package="com.example.overlay" text="别的窗口" bounds="[60,420][400,480]"/>
  <node package="com.android.settings" text="广告" bounds="[60,540][400,600]"/>
</hierarchy>'''

def switch_page(w, h):
    """按屏宽高参数化的开关页：普通、保护、带外都有，两种尺寸下都可达。

    带内两行贴着 8% / 98.5% 边界放（0.077 / 0.929），常量一改分类就变；
    带外两行完全在屏内，只有中心越界——否则「没点」分不清是被过滤还是没读到。
    守卫按标题回认点击坐标，所以这里同时交回每行开关的中心点。
    """
    rows = [("顶部广告", True, 0.02), ("上边缘广告", True, 0.077), ("广告推荐", True, 0.20),
            ("猜你喜欢", False, 0.35), ("限制广告跟踪", False, 0.50), ("防止广告追踪", True, 0.65),
            ("下边缘广告", True, 0.929), ("底部广告", True, 0.985)]
    row_h = max(12, h // 60)
    nodes, coords = [], {}
    for title, checked, ratio in rows:
        y0 = min(int(h * ratio), h - row_h)
        y1 = y0 + row_h
        l, r = int(w * 0.88), int(w * 0.98)
        nodes.append(
            f'  <node package="com.android.settings" clickable="true" bounds="[0,{y0}][{w},{y1}]">\n'
            f'    <node text="{title}" bounds="[{int(w * 0.05)},{y0 + 2}][{int(w * 0.4)},{y1 - 2}]"/>\n'
            f'    <node class="android.widget.Switch" checkable="true" checked="{str(checked).lower()}"'
            f' bounds="[{l},{y0}][{r},{y1}]"/>\n'
            f'  </node>')
        coords[title] = ((l + r) // 2, (y0 + y1) // 2)
    return '<hierarchy rotation="0">\n' + "\n".join(nodes) + '\n</hierarchy>', coords


def dump(tool_dir):
    """跑一份 `tool/`，把三处可观察输出整理成 JSON。"""
    sys.path.insert(0, str(TESTS))
    sys.path.insert(0, tool_dir)
    import fast
    import explore
    import fixtures

    def page_phone(xml, size):
        p = fixtures.phone_stub("test", fast_mod=fast)
        p.W, p.H = size
        p.d = fixtures.Device(fixtures.Timeline([(0.0, xml)]), size, fixtures.Clock())
        return p

    def texts():
        out = []
        for label, xml in fixtures.all_pages(str(TESTS)):
            for size in SIZES:
                for flag in (False, True):
                    p = page_phone(xml, size)
                    p.sysui = flag            # 改前的名字
                    p.systemui_text = flag    # 改后的名字
                    try:
                        got = [(t, b) for t, b, _ in p.texts(ET.fromstring(xml))]
                    except Exception as e:
                        got = ["ERROR", type(e).__name__]
                    out.append({"id": f"{label}|{size}|{flag}", "got": got})
        return out

    def entries():
        takes_pkg = explore.entries.__code__.co_argcount == 2      # 改前 1 个参数，改后 2 个
        out = []
        for label, xml in [("two-windows", TWO_WINDOWS)] + fixtures.all_pages(str(TESTS)):
            p = page_phone(xml, SIZES[0])
            for pkg in ("com.android.settings", ""):
                try:
                    if takes_pkg:
                        got = explore.entries(p, pkg)
                    else:
                        p.pkg_now = pkg
                        got = explore.entries(p)
                except Exception as e:
                    got = ["ERROR", type(e).__name__]
                out.append({"id": f"{label}|{pkg}", "got": got})
        return out

    def off():
        out = []
        for size in SIZES:
            page, _ = switch_page(*size)
            for safe in (True, False):
                for only in (None, ["运营任务"], ["广告推荐"]):
                    clock = fixtures.Clock()
                    fixtures.install_clock(fast, clock)
                    lines, clicked = [], []
                    p = fixtures.fake_phone(clock=clock, size=size, stages=[(0.0, page)], fast_mod=fast,
                                            say=lines.append)
                    p.safe_mode = safe
                    p.click = lambda x, y, _c=clock, _a=clicked: (_c.click(), _a.append((x, y)))
                    label = "None" if only is None else only[0]
                    previous = os.environ.pop("AAC_REF", None)
                    try:
                        if safe:
                            os.environ["AAC_REF"] = "1"   # 更早的实现靠环境变量；当前两版都忽略它
                        done = p.off(page="系统·广告服务", only=only)
                    finally:
                        os.environ.pop("AAC_REF", None)
                        if previous is not None:
                            os.environ["AAC_REF"] = previous
                    out.append({"id": f"{size[0]}x{size[1]}|safe={safe}|only={label}",
                                "done": done, "clicks": clock.clicks, "clicked": clicked,
                                "changed": p.changed, "lines": lines})
        return out

    return {"texts": texts(), "entries": entries(), "off": off()}


@contextmanager
def baseline_tool_dir(sha):
    """把 <sha> 解到临时 worktree，交出它的 tool/；退出时删掉 worktree 与临时目录。"""
    root = TESTS.parent
    tmp = Path(tempfile.mkdtemp(prefix="aac-baseline-"))
    tree = tmp / "tree"
    added = False
    try:
        try:
            subprocess.run(["git", "worktree", "add", "--detach", str(tree), sha],
                           cwd=root, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            sys.exit(f"找不到提交 {sha}：先 git fetch origin {sha}\n{e.stderr.strip()}")
        added = True
        yield tree / "tool"
    finally:
        if added:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)],
                           cwd=root, check=False, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def collect(tool_dir):
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--dump", str(tool_dir)],
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode:
        sys.exit(f"跑不通 {tool_dir}：\n{proc.stderr}")
    return json.loads(proc.stdout)


def off_guards(records):
    """每个场景断言它自己那条分支：点到哪些标题、核对几项、带外行一次不点、重试真的补点。"""
    expected_clicks = {
        ("None", False): {"上边缘广告", "广告推荐", "下边缘广告", "限制广告跟踪"},
        ("None", True): {"限制广告跟踪"},
        ("运营任务", False): {"限制广告跟踪"},
        ("运营任务", True): {"限制广告跟踪"},
        ("广告推荐", False): {"广告推荐", "限制广告跟踪"},
        ("广告推荐", True): {"广告推荐", "限制广告跟踪"},
    }
    expected_checked = {
        ("None", False): 8, ("None", True): 2,
        ("运营任务", False): 2, ("运营任务", True): 2,
        ("广告推荐", False): 3, ("广告推荐", True): 3,
    }
    bad = 0
    for rec in records:
        size_s, safe_s, only_s = rec["id"].split("|")
        w, h = map(int, size_s.split("x"))
        _, coords = switch_page(w, h)
        by_xy = {xy: title for title, xy in coords.items()}
        clicked = [by_xy.get(tuple(xy)) for xy in rec["clicked"]]
        got = set(clicked)
        key = (only_s.removeprefix("only="), safe_s == "safe=True")
        expected = expected_clicks[key]
        summary = f"核对 {expected_checked[key]} 项，调整 0 项"
        ok = (got == expected
              and rec["clicks"] > len(expected)          # 静态页回读不变，重试必须补点
              and "顶部广告" not in got and "底部广告" not in got
              and None not in got
              and any(summary in line for line in rec["lines"]))
        bad += 0 if ok else 1
        print(f"守卫：{rec['id']} 点到 {sorted(x for x in got if x)}，共 {rec['clicks']} 次，"
              f"{'ok' if ok else 'FAIL'}")
    return bad


def compare(baseline_tool):
    before, after = collect(str(baseline_tool)), collect(str(TESTS.parent / "tool"))
    bad = 0
    for key in before:
        bm, am = {x["id"]: x for x in before[key]}, {x["id"]: x for x in after[key]}
        diff = [i for i in bm if bm[i] != am.get(i)]
        bad += len(diff)
        print(f"{key}: {len(bm)} 组，一致 {len(bm) - len(diff)}，不一致 {len(diff)}")
        for i in diff[:5]:
            print(f"  {i}\n    改前 {json.dumps(bm[i], ensure_ascii=False)}\n    改后 {json.dumps(am.get(i), ensure_ascii=False)}")
    # 守卫：对拍必须真的走到目标分支，否则「两边一样」是必然的
    t = {x["id"]: x["got"] for x in after["texts"]}
    flipped = sum(1 for k in t if k.endswith("|True") and t[k] != t[k[:-5] + "|False"])
    e = {x["id"]: x["got"] for x in after["entries"]}
    filtered = sum(1 for k, v in e.items() if k.rsplit("|", 1)[1] == "com.android.settings"
                   and v != e[k.rsplit("|", 1)[0] + "|"])
    print(f"守卫：读屏策略改变输出的组数 {flipped}，包名过滤改变输出的页数 {filtered}")
    bad += off_guards(after["off"])
    return 1 if bad else 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        print(json.dumps(dump(sys.argv[2]), ensure_ascii=False, sort_keys=True))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--baseline":
        with baseline_tool_dir(sys.argv[2]) as tool_dir:
            bad = compare(tool_dir)
        sys.exit(bad)
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(compare(sys.argv[1]))


if __name__ == "__main__":
    main()
