#!/usr/bin/env python3
"""新机型适配辅助：探路 → 人工勾选 → 生成草稿 → 安全模式自检。四段都由人把关，工具不自动决定关哪些开关。

  adapt.py explore -s SERIAL [包名 …]        只读探路（复用 explore.py）→ 探路-<型号>.tsv
  adapt.py gen 探路-<型号>.tsv [-o 输出.py]   把人工勾选的开关生成 recipe 草稿（不碰手机）
                     [--pick 清单.txt]       勾选清单：每行一个开关标题（不用改 TSV 时用它）
                     [--model 型号] [--build 录制版本]
  adapt.py check -s SERIAL 草稿.py [段名 …]   安全模式自检草稿，输出适配报告

草稿不是适配：入口路径来自探路读屏，未经人工逐步核对；自检只证明「进得去、关得掉、回读确认」。
转正式机型脚本前必须人工在手机上核对，并补上 BUILD 录制版本。不要直接放进 recipes/。
"""
import datetime, json, os, re, subprocess, sys
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast                                    # 只读 want_state / 驱动 Phone；不改引擎
from fast import Phone
from run import fail, script_cmd             # 错误渲染与打包版的 --cli 规矩都只在 run.py 写一份

TSV_COLS = ("pkg", "page", "title", "state", "ad", "pick")
# 人工勾选列里写这些值=要关；空=不关。工具不自动勾选。
SELECT_MARKS = {"关", "是", "y", "yes", "1", "√", "✓", "选中", "true"}


# ---------- 探路 TSV ----------

def parse_tsv(path):
    """读探路 TSV：容忍 BOM、CRLF、# 注释行和表头；列不够补空，列多截断。"""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    rows = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = [c.strip() for c in line.split("\t")]
        if cols and cols[0] == "包名":
            continue                            # 表头
        cols += [""] * (len(TSV_COLS) - len(cols))
        rows.append(dict(zip(TSV_COLS, cols[:len(TSV_COLS)])))
    return rows


def read_pick_file(path):
    """人工勾选清单：每行一个开关标题；# 开头是注释。
    找不到时返回 (None, 文案)，由调用方转成退出码——helper 不结束进程。"""
    if not os.path.exists(path):
        return None, f"找不到勾选清单 {path}"
    with open(path, encoding="utf-8-sig") as f:
        return [l.strip() for l in f.read().splitlines() if l.strip() and not l.lstrip().startswith("#")], None


