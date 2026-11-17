"""反馈附带的设备诊断文本：措辞、排版与脱敏的唯一 owner（rule:dev.client.diagnostics-owner，#1376）。

`gui/app.py` 只负责取数据（`Api` 的实例状态、`Job` 的锁内快照）与两个跑本机命令的探针，
这一段文本怎么拼、什么时候多说一行、哪些字符要脱敏都在这里。判据是「本模块不认识 `Job`、
不认识 `adb devices` 的输出格式」：进来的 `State` 已经是切好的普通值，`Probe` 只给两个查询。
所以本文件没有 `subprocess`、没有平台分支，进 mypy 严格档名单。

`usb_phones()`（PowerShell 枚举）与 `other_adb()`（PowerShell / `ps`）跑本机命令，留在
`gui/app.py`；`os_name()` 被手机版整段换掉措辞，`skip_reason()` 属执行域，也留在那里。
"""
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypeAlias, TypedDict

# Windows 上插着、但 adb 看不到的手机：按 USB 厂商号认品牌，给对应的驱动 / 开关提示（#57 #58 #65 #118 等）。
USB_VENDORS = {"04E8": "三星", "12D1": "华为", "339B": "荣耀", "2717": "小米", "22D9": "OPPO / 一加 / realme",
               "2A70": "一加", "2D95": "vivo / iQOO", "18D1": "Google", "2A45": "魅族", "19D2": "中兴 / 努比亚",
               "22B8": "摩托罗拉", "0B05": "华硕", "17EF": "联想", "05C6": "高通方案"}
DRIVER_HINT = {
    "三星": "Windows 要先装三星官方的 Samsung Android USB Driver，装好后重新插线。",
    "华为": "开发者选项里同时打开「仅充电模式下允许 ADB 调试」。驱动可装华为手机助手获取，装好后退出手机助手再用本工具。"
            "已升级 HarmonyOS NEXT（5.0 及以上，原生鸿蒙）的机型不支持 adb。",
    "荣耀": "开发者选项里同时打开「仅充电模式下允许 ADB 调试」。驱动可装荣耀手机助手获取，装好后退出手机助手再用本工具。",
}
# adb 在 Windows 上只按 android_winusb.inf 里登记的这个 GUID 枚举 USB 接口；手机只登记了厂商
# 自己的 GUID 时，接口状态正常、`adb devices` 却静默为 0 台（#702）。
ADB_INTERFACE_GUID = "f72fe0d4-cbcb-407d-8814-9ed673d0dd6b"
USB_GUID_UNREADABLE = "-"   # PowerShell 与 usb_parse() 之间的约定：注册表没读到
# GUID 只含十六进制数字、连字符与两端的英文花括号；strip 的集合里多出两个 X 也不改结论。
GUID_BRACES = "{}"   # pragma: no mutate 语义等价

# 设备管理器里一台命中设备的六个字段：品牌、设备名、状态、是不是调试接口、硬件 ID、
# 登记的 device interface GUID 元组（`None` 表示没读到，空元组表示读到了但一个都没登记）。
UsbDevice: TypeAlias = tuple[str, str, str, bool, str, tuple[str, ...] | None]


class Probe(Protocol):
    """诊断要的两个本机查询。实现留在 `gui/app.py`（那里才跑子进程）。

    两个都必须惰性：`usb_devices` 只在「adb 看到 0 台」的分支被调用，最坏要等 PowerShell 8 秒，
    所以不能预先填进 `State`。`adb_version` 自带「没有 adb」与「adb 出错：…」两种兜底文案。
    """

    def adb_version(self) -> str: ...

    def usb_devices(self) -> list[UsbDevice]: ...


class ResultRow(TypedDict):
    """执行结果里的一行：跳过原因已由调用方经 `skip_reason()` 预渲染进 `reason`。"""

    title: str
    rc: int
    sec: int
    skipped: bool
    reason: str


class JobView(TypedDict):
    """执行快照里诊断要的三样：序列号（脱敏用）、结果行、已滤掉空行并只留末 60 行的日志。"""

    serial: str | None
    results: list[ResultRow]
    log: list[str]


class State(TypedDict):
    """`Api` 侧整理好的普通映射：模块只排版，不再回读任何对象。"""

    app: str
    version: str
    frozen: bool
    os: str
    machine: str
    adb: str | None
    other_adb: list[str]
    devices: tuple[str, ...]
    status: Mapping[str, Any] | None
    scan_notes: list[str]
    job: JobView | None
    last_error: Mapping[str, Any] | None
    tap_refused: str
    home: str


