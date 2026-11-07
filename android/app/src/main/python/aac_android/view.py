"""手机版界面要用的判断。放在 Python 是为了 CI 不连手机也测得到，Compose 那边只管画。

桌面版同样的判断在 gui/web/index.html（summarize、showDetect、sendFeedback），改口径时两边都要看。
"""
import json
import os
import re
import time
from urllib.parse import quote

BASE = ""       # 解出来的 aac/ 目录，boot() 填

REPO = "https://github.com/rddmwmddr/android-ad-cleaner"
URL_LIMIT = 7500        # 网址太长浏览器会截断
FEEDBACK = {"bug": ("bug_report.md", "[问题] "),
            "idea": ("feature_request.md", "[建议] "),
            "device": ("new_device.md", "[新机型] ")}

CHECKLIST = {"OPPO": "OPPO-ColorOS.md", "ONEPLUS": "OPPO-ColorOS.md", "REALME": "OPPO-ColorOS.md",
             "HONOR": "荣耀-MagicOS.md",
             "XIAOMI": "小米-HyperOS.md", "REDMI": "小米-HyperOS.md", "POCO": "小米-HyperOS.md",
             "VIVO": "vivo-OriginOS.md", "IQOO": "vivo-OriginOS.md"}
CHECKLIST_NAME = {"OPPO-ColorOS.md": "OPPO / ColorOS", "荣耀-MagicOS.md": "荣耀 / MagicOS",
                  "小米-HyperOS.md": "小米 / HyperOS", "vivo-OriginOS.md": "vivo / OriginOS"}

AD_NAMES = {"com.opos.ads": "OPPO 广告服务",
            "com.heytap.pictorial": "OPPO 乐划锁屏（锁屏杂志）",
            "com.miui.systemAdSolution": "小米系统广告组件。尝试挂起并禁止联网；旧系统可能不支持断网，会报告部分完成，开屏广告也可能仍出现"}

# brand-taps.json 的品牌列是给人看的（「小米 / Redmi / POCO」），这里把 Build.BRAND 对到它
BRAND_KEYS = {"xiaomi": "小米", "redmi": "小米", "poco": "小米", "vivo": "vivo", "iqoo": "vivo",
              "oppo": "OPPO", "oneplus": "OPPO", "realme": "OPPO", "honor": "荣耀", "huawei": "荣耀"}
XIAOMI = {"xiaomi", "redmi", "poco"}


def _encode(text):
    """等同 JS 的 encodeURIComponent。"""
    return quote(text, safe="-_.!~*'()")


def _run_summary(text, turned_off):
    """「机型脚本跑完」那行只有关掉几个，另两类结局要从 tail 里数（#758）。

    不动的项只认 `tool/fast.py` 的 `off()` 末尾那句「核对 X 项，调整 Y 项」：回读确认 /
    调整 N 项 是各机型脚本自己写的、说法不统一，数不准。X−Y 要扣两档「没动但不是本来就
    关着」的：灰态、以及「✗ 关不掉 / 打不开」。带外没点的行仍在 X 里（CONTEXT.md 的
    「拨动计划」），归进「无需改动」。

    几份 vivo / OPPO 脚本自打「✗ 关不掉」却不用核对行（V2547A、V2545A、V1986A、PKH110），
    与 p.off() 的段混在一次运行里会被多扣；tail 只留最近 80 行（`gui/app.py` 的 `_log`），
    日志更长时前几页少算。两处都只让这个数偏小，好过把没拨成说成没事。
    """
    parts = [f"关了 {turned_off} 个开关"]
    same = sum(int(x) - int(y) for x, y in re.findall(r"核对 (\d+) 项，调整 (\d+) 项", text))
    same -= text.count("被上级开关禁用（开关是灰的），未改动")
    same -= len(re.findall(r"✗ (?:关不掉|打不开) ", text))
    if same > 0:
        parts.append(f"{same} 项核对过无需改动")
    m = re.search(r"未完成步骤：(.*)", text)
    if m:
        names = [n.strip() for n in m.group(1).split("、") if n.strip()]
        if names:
            parts.append(f"{len(names)} 段未完成（{names[0]}{' 等' if len(names) > 1 else ''}）")
    return "；".join(parts)