def select_rows(rows, pick_titles=()):
    """按人工勾选挑行 → [(包名, 页面, [开关标题, …]), …]；保护类开关跳过（打开才是保护）。
    返回 (分组, 跳过的保护类开关, 未勾选的疑似广告开关数)。"""
    marks = {t for t in pick_titles if t}
    groups, order = {}, []
    protection, ad_left = [], 0
    for r in rows:
        title = r["title"]
        if not title or title.startswith("（"):          # 探路失败的占位行
            continue
        if fast.want_state(title) is True:               # 「限制广告跟踪」这类：打开才是保护
            if r["pick"].strip().lower() in SELECT_MARKS or title in marks:
                protection.append(title)
            continue
        picked = r["pick"].strip().lower() in SELECT_MARKS or title in marks
        if not picked:
            ad_left += bool(r["ad"])
            continue
        key = (r["pkg"], r["page"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        if title not in groups[key]:
            groups[key].append(title)
    return [(pkg, page, groups[(pkg, page)]) for pkg, page in order], protection, ad_left


# ---------- 生成草稿 ----------

def step_name(pkg, page):
    """@step("...") 里不能出现引号/反斜杠/换行：run.py recipe_meta 按这个字面格式解析步骤名。"""
    name = f"{pkg} · {page}"
    for bad in ('"', "\\", "\r", "\n"):
        name = name.replace(bad, "")
    return name


DRAFT_HELPERS = '''
import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
VERIFIED_SWITCHES = 0        # 回读确认关闭的开关数
MISSING_SWITCHES = []        # 没找到的开关（待人工确认）
PENDING_SWITCHES = []        # 找到了但回读没确认关闭（待人工确认）


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def step(name):
    def decorate(action):
        if ONLY and name not in ONLY:
            return action
        print(f"\\n== {name}", flush=True)
        p.miss = 0
        try:
            require(not p.locked(), "手机锁屏了，请机主解锁后再跑")
            action()
        except Exception as error:
            FAILED_STEPS.append(name)
            print(f"  ✗ 未完成：{error}", flush=True)
        return action
    return decorate


def read_switches(max_screens):
    current = {}
    for index in range(max_screens):
        current.update({title: on for title, on, _ in p.switches()})
        if index + 1 == max_screens or not p.scroll_more():
            break
    return current


def close_named(names, page, max_screens=1):
    """待验证壳：只关 only= 点名的开关；没找齐不操作；关完回读确认。
    与正式机型脚本的 close_named 不同：找不到/没确认时记进报告，不中断其余步骤。
    开关在第二屏以后找不到时，把 max_screens 改大再自检。"""
    global VERIFIED_SWITCHES
    p.top(max_screens)
    before = read_switches(max_screens)
    missing = [name for name in names if name not in before]
    if missing:
        MISSING_SWITCHES.extend(missing)
        print(f"  ✗ {page}：未找到 {missing}，未操作", flush=True)
        return
    p.top(max_screens)
    p.off(only=names, page=page, max_screens=max_screens)
    p.top(max_screens)
    current = read_switches(max_screens)
    still = [name for name in names if current.get(name) is not False]
    PENDING_SWITCHES.extend(still)
    if still:
        print(f"  ✗ {page}：回读未确认关闭 {still}", flush=True)
        return
    VERIFIED_SWITCHES += len(names)
    print(f"  ✓ {page}：回读确认关闭 {len(names)} 项", flush=True)
'''


def render_draft(groups, model, build, source):
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# -*- coding: utf-8 -*-",
        "# ===================== 待验证草稿 · adapt gen 生成 =====================",
        "# 这不是适配成果：下面的入口路径、开关标题全部来自探路读屏，未经人工逐步核对。",
        f"# 生成时间：{when}；来源：{source}",
        "# 自检：python3 tool/run.py -s <序列号> adapt check <本文件>",
        "#   自检只证明「进得去、关得掉、回读确认」，不代表适配完成；",
        "#   转为正式机型脚本前，必须人工在手机上核对每一步，并补 BUILD 录制版本。",
        "# 不要直接放进 recipes/：放进去会被当成本型号的正式脚本自动匹配。",
        "# ======================================================================",
        f"BUILD = {json.dumps(build)}",
        f"MODELS = {json.dumps([model] if model else [], ensure_ascii=False)}",
    ]
    lines += DRAFT_HELPERS.strip("\n").split("\n")
    for pkg, page, names in groups:
        lines += [
            "",
            "",
            f"@step({json.dumps(step_name(pkg, page), ensure_ascii=False)})",
            "def _():",
            f"    # 待验证：入口路径来自探路（{page}）",
            f"    p.start({json.dumps(pkg, ensure_ascii=False)})",
            '    if p.find("我的", exact=True, edge_ok="tab"):',
            '        p.tap("我的", exact=True, scrolls=0)',
            '    require(p.tap("设置", exact=True, scrolls=3), "未找到设置入口「设置」")',
        ]
        for seg in [s.strip() for s in page.split(">") if s.strip()][1:]:
            lines.append(f'    require(p.tap({json.dumps(seg, ensure_ascii=False)}, exact=True, scrolls=4), "未找到子页入口「{seg}」")')
        lines.append(f"    close_named({json.dumps(names, ensure_ascii=False)}, {json.dumps(page, ensure_ascii=False)})")
    lines += [
        "",
        "",
        'print(f"\\n草稿自检：回读确认 {VERIFIED_SWITCHES} 项，未找到 {len(MISSING_SWITCHES)} 项，"',
        '      f"待人工确认 {len(PENDING_SWITCHES)} 项，未完成步骤 {len(FAILED_STEPS)} 个", flush=True)',
        "",
    ]
    return "\n".join(lines)


def cmd_gen(rest):
    tsv = out = None
    picks, model, build = [], "", ""
    args, i = list(rest), 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "--pick", "--model", "--build"):
            if i + 1 >= len(args):
                return fail(f"选项 {a} 后面要跟值")
            value = args[i + 1]
            if a == "-o":
                out = value
            elif a == "--pick":
                picks.append(value)
            elif a == "--model":
                model = value
            else:
                build = value
            i += 2
        elif a.startswith("-"):
            return fail(f"不认识的选项 {a}。用法：run.py adapt gen <探路-型号.tsv> [-o 输出.py] [--pick 清单.txt] "
                        "[--model 型号] [--build 录制版本]")
        elif tsv is None:
            tsv = a
            i += 1
        else:
            return fail("只收一个探路 TSV 文件；要合并多份结果请先手工合并")
    if not tsv:
        return fail("用法：run.py adapt gen <探路-型号.tsv> [-o 输出.py] [--pick 清单.txt] [--model 型号] [--build 录制版本]")
    if not os.path.exists(tsv):
        return fail(f"找不到 {tsv}")
    rows = parse_tsv(tsv)
    if not rows:
        return fail(f"{tsv} 里没有数据行")
    if not model:
        m = re.search(r"探路-(.+)\.tsv$", os.path.basename(tsv))
        model = m.group(1) if m else ""
    pick_titles = []
    for pf in picks:
        titles, error = read_pick_file(pf)
        if error:
            return fail(error)
        pick_titles.extend(titles)
    groups, protection, ad_left = select_rows(rows, pick_titles)
    if not groups:
        return fail("没有勾选任何开关：在 TSV 末列「人工勾选」写「关」，或用 --pick 给清单文件。"
                    "工具不自动决定关哪些开关。")
    known = {r["title"] for r in rows}
    unknown = sorted({t for t in pick_titles if t not in known})
    if unknown:
        print(f"⚠ 勾选清单里这些开关在探路结果里找不到，未写进草稿：{'、'.join(unknown)}")
    if protection:
        print(f"⚠ 这些是保护类开关（打开才是保护），没有写进草稿：{'、'.join(protection)}")
    if ad_left:
        print(f"另有 {ad_left} 个疑似广告开关没有勾选，未写进草稿（工具不自动决定关哪些）")
    src = render_draft(groups, model=model, build=build, source=os.path.basename(tsv))
    out = out or (f"草稿-{model}.py" if model else "草稿.py")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(src)
    except OSError as e:
        return fail(f"写不出 {out}：{e}")
    total = sum(len(names) for _, _, names in groups)
    print(f"草稿已生成：{out}（{len(groups)} 段，{total} 个开关，均为待验证）")
    if not model:
        print("没能从文件名认出型号，MODELS 为空；补型号用 --model，或直接把文件名改成 探路-<型号>.tsv")
    if not build:
        print("BUILD 为空：自检时不比对系统版本；转正式脚本前请填上录制版本（ro.build.display.id）")
    print(f"下一步：python3 tool/run.py -s <序列号> adapt check {out}")
    print("自检通过也不等于适配完成：请人工在手机上核对每一步，再决定是否转为正式机型脚本。")
    return 0