def usb_hw_id(instance_id: str | None) -> str:
    """InstanceId 里认得出设备的那一段：`USB\\VID_xxxx&PID_xxxx` 加可选的 `&MI_xx`，
    最后一个反斜杠之后的设备序列号丢掉（诊断「序列号一律替换」的口径不能破）。认不出格式返回空。"""
    # 正则写成大写、拿 `upper()` 的副本去比：`re.I` 会多出一个杀不掉的等价 mutant（模式串被小写化后
    # 仍受 `re.I` 保护）。`str()` 就是空串，写 `""` 只会再换一个占位串也能过的等价 mutant。
    parts = (instance_id or str()).split("\\")
    prefix = "\\".join(parts[:2])
    return prefix if re.fullmatch(r"USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}(&MI_[0-9A-F]{2})?", prefix.upper()) else ""


def usb_parse(out: str) -> list[UsbDevice]:
    """把 Get-PnpDevice 那段输出解析成设备表：品牌、设备名、状态、是不是调试接口、硬件 ID、
    登记的 device interface GUID 元组。末字段是 `-` 或整段缺失时算没读到（None），
    空字段算读到了但一个都没登记（空元组）。"""
    found: list[UsbDevice] = []
    for line in out.splitlines():
        parts = line.split("|")
        m = re.match(r"USB\\VID_([0-9A-F]{4})", parts[0].upper())
        if not m:
            continue
        name = parts[1] if len(parts) > 1 else ""
        status = parts[2] if len(parts) > 2 else ""
        # cls 只喂下面那行的 adb 探测，占位串取什么都一样：`str()` 免掉一个杀不掉的等价 mutant。
        cls = parts[3] if len(parts) > 3 else str()
        raw = parts[4] if len(parts) > 4 else USB_GUID_UNREADABLE
        # 名字与类分开搜：中间那个空格不可能落在 `adb|android` 的匹配里，拼起来只是一份逃不掉的等价 mutant。
        adb = any(re.search(r"adb|android", field.lower()) for field in (name, cls))
        guids = None if raw.strip() == USB_GUID_UNREADABLE else tuple(
            g.strip() for g in raw.split(",") if g.strip())
        found.append((USB_VENDORS.get(m.group(1).upper(), "安卓"), name, status, adb,
                      usb_hw_id(parts[0]), guids))
    return found


def usb_guid_note(guids: tuple[str, ...]) -> str:
    """这个接口登记的 device interface GUID 里有没有 adb 要的那个；没有时把它实际登记的 GUID 说出来。"""
    if ADB_INTERFACE_GUID in {g.strip().strip(GUID_BRACES).lower() for g in guids}:
        return "已登记 adb 需要的 device interface GUID"
    registered = "、".join(g for g in guids if g.strip())
    trail = f"（实际登记的 GUID：{registered}）" if registered else "，也没有登记任何 GUID"
    return "未登记 adb 需要的 device interface GUID" + trail


def usb_facts(found: Sequence[UsbDevice], limit: int = 5) -> list[str]:
    """把命中的设备逐台说成诊断行：品牌、设备名、状态、是不是调试接口、硬件 ID。
    只截断设备台数，不替用户判断哪台是手机；带调试接口的排前面，先被截掉的是别的外设（#673）。
    调试接口后面再跟一行它登记的 device interface GUID，所以输出最多两倍 limit 行；读不到就不写（#702）。"""
    ordered = [f for f in found if f[3]] + [f for f in found if not f[3]]
    lines = []
    for brand, name, status, adb, hw, guids in ordered[:limit]:
        lines.append(f"{brand} {name}（{status}，{'调试接口' if adb else '非调试接口'}）硬件 ID：{hw or '未识别'}")
        if adb and guids is not None:
            lines.append(f"{brand} {name} {usb_guid_note(guids)}")
    return lines


def usb_hint(found: Sequence[UsbDevice]) -> str:
    """把设备管理器的结果说成一句人话；没有手机设备时返回空。"""
    if not found:
        return ""
    # 品牌只从带调试接口的设备里取：电脑上还插着别的东西时，列表第一台可能根本不是用户的手机（#357）。
    adb = [f for f in found if f[3]]
    picked = adb or found
    brands = list(dict.fromkeys(f[0] for f in picked))
    if len(brands) > 1:
        # 多台手机同时插着：不猜哪台是用户的，逐台说状态，让用户自己只留一台。
        lines = []
        for b in brands:
            items = [f for f in picked if f[0] == b and f[3]]
            if not items:
                lines.append(f"{b}（没有调试接口）")
            elif any(f[2].upper() != "OK" for f in items):
                lines.append(f"{b}（调试接口的驱动没有装好）")
            else:
                lines.append(f"{b}（调试接口在，但 adb 没连上）")
        return ("电脑识别到多台手机：" + "、".join(lines)
                + "。只留要处理的那一台插着，重新插线后再检测。")
    brand = brands[0]
    if adb and any(f[2].upper() != "OK" for f in adb):
        head = f"电脑识别到{brand}手机的调试接口，但驱动没有装好。"
    elif adb:
        head = f"电脑识别到{brand}手机的调试接口，但 adb 没连上：请退出手机助手类软件和模拟器后重新插线。"
    else:
        head = f"电脑识别到{brand}手机，但没有调试接口：手机上的「USB 调试」还没打开，或没点「允许 USB 调试」。"
    return head + DRIVER_HINT.get(brand, "")


