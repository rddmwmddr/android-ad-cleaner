#!/usr/bin/env python3
"""新机型适配辅助：试入口 → 探路 → 人工勾选 → 生成草稿 → 安全模式自检。五段都由人把关，工具不自动决定关哪些开关。

  adapt.py survey -s SERIAL                  只读试入口：拿同家族验证过的直达逐条打开，报打不打得开、命中的同组词条、App 装没装
  adapt.py explore -s SERIAL [包名 …]        只读探路（复用 explore.py）→ 探路-<型号>.tsv
  adapt.py gen 探路-<型号>.tsv [-o 输出.toml]   把人工勾选的开关生成页面树草稿（不碰手机）
                     [--pick 清单.txt]       勾选清单：每行一个开关标题（不用改 TSV 时用它）
                     [--model 型号] [--build 录制版本]
  adapt.py check -s SERIAL 草稿.toml [段名 …] 安全模式自检草稿，输出适配报告

草稿不是适配：入口路径来自探路读屏，未经人工逐步核对；自检只证明「进得去、关得掉、回读确认」。
转正式机型脚本前必须人工在手机上核对，并补上 BUILD 录制版本。不要直接放进 recipes/。
"""
import datetime, json, os, re, subprocess, sys, tomllib
import xml.etree.ElementTree as ET
from stdio import use_utf8_console

use_utf8_console()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entries
import fast                                    # 只读 want_state / 驱动 Phone；不改引擎
import recipe_loader
import vocab
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
        rows.append(dict(zip(TSV_COLS, cols[:len(TSV_COLS)], strict=True)))    # 上一行已把 cols 补齐到 len(TSV_COLS)
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
    """@step("...") 里不能出现引号/反斜杠/换行：recipe_meta 按这个字面格式解析步骤名。"""
    name = f"{pkg} · {page}"
    for bad in ('"', "\\", "\r", "\n"):
        name = name.replace(bad, "")
    return name


# 草稿不再自带台账变量：回读确认数与分段结果都在这层注入的 `rt` 上（ADR-0037），
# `read_switches` / `close_named` 同样用注入面那一份（沿用 #1151），否则新写出的脚本又把
# 本地副本带走，两代实现的坑重挖一遍。


def render_catalog_draft(groups, model, build, source):
    """`adapt gen` 的 catalog 骨架（ADR-0038，`<型号>.toml`）：每段的入口与待关名单写成页面树数据。

    骨架是「待验证草稿」，起点形状已经对：每段一个 `[[segment]]`，`start` 拉起 → `entry` 逐层进子页 →
    `off` 关点名的开关。人只需在手机上核对、补 `activity` / 守卫 / 例外，不再是写一个程序。这里不产
    `code=` 例外：草稿没有本机知识，<型号>.py 有例外时才另写。
    """
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# ===================== 待验证草稿（页面树）· adapt gen 生成 =====================",
        "# 这不是适配成果：入口路径、开关标题全部来自探路读屏，未经人工逐步核对。",
        f"# 生成时间：{when}；来源：{source}",
        "# 自检：python3 tool/run.py -s <序列号> adapt check <本文件>",
        "#   自检只证明「进得去、关得掉、回读确认」，不代表适配完成；转为正式数据前必须人工核对。",
        "# 不要直接放进 recipes/：放进去会被当成本型号的正式脚本自动匹配。",
        "# 页面树只装机型知识；失败怎么收场、顺序、重试、台账归运行时（ADR-0038）。",
        "# ==========================================================================",
        f"model = {json.dumps(model, ensure_ascii=False)}",
        f"models = {json.dumps([model] if model else [], ensure_ascii=False)}",
        f"build = {json.dumps(build, ensure_ascii=False)}",
    ]
    for pkg, page, names in groups:
        lines += ["", "[[segment]]", f"name = {json.dumps(step_name(pkg, page), ensure_ascii=False)}", "ops = ["]
        lines.append(f"  {{kind = \"start\", pkg = {json.dumps(pkg, ensure_ascii=False)}}},")
        for seg in [s.strip() for s in page.split(">") if s.strip()][1:]:
            lines.append(f"  {{kind = \"entry\", text = {json.dumps(seg, ensure_ascii=False)}}},")
        only = json.dumps(names, ensure_ascii=False)
        lines.append(f"  {{kind = \"off\", only = {only}, page = {json.dumps(page, ensure_ascii=False)}}},")
        lines.append("]")
    lines.append("")
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
            return fail(f"不认识的选项 {a}。用法：run.py adapt gen <探路-型号.tsv> [-o 输出.toml] [--pick 清单.txt] "
                        "[--model 型号] [--build 录制版本]")
        elif tsv is None:
            tsv = a
            i += 1
        else:
            return fail("只收一个探路 TSV 文件；要合并多份结果请先手工合并")
    if not tsv:
        return fail("用法：run.py adapt gen <探路-型号.tsv> [-o 输出.toml] [--pick 清单.txt] [--model 型号] [--build 录制版本]")
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
    # 只有 catalog 骨架（`.toml`，ADR-0038）：`.py` 机型脚本已随注入面删除（#1268）。
    if out and not out.lower().endswith(".toml"):
        return fail(f"-o 只收 .toml 页面树草稿；{out} 不是 .toml（.py 机型脚本已删除，#1268）")
    src = render_catalog_draft(groups, model=model, build=build, source=os.path.basename(tsv))
    target = out or (f"草稿-{model}.toml" if model else "草稿.toml")
    out = target
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(src)
    except OSError as e:
        return fail(f"写不出 {target}：{e}")
    total = sum(len(names) for _, _, names in groups)
    print(f"草稿已生成：{out}（{len(groups)} 段，{total} 个开关，均为待验证）")
    if not model:
        print("没能从文件名认出型号，MODELS 为空；补型号用 --model，或直接把文件名改成 探路-<型号>.tsv")
    if not build:
        print("BUILD 为空：自检时不比对系统版本；转正式脚本前请填上录制版本"
              "（小米系填 ro.mi.os.version.incremental，别填 ro.build.display.id 的 Android 底包）")
    print(f"下一步：python3 tool/run.py -s <序列号> adapt check {out}")
    print("自检通过也不等于适配完成：请人工在手机上核对每一步，再决定是否转为正式机型脚本。")
    return 0