# ---------- 安全模式自检 ----------

def check_draft(p, recipe_path, only=()):
    """安全模式跑草稿并统计回读结果。驱动方式与 fast.py 的 `run` 分支一致：
    exec 注入 p/ONLY 到 globals，引擎逻辑本身不改。"""
    with open(recipe_path, encoding="utf-8") as f:
        src = f.read()
    # 手改过的草稿若写了不带 only= 的 p.off()，靠这个也只关点名的开关，不整页全关。
    p.safe_mode = True
    g = {"p": p, "__name__": "__draft__", "ONLY": list(only)}
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    osv = p.d.shell("getprop ro.mi.os.version.incremental").output.strip()
    m = re.search(r'^BUILD\s*=\s*"([^"]+)"', src, re.M)
    if m and not (build.startswith(m.group(1)) or osv.startswith(m.group(1))):
        print(f"⚠ 草稿标注 BUILD {m.group(1)}，这台是 {osv or build}：按安全模式跑（只关点名的开关）")
    exec(compile(src, recipe_path, "exec"), g)
    return {
        "verified": g.get("VERIFIED_SWITCHES", 0) or 0,
        "missing": list(g.get("MISSING_SWITCHES", []) or []),
        "pending": list(g.get("PENDING_SWITCHES", []) or []),
        "failed_steps": list(g.get("FAILED_STEPS", []) or []),
    }