def summarize(result):
    """一步的结果用一句话说；认不出模式就取日志末行（所以机器行不能进 tail）。"""
    tail = result.get("tail") or []
    text = "\n".join(tail)
    m = re.search(r"机型脚本跑完：关了 (\d+) 个，(\d+) 秒", text)
    if m:
        return _run_summary(text, int(m.group(1)))
    m = re.search(r"拨了 (\d+) 个", text)
    if m:
        left = re.search(r"仍开着: (\d+) 个", text)
        return f"关了 {m.group(1)} 个渠道" + (f"，复查仍开着 {left.group(1)} 个" if left else "")
    if "快应用组件已关闭" in text:
        return f"{len(re.findall(r'已关闭$', text, re.M))} 个组件已关闭"
    if "快照已存" in text:
        return "已保存"
    lines = [line for line in tail if line]
    return lines[-1] if lines else ""


def outcome(run):
    """这次执行怎么算：点了停止不算出错。"""
    results = run.get("results") or []
    if all(r.get("rc") == 0 for r in results) and not run.get("cancel"):
        return "ok"
    if any(r.get("rc") != 0 and not r.get("stopped") for r in results):
        return "failed"
    return "stopped"


class StallWatch:
    """这一轮多久没有进展了：步骤没变、日志没有新行。已经暂停的不算。
    引擎卡住时界面上的动画还在动，用户分不出来，要靠这个说出来。"""

    AFTER = 60      # 秒。正常的一页也可能读几十秒，太短会误报

    def __init__(self, now=time.monotonic):
        self.now = now
        self.mark = None
        self.since = now()

    def update(self, run):
        """返回已经停了多少秒；还没到门槛、没在跑、在暂停时都是 0。"""
        mark = (run.get("idx"), run.get("next"))
        if mark != self.mark or not run.get("running") or run.get("paused"):
            self.mark, self.since = mark, self.now()
            return 0
        quiet = int(self.now() - self.since)
        return quiet if quiet >= self.AFTER else 0


WATCH = StallWatch()


def poll(api, since=0):
    run = dict(api.poll(since))
    run["results"] = [{**r, "summary": summarize(r)} for r in run.get("results") or []]
    run["outcome"] = outcome(run)
    run["stalled"] = WATCH.update(run)
    return run


def _warnings(status, fold_block):
    out = []
    if status.get("locked"):
        out.append("手机锁屏了。请解锁手机并保持亮屏，然后点「重新检测」。")
    if status.get("input_blocked"):
        out.append("系统拒绝了模拟点按。小米 / Redmi / POCO 要在「开发者选项」里打开「USB 调试（安全设置）」"
                   "（需插 SIM 卡、登录小米账号），等风险提示倒计时结束点「确定」，再重新检测。"
                   "还是不行就重启手机再检测。不开它，自动关开关和营销通知都会失败。")
    if status.get("fold_open"):
        out.append("这是展开的折叠屏。展开后是左右分栏，自动关 App 开关会找错位置。合上手机用外屏，再重新检测。"
                   if fold_block else
                   "这是展开的折叠屏。营销通知、快应用、广告组件不受影响，可以继续。")
    return out


def _recipe(status, info):
    if not status.get("steps"):
        return None, ""
    ref = bool(status.get("recipe_ref"))
    ok = bool(status.get("recipe_ok"))
    recipe = status.get("recipe") or ""
    label = f"试用同品牌参考脚本（{recipe.split('/')[1]} 录制）" if ref and "/" in recipe else (
        "试用同品牌参考脚本" if ref else "按机型脚本自动关")
    note = ("安全模式：只关脚本里点名的开关，不做整页全关；页面不一样时，找不到入口的步骤会跳过。" if ref or not ok
            else "系统广告、负一屏、搜索、商店、浏览器、主题等 App 里的推荐和广告开关。")
    if recipe and not ref and not ok:
        note = f"脚本按 {status.get('recipe_build')} 录，这台是 {info.get('os') or info.get('build')}。" + note
    return label, note + "「防止 / 限制广告跟踪」这类保护开关会打开。"