def diagnostics(state: State, probe: Probe) -> str:
    """反馈附带的诊断信息。序列号替换成 <序列号>；不含应用列表和通知内容。"""
    lines = [f"- 客户端：{state['app']} {state['version']}（{'打包版' if state['frozen'] else '源码'}）",
             f"- 电脑：{state['os']}（{state['machine']}）"]
    lines.append(f"- adb：{probe.adb_version()}")
    rows = state["devices"]
    lines.append(f"- adb 设备：{len(rows)} 台" + (f"（{'、'.join(rows)}）" if rows else ""))
    others = [o for o in state["other_adb"]
              if not state["adb"] or os.path.normcase(o) != os.path.normcase(state["adb"])]
    if others:
        lines.append(f"- 其他正在运行的 adb：{'；'.join(others)}")
    if not rows:
        found = probe.usb_devices()
        hint = usb_hint(found)
        if hint:
            lines.append(f"- USB：{hint}")
        lines += [f"- USB 设备：{line}" for line in usb_facts(found)]
    st = state["status"]
    if st and "info" in st:
        i = st["info"]
        nm = i.get("name") or i.get("model")
        if not nm.upper().startswith((i.get("brand") or "").upper()):
            nm = f"{i.get('brand')} {nm}"
        # 借用同品牌参考脚本时 recipe_ok 恒为假（`status-json` 的 `(not ref) and build_ok(...)`），
        # 检测页与手机版都先看 recipe_ref 再谈版本：这里同样分三档（#778）。
        recipe = st.get("recipe")
        if not recipe:
            script = "无"
        elif st.get("recipe_ref"):
            script = f"{recipe}（同品牌参考脚本，录制版本 {st.get('recipe_build') or '未标'}）"
        else:
            # 没标录制版本就无从比对，别写成「一致」（#942）。
            rb = st.get("recipe_build")
            script = f"{recipe}（录制版本 {rb}，{'一致' if st.get('recipe_ok') else '不一致'}）" if rb \
                else f"{recipe}（录制版本 未标）"
        lines += [f"- 手机：{nm}（{i.get('model')}）",
                  f"- 系统：{i.get('os') or i.get('build')}（{i.get('build')}），Android {i.get('android')}",
                  f"- 机型脚本：{script}",
                  f"- 折叠屏展开：{'是' if st.get('fold_open') else '否'}；锁屏：{'是' if st.get('locked') else '否'}"
                  + (state["tap_refused"] if st.get("input_blocked") else "")]
    else:
        lines.append("- 手机：还没检测")
    if state["scan_notes"]:
        # 用户报「候选比预期少」时，判据就是这几条排除计数（#521）。
        lines.append("- 通知扫描附注：" + "；".join(state["scan_notes"]))
    job = state["job"]
    if job:
        lines.append("\n**执行结果**\n")
        for r in job["results"]:
            if r["skipped"]:
                verdict = f"跳过（{r['reason']}）" if r["reason"] else "跳过"
            else:
                verdict = "成功" if r["rc"] == 0 else f"失败（退出码 {r['rc']}）"
            lines.append(f"- {r['title']}：{verdict}，{r['sec']} 秒")
        log = "\n".join(job["log"])
        if job["serial"]:
            log = log.replace(job["serial"], "<序列号>")
        lines.append("\n<details><summary>最近的日志</summary>\n\n```text\n" + log + "\n```\n</details>")
    error = state["last_error"]
    if error:
        detail = error["detail"].replace("```", "~~~")
        lines.append(f"\n<details><summary>最近失败的完整诊断：{error['operation']}</summary>\n\n```text\n{detail}\n```\n</details>")
    report = "\n".join(lines)
    home = state["home"]
    return report.replace(home, "<用户目录>").replace(home.replace("\\", "\\\\"), "<用户目录>")