# ---------- 安全模式自检 ----------

def check_draft(p, recipe_path, only=()):
    """安全模式跑草稿并统计回读结果。草稿唯一形态是 catalog 页面树（`.toml`，ADR-0038）。"""
    if not str(recipe_path).lower().endswith(".toml"):
        raise ValueError(f"{recipe_path}：check 只认 .toml 页面树草稿；.py 机型脚本已随注入面删除（#1268）")
    with open(recipe_path, "rb") as f:
        data = tomllib.load(f)
    # 手改过的草稿若写了不带 only= 的 p.off()，靠这个也只关点名的开关，不整页全关。
    p.safe_mode = True
    p.screen.captures.task = "adapt"        # 失败现场按任务归档（#1126）
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    osv = p.d.shell("getprop ro.mi.os.version.incremental").output.strip()
    recorded = str(data.get("build", ""))
    if recorded and not (build.startswith(recorded) or osv.startswith(recorded)):
        print(f"⚠ 草稿标注 BUILD {recorded}，这台是 {osv or build}：按安全模式跑（只关点名的开关）")
    recipe = recipe_loader.run(recipe_path, p, only=list(only))
    return {"verified": recipe.rt.verified, "failed_steps": list(recipe.rt.failed_steps)}


def print_report(report):
    """适配报告：关成几个、哪几步没做成。部分完成不说成成功。"""
    verified = report["verified"]
    failed = report["failed_steps"]
    print("\n================ 适配报告（草稿 · 安全模式自检） ================")
    print(f"  回读确认关闭：{verified} 项")
    print(f"  未完成步骤：{len(failed)} 个" + (f"（{'、'.join(failed)}）" if failed else ""))
    ok = verified > 0 and not failed
    if ok:
        print("结论：自检通过——勾选的开关都已找到并回读确认关闭。")
        print("      这仍不代表适配完成：请人工在手机上核对入口和效果，再决定是否转为正式机型脚本。")
    elif verified == 0:
        print("结论：自检未通过——没有回读确认关闭任何开关。请把上面的开关名和步骤名交给人工核对。")
    else:
        print("结论：部分完成——已确认关闭的项见上；没做成的那几步必须人工在手机上核对，")
        print("      不能把部分完成当成适配成功。")
    print("==================================================================")
    return ok


def cmd_check(rest):
    if len(rest) < 3 or rest[0] != "-s":
        return fail("用法：run.py adapt check -s <序列号> <草稿.toml> [段名 …]")
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


# ---------- 试入口 ----------


def _installed_packages(p):
    """一次 `pm list packages` 换成集合：逐条 `pm path` 每次都要起一个进程。"""
    out = p.reader.shell("pm list packages").output or ""
    return {line.strip().split("package:", 1)[1] for line in out.splitlines() if "package:" in line}


def _page_texts(p):
    """这一屏的文字。半截 dump 解析失败按「这屏没有文字」处理，与 `Phone.has_text()` 同口径。"""
    try:
        return [t for t, _, _ in p.texts()]
    except ET.ParseError:
        return []