def _checklist(status, info):
    """没有本机脚本时，App 里的开关要照手动清单关。"""
    if status.get("recipe") and not status.get("recipe_ref"):
        return "", ""
    name = CHECKLIST.get((info.get("brand") or "").upper())
    url = f"{REPO}/blob/main/docs/{_encode('清单')}/{_encode(name) if name else 'README.md'}"
    return CHECKLIST_NAME.get(name, ""), url


def _quickapp(status):
    apps = status.get("quickapps") or []
    on = [q for q in apps if not q.get("closed") and not q.get("keep")]
    kept = [q for q in apps if q.get("keep")]
    if not on:
        if not apps:
            return [], "", "没有检测到"
        return [], "", f"已关闭（保留 {len(kept)} 个系统组件）" if kept else "已关闭"
    keep = ("快应用平台会保留（负一屏快递卡片等系统服务依赖它），广告仍可能通过 hap:// 跳进快应用" if kept
            else "关闭后系统会拦截这类入口")
    used = "检测到近期打开过，确认不是你主动在用。" if any(q.get("used") for q in on) else "请确认负一屏快递卡片等常用服务不依赖快应用。"
    return ([q.get("name", "") for q in on],
            f"广告常用 hap:// 链接把人跳进快应用。{keep}；vivo 优先使用快应用服务开关，其他支持的机型使用挂起。{used}可还原。",
            "")


def _ads(status):
    ads = status.get("ads") or []
    on = [{"pkg": a["pkg"], "name": AD_NAMES.get(a["pkg"], "系统广告组件")} for a in ads if not a.get("suspended")]
    return on, "" if on else ("已挂起" if ads else "没有已知的")


def detect(api, serial):
    """检测结果 + 界面要说的话；`blocked` 为真时挡住开始（锁屏、点按被拒、展开的折叠屏）。"""
    status = api.status(serial)
    if status.get("error"):
        return {"error": status["error"]}
    info = status.get("info") or {}
    steps = status.get("steps") or []
    fold_block = bool(status.get("fold_open") and steps)
    label, note = _recipe(status, info)
    manual_name, manual_url = _checklist(status, info)
    qa_names, qa_note, qa_state = _quickapp(status)
    ads, ads_state = _ads(status)
    return {"name": info.get("name") or f"{info.get('brand', '')} {info.get('model', '')}".strip(),
            "model": info.get("model", ""),
            "warnings": _warnings(status, fold_block),
            "blocked": bool(status.get("locked") or status.get("input_blocked") or fold_block),
            "steps": steps, "ref": bool(status.get("recipe_ref")),
            "recipe_label": label, "recipe_note": note,
            "manual_name": manual_name, "manual_url": manual_url,
            "quickapps": qa_names, "quickapp_note": qa_note, "quickapp_state": qa_state,
            "ads": ads, "ads_state": ads_state}


def brand_guide(api, brand):
    """首次设置时只说这个品牌的路径。表格的单一来源是 docs/手机版教程/brand-taps.json（#654）。"""
    key = (brand or "").lower()
    tap = "「关于手机」里的「版本号」"
    try:
        with open(os.path.join(BASE, "docs", "brand-taps.json"), encoding="utf-8") as f:
            rows = json.load(f)["rows"]
        word = BRAND_KEYS.get(key)
        row = next((r for r in rows if word and word in r["brand"]), None)
        if row:
            tap = row["tap"]
    except (OSError, ValueError, KeyError):
        pass
    return {"tap": tap, "xiaomi": key in XIAOMI}


SETUP_AT = {"need_dev": 0, "need_wifi": 1, "need_pair": 2}