def print_report(report):
    """适配报告：找到几个/关成几个/没找到几个/待人工确认几个。部分完成不说成成功。"""
    verified = report["verified"]
    missing, pending, failed = report["missing"], report["pending"], report["failed_steps"]
    print("\n================ 适配报告（草稿 · 安全模式自检） ================")
    print(f"  回读确认关闭：{verified} 项")
    print(f"  没找到：{len(missing)} 项" + (f"（{'、'.join(missing)}）" if missing else ""))
    print(f"  待人工确认：{len(pending)} 项" + (f"（{'、'.join(pending)}）" if pending else ""))
    print(f"  未完成步骤：{len(failed)} 个" + (f"（{'、'.join(failed)}）" if failed else ""))
    ok = verified > 0 and not missing and not pending and not failed
    if ok:
        print("结论：自检通过——勾选的开关都已找到并回读确认关闭。")
        print("      这仍不代表适配完成：请人工在手机上核对入口和效果，再决定是否转为正式机型脚本。")
    elif verified == 0 and not pending:
        print("结论：自检未通过——没有回读确认关闭任何开关。请把上面的开关名和步骤名交给人工核对。")
    else:
        print("结论：部分完成——已确认关闭的项见上；没找到/待人工确认的项必须人工在手机上核对，")
        print("      不能把部分完成当成适配成功。")
    print("==================================================================")
    return ok


def cmd_check(rest):
    if len(rest) < 3 or rest[0] != "-s":
        return fail("用法：run.py adapt check -s <序列号> <草稿.py> [段名 …]")
    serial, recipe, only = rest[1], rest[2], rest[3:]
    if not os.path.exists(recipe):
        return fail(f"找不到 {recipe}")
    locked = False
    with Phone(serial) as p:
        if p.locked():
            locked = True
        else:
            stay = p.d.shell("settings get global stay_on_while_plugged_in").output.strip()
            try:
                p.d.shell("settings put global stay_on_while_plugged_in 7")
                print("⚠ 安全模式自检：这份是待验证草稿，只关 only= 点名的开关，找不到就如实报告。")
                report = check_draft(p, recipe, only)
            finally:
                p.d.shell(f"settings put global stay_on_while_plugged_in {int(stay) if stay.isdigit() else 0}")
    if locked:                      # 文案等 __exit__ 跑完再渲染：close 抛错时与 sys.exit 的旧时机一致
        return fail("手机锁屏了，请机主解锁后再跑")
    return 0 if print_report(report) else 1


def cmd_explore(rest):
    if not rest or rest[0] != "-s" or len(rest) < 2:
        return fail("用法：run.py adapt explore -s <序列号> [包名 …]")
    return subprocess.call(script_cmd("explore.py", "-s", rest[1], *rest[2:]))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    sub, rest = argv[0], argv[1:]
    if sub == "explore":
        return cmd_explore(rest)
    if sub == "gen":
        return cmd_gen(rest)
    if sub == "check":
        return cmd_check(rest)
    return fail("adapt 后面跟 explore / gen / check。用法：run.py adapt --help")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