def survey(p, family, words, log=print, now=None, sleep=None):
    """拿同家族已经验证过的直达页面在这台手机上逐条试：打不打得开、页面上有哪些同分组的词条、
    同族脚本用过的 App 这台装了哪些。只读：不点开关、不点弹窗，看到协议只标注。

    不走 `Phone.start`：它的 DISMISS 会替人点「取消 / 不同意」。打不开的判据与
    `entries.open_direct()` 那一处相同（退出码或 Error / Exception）；`Direct.expect` 非空时还要求
    看见判据文字，与 `entries.reach()` 同口径——焦点对上了但内容不是那一页，引擎会换下一档。
    命中词条只比同分组的词：全量比对会把「应用商店」页报出「浏览器」组的词。
    `now` / `sleep` 给测试换掉真实等待，与 `entries.reach()` 同口径。返回每条入口的结果。"""
    import time
    import wait

    now = now or time.time
    sleep = sleep or time.sleep
    rows = []
    for group, entry in entries.ENTRIES.get(family, {}).items():
        for d in entry.direct:
            page = entries.full(d.pkg, d.activity)
            result = p.reader.shell(entries.start_command(d, wait=True))
            if getattr(result, "exit_code", 0) or re.search(r"Error|Exception", result.output or "", re.I):
                log(f"✗ 打不开  {group} {page}")
                rows.append({"group": group, "page": page, "landed": False, "expect": False, "words": []})
                continue
            if not wait.until(lambda: entries.landed(p, d), timeout=4, poll=0.2, now=now, sleep=sleep):  # noqa: B023 - d 当轮创建当轮消费，until 同步轮询
                log(f"落在别处（实际 {p.focus() or '未知页面'}）  {group} {page}")
                rows.append({"group": group, "page": page, "landed": False, "expect": False, "words": []})
                continue
            if d.expect and not p.expect_page(d.expect, 3):
                log(f"! {group} {page}  落在这一页，但没看到「{d.expect}」")
                rows.append({"group": group, "page": page, "landed": True, "expect": False, "words": []})
                continue
            shown = _page_texts(p)
            normalized = [vocab.key_of(t) for t in shown]
            hits, seen = [], set()
            for word in words:
                key = vocab.key_of(word.text)
                if (word.family == family and word.group == group and key not in seen
                        and any(key in text for text in normalized)):
                    seen.add(key)
                    hits.append(word.text)
            agreement = any("同意" in text for text in shown)
            log(f"✓ {group} {page}" + ("（弹着协议，没有点）" if agreement else ""))
            if hits:
                log(f"    同组词条：{'、'.join(hits)}")
            rows.append({"group": group, "page": page, "landed": True, "expect": True, "words": hits})
    apps, searches = [], []
    for entry in entries.ENTRIES.get(family, {}).values():
        apps += [d.pkg for d in entry.direct] + ([entry.app] if entry.app else [])
        searches += [s.keyword for s in entry.search]
    apps = list(dict.fromkeys(apps))
    installed = _installed_packages(p) if apps else set()
    missing = [pkg for pkg in apps if pkg not in installed]
    log(f"同族脚本用过的 App：装了 {len(apps) - len(missing)} / {len(apps)} 个"
        + (f"（没装：{'、'.join(missing)}）" if missing else ""))
    log(f"设置搜索词可试：{'、'.join(dict.fromkeys(searches)) or '无'}")
    return rows


def cmd_survey(rest):
    if not rest or rest[0] != "-s" or len(rest) < 2:
        return fail("用法：run.py -s <序列号> adapt survey")
    recipes = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")
    with Phone(rest[1]) as p:
        if p.locked():
            return fail("手机锁屏了，请机主解锁后再跑")
        brand = p.reader.shell("getprop ro.product.brand").output.strip().lower()
        family = entries.FAMILY.get(brand)
        if not family:
            return fail(f"认不出品牌「{brand or '空'}」：入口速查只收了"
                        + "、".join(entries.LABEL[f] for f in entries.ENTRIES) + "的机型")
        groups = entries.ENTRIES.get(family, {})
        if not any(entry.direct for entry in groups.values()):
            return fail(f"{entries.LABEL.get(family, family)}还没有直达入口记录：用 adapt explore 探路")
        words = vocab.scan(recipes).words
        if not any(word.family == family for word in words):
            return fail(f"{entries.LABEL.get(family, family)}的词库是空的：还没有这个家族的机型脚本，先用 adapt explore 探路")
        print(f"{entries.LABEL.get(family, family)}：试 {sum(len(e.direct) for e in groups.values())} 个直达入口，"
              "屏幕会跳，不要碰手机。", flush=True)
        rows = survey(p, family, words)
        p.reader.press("home")
    return 0 if any(row["landed"] and row["expect"] for row in rows) else 1


def cmd_explore(rest):
    if not rest or rest[0] != "-s" or len(rest) < 2:
        return fail("用法：run.py adapt explore -s <序列号> [包名 …]")
    return subprocess.call(script_cmd("explore.py", "-s", rest[1], *rest[2:]))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    sub, rest = argv[0], argv[1:]
    if sub == "survey":
        return cmd_survey(rest)
    if sub == "explore":
        return cmd_explore(rest)
    if sub == "gen":
        return cmd_gen(rest)
    if sub == "check":
        return cmd_check(rest)
    return fail("adapt 后面跟 survey / explore / gen / check。用法：run.py adapt --help")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