def setup_steps(brand=""):
    """首次设置的三步。页面与通知栏取同一份，别在 Kotlin 再写一遍（#646）。"""
    g = brand_guide(None, brand)
    tap, xiaomi = g["tap"], g["xiaomi"]
    return [
        {"key": "about", "title": "打开开发者选项", "action": "打开「关于手机」",
         "lines": ["点下面的按钮，进入系统设置",
                   f"连点{tap} 7 下，输入锁屏密码",
                   "看到「已处于开发者模式」，回到这里"],
         "note": "",
         "notice": {"title": "第 1 步，共 3 步：打开开发者选项",
                    "text": f"连点{tap} 7 下，输入锁屏密码；看到「已处于开发者模式」就回到「肉呆去广告」。"}},
        {"key": "dev", "title": "打开无线调试", "action": "打开开发者选项",
         "lines": ["连上 Wi-Fi，点下面的按钮"]
                  + (["打开「USB 调试（安全设置）」，不然点不动下一个开关"] if xiaomi else [])
                  + ["打开「无线调试」", "弹窗里勾「始终允许」，点「允许」"],
         "note": "",
         "notice": {"title": "第 2 步，共 3 步：打开无线调试",
                    "text": ("先打开「USB 调试（安全设置）」；" if xiaomi else "")
                            + "打开「无线调试」，弹窗里勾「始终允许」再点「允许」，然后回到「肉呆去广告」。"}},
        {"key": "pair", "title": "授权本 App", "action": "开始授权",
         "lines": ["点下面的按钮，共享屏幕时选「整个屏幕」，点「立即开始」",
                   "在打开的页面点「无线调试」→「输入配对码配对设备」" if xiaomi
                   else "在打开的页面点「无线调试」→「使用配对码配对设备」",
                   "本 App 读出 6 位数字自己完成授权，你不用输入"],
         "note": "截屏只在这台手机上识别数字，不保存、不上传，授权完成就停。",
         # 这一阶段的指引由 PairingService 的通知给（自动读码或退回手填）；
         # 另发一条「回 App 重新开始」会把人推进 ADR-0015 说的重开死循环。
         "notice": None},
    ]


def setup_guide(api, brand=""):
    """首次设置要的三步，以及每个授权状态是第几步；界面与通知栏都从这里取（#646）。"""
    return {"steps": setup_steps(brand), "at": SETUP_AT}


def feedback_url(kind, text, diag):
    """返回 (网址, 要放进剪贴板的全文)。网址太长时里面只留摘要，全文走剪贴板。"""
    template, prefix = FEEDBACK.get(kind, FEEDBACK["bug"])
    title = prefix + text.split("\n")[0][:60]
    body = f"## 描述\n\n{text}\n" + (f"\n## 诊断信息\n\n{diag}\n" if diag else "")
    base = f"{REPO}/issues/new?template={template}&title={_encode(title)}&body="
    url = base + _encode(body)
    if len(url) <= URL_LIMIT:
        return url, ""
    head = diag.split("<details>")[0].strip()
    found = re.search(r"```text\n([\s\S]*?)\n```", diag)
    tail = [line for line in (found.group(1) if found else "").split("\n") if line.strip()]

    def brief(n):
        kept = "\n".join(tail[-n:]) if n else ""
        return (f"## 描述\n\n{text}\n\n## 诊断信息\n\n{head}\n\n最近的日志（节选）：\n\n```text\n{kept}\n```\n\n"
                "（完整诊断已复制到剪贴板，可以粘贴在这里）\n")

    n = 40
    url = base + _encode(brief(n))
    while len(url) > URL_LIMIT and n > 0:
        n -= 5
        url = base + _encode(brief(n))
    if len(url) > URL_LIMIT:
        url = base + _encode(f"## 描述\n\n{text}\n\n## 诊断信息\n\n（内容较长，已复制到剪贴板，请在这里粘贴）\n")
    return url, body


def send_feedback(api, kind, text, diag):
    url, clip = feedback_url(kind, text, diag)
    if clip:
        api.copy_text(clip)
    api.open_url(url)
    return {"trimmed": bool(clip)}


EXPORTS = {"poll": poll, "detect": detect, "brand_guide": brand_guide, "setup_guide": setup_guide,
           "send_feedback": send_feedback}
