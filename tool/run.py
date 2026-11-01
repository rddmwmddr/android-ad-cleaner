#!/usr/bin/env python3
"""手机去广告 · 总入口。所有命令都要带 -s <序列号>（adb devices 第一列）。

  python3 tool/run.py devices                      列出连着的手机、型号、系统版本、有没有现成机型脚本
  python3 tool/run.py -s 序列号 check              只读：锁屏、机型脚本匹配、广告包挂起状态
  python3 tool/run.py -s 序列号 ui-check           只读：检查手机读屏服务，不点击任何开关
  python3 tool/run.py -s 序列号 backup             改动前快照，存到 backups/<型号>-<时间>/
  python3 tool/run.py -s 序列号 recipe [段名 …]     跑本机型机型脚本（不带段名=全跑）
  python3 tool/run.py -s 序列号 adapt explore [包名 …]  只读：探路新机型 → 探路-<型号>.tsv（末列供人工勾选）
  python3 tool/run.py adapt gen 探路-<型号>.tsv      把人工勾选的开关生成 recipe 草稿（不碰手机；草稿≠适配）
  python3 tool/run.py -s 序列号 adapt check 草稿.py  安全模式自检草稿，输出适配报告（找不到就如实说找不到）
  python3 tool/run.py -s 序列号 chan-scan          只读：列出开着的营销通知渠道 → backups/.../channels.tsv
  python3 tool/run.py -s 序列号 chan-off 清单.tsv   关掉清单里的渠道
  python3 tool/run.py -s 序列号 chan-on  清单.tsv   还原
  python3 tool/run.py -s 序列号 suspend 包名 …       挂起广告包（先征得机主同意），记录到 backups/.../suspended.txt
  python3 tool/run.py -s 序列号 unsuspend [包名 …]   解除挂起（不给包名=解除记录里的全部）
  python3 tool/run.py -s 序列号 quickapp          只读：检测快应用组件（装没装、挂没挂、在不在跑、用没用过）
  python3 tool/run.py -s 序列号 quickapp off      关闭快应用：挂起快应用组件（快递等系统服务依赖的框架自动保留；先征得机主同意）
  python3 tool/run.py -s 序列号 quickapp on       恢复快应用
  python3 tool/run.py -s 序列号 finish             收尾：插电常亮改回备份时的值，提醒关闭开发者模式
  python3 tool/run.py -s 序列号 dev-off --yes      从电脑上关闭开发者模式和 USB 调试（执行后电脑与手机断开）
  python3 tool/run.py -s 序列号 status-json        只读：一次输出全部状态（JSON，给图形界面用）
"""
import glob, json, os, re, subprocess, sys, time
from pathlib import Path
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adb_link
import events
import troubleshooting
from backups import Backups, root_from_env

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tool")
BACKUPS = root_from_env() or os.path.join(ROOT, "backups")

# 各品牌常见的系统广告包（快应用另列在 QUICKAPP）。只在机主同意后挂起；挂起可一条命令还原。
# 键是品牌族（见 FAMILY），不是 ro.product.brand 原值：POCO 归 xiaomi、一加 / realme 归 oppo、iQOO 归 vivo。
AD_PKGS = {
    "oppo": ["com.opos.ads", "com.heytap.pictorial"],
    "honor": [],
    # 第二个是海外版（global / 俄区等）HyperOS 上同一个系统广告组件的包名，国行没有
    "xiaomi": ["com.miui.systemAdSolution", "com.miui.msa.global"],
    "vivo": [],
}

# 快应用组件：免安装的「轻 App」，广告常用 hap:// 链接把人跳进去。
# (包名, 名称, 品牌, 是否实测过挂起)
QUICKAPP = [
    ("com.nearme.instant.platform", "快应用平台", "OPPO / 一加 / realme", True),
    ("com.oppo.instant.local.service", "快应用本地服务", "OPPO / 一加 / realme", True),
    ("com.nearme.instant.card", "快应用卡片", "OPPO / 一加 / realme", True),
    ("com.hihonor.quickengine", "快应用引擎", "荣耀", True),
    ("com.hihonor.quickgame", "快游戏", "荣耀", True),
    ("com.honor.quickgamecenter", "快游戏中心", "荣耀", True),
    ("com.huawei.fastapp", "快应用中心", "华为", False),
    ("com.miui.hybrid", "快应用服务框架", "小米 / Redmi", False),
    ("com.miui.hybrid.accessory", "快应用服务框架辅件", "小米 / Redmi", False),
    ("com.vivo.hybrid", "快应用", "vivo / iQOO", False),
]
# 挂了会坏功能的包，不许挂
NEVER = {"com.heytap.quicksearchbox", "com.coloros.assistantscreen", "com.android.systemui",
         "com.vivo.systemuiplugin", "com.heytap.market", "com.xiaomi.market", "com.hihonor.appmarket"}

# 快应用里挂起会误伤系统功能的组件，quickapp off 不挂。PMX110 / ColorOS 17 逐个单独挂起实测
# （2026-10-30，Issue #335）：只剩 platform 挂起时，负一屏快递卡片能显示缓存，点「全部」打不开详情页，
# 弹「快应用服务框架目前无法使用。该应用是由Shell所管理。」；另两个单独或同时挂起，快递详情页都正常。
QUICKAPP_KEEP = {
    "com.nearme.instant.platform": "快应用平台主框架，负一屏快递助手等系统卡片依赖它，挂起后详情页打不开",
}


class NoAdb(RuntimeError):
    """找不到 adb。和断线一样，文案与退出码由 main() 的出口渲染。"""


def adb():
    """adb 可执行文件。以前是 import 期算一次的模块常量，找不到就当场退出（ADR-0005）。"""
    path = adb_link.adb_path()
    if not path:
        raise NoAdb(adb_link.NO_ADB)
    return path


def fail(message, code=1):
    """命令失败的唯一渲染：与原来的 sys.exit("文案") 一样，文案进 stderr、退出码 1。"""
    print(message, file=sys.stderr)
    return code


def adb_shell(serial, cmd):
    """手机掉线时等它回来重试一次；仍不在就抛 DeviceLost 交给 main() 的出口。

    Issue #147：以前读到空结果仍显示成功。link_lost 事件在 DeviceLost 构造时就发了（ADR-0004），
    所以谁把它转成退出码都不影响事件（ADR-0005）。
    """
    return adb_link.Connection(serial, adb=adb()).shell(cmd)


def sh(serial, cmd, check=False):
    return adb_shell(serial, cmd).stdout.strip()


def sh_all(serial, cmd):
    """stdout + stderr：pm suspend 失败的原因在 stderr 里。"""
    r = adb_shell(serial, cmd)
    return (r.stdout + r.stderr).strip()


MSA = "com.miui.systemAdSolution"
MSA_PKGS = (MSA, "com.miui.msa.global")      # 国行 / 海外版的 msa，挂起后都要断网


def msa_net(serial, enable, pkg=MSA):
    """仅用本系统确实提供的接口；Android 13 等旧系统不伪报断网成功。"""
    help_text = sh_all(serial, "cmd connectivity help")
    required = ["set-package-networking-enabled", "get-package-networking-enabled"]
    if not enable:
        required += ["set-chain3-enabled", "get-chain3-enabled"]
    if not all(re.search(r"(?m)^\s*" + re.escape(command) + r"(?:\s|$)", help_text) for command in required):
        return {"ok": False, "supported": False, "reason": "本系统不支持 msa 断网接口；仅挂起仍可能出现广告"}
    commands = [f"cmd connectivity set-package-networking-enabled {'true' if enable else 'false'} {pkg}"]
    if not enable:
        commands.append("cmd connectivity set-chain3-enabled true")
    for command in commands:
        result = sh_all(serial, command)
        if re.search(r"unknown command|exception|permission denial|error|not supported|denied", result, re.I):
            return {"ok": False, "supported": True, "reason": "系统拒绝更改 msa 网络状态：" + result[-180:]}
    result = sh_all(serial, f"cmd connectivity get-package-networking-enabled {pkg}").strip().lower()
    # HyperOS 实机返回「包名:allow/deny」，部分接口返回布尔值；不接受错误信息中的碰巧匹配。
    expected = {"true", f"{pkg}:allow".lower()} if enable else {"false", f"{pkg}:deny".lower()}
    ok = result in expected
    if ok and not enable:
        chain = sh_all(serial, "cmd connectivity get-chain3-enabled").strip().lower()
        ok = chain in {"chain:enabled", "true"}
    return {"ok": ok, "supported": True, "reason": "" if ok else "msa 网络状态回读未确认成功"}


# 部分 ROM 上 ro.build.version.release 单键读为空，真值在分区属性里（#195：HyperOS 4 /
# 24129PN74C 上 release 单键空，ro.system.build.version.release 是 17）。完整 getprop dump
# 在这台给的是陈旧的 6.0.1、SDK 21，所以只按顺序单键读，不退回 dump——宁可读不到也不报假版本。
ANDROID_RELEASE_KEYS = ("ro.build.version.release",
                        "ro.build.version.release_or_codename",
                        "ro.system.build.version.release",
                        "ro.product.build.version.release",
                        "ro.system_ext.build.version.release")


def prop(serial, k):
    return sh(serial, f"getprop {k}")


def android_release(serial):
    """按 ANDROID_RELEASE_KEYS 的顺序取第一个非空值，都读不到返回空串。"""
    for k in ANDROID_RELEASE_KEYS:
        value = prop(serial, k)
        if value:
            return value
    return ""


def info(serial):
    return {
        "brand": prop(serial, "ro.product.brand"),
        "model": prop(serial, "ro.product.model"),
        "name": prop(serial, "ro.vendor.oplus.market.name") or prop(serial, "ro.product.marketname") or prop(serial, "ro.product.vendor.marketname"),
        "build": prop(serial, "ro.build.display.id"),
        "os": prop(serial, "ro.mi.os.version.incremental") or prop(serial, "ro.build.version.opporom")
              or prop(serial, "ro.vivo.os.build.display.id") or prop(serial, "ro.build.version.magic"),
        # 都读不到时给「未知」：诊断输出留空会被当成没读到（#195 正文第 4 条）
        "android": android_release(serial) or "未知",
    }


FAMILY = {"oppo": "oppo", "oneplus": "oppo", "realme": "oppo", "honor": "honor",
          "xiaomi": "xiaomi", "redmi": "xiaomi", "poco": "xiaomi", "vivo": "vivo", "iqoo": "vivo",
          "meizu": "meizu"}


def ad_packages(brand):
    return AD_PKGS.get(FAMILY.get((brand or "").lower(), ""), [])


# 没有本型号脚本时用的同品牌参考脚本。以前取目录名排第一的那份，社区每加一个机型，
# 别的手机用的参考脚本就可能跟着变（10-28 合并社区机型脚本时发现）；固定成一份经过真机验证的最全的。
REFERENCE = {"oppo": "oppo-PLP120", "honor": "honor-PNM-AN10", "xiaomi": "xiaomi-M154FF", "vivo": "vivo-V2547DA",
             "meizu": "meizu-MEIZU 21 Pro"}


def recipe_meta(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'^BUILD\s*=\s*"([^"]*)"', src, re.M)
    models = re.search(r'^MODELS\s*=\s*\[([^\]]*)\]', src, re.M)
    return {"build": m.group(1) if m else "", "steps": re.findall(r'^@step\("([^"]+)"\)', src, re.M),
            "models": re.findall(r'"([^"]+)"', models.group(1)) if models else []}


def recipe_for(model, brand="", device_info=None):
    """返回 (路径, 是否参考)。先找本型号（目录名或脚本里的 MODELS）；没有就找同品牌别的机型，作参考。"""
    allr = sorted(glob.glob(os.path.join(ROOT, "recipes", "*", "recipe.py")))
    for r in allr:
        d = os.path.basename(os.path.dirname(r))
        if d.endswith("-" + model) or model in recipe_meta(r)["models"]:
            # 一个型号可能有不同系统版本的实测路径。仅在版本明确匹配时选择变体。
            if device_info:
                variants = sorted(glob.glob(os.path.join(os.path.dirname(r), "recipe_*.py")))
                for variant in variants:
                    recorded = recipe_meta(variant)["build"]
                    if recorded and build_ok(device_info, recorded):
                        return variant, False
            return r, False
    fam = FAMILY.get((brand or "").lower())
    preferred = os.path.join(ROOT, "recipes", REFERENCE.get(fam, ""), "recipe.py")
    if fam in REFERENCE and os.path.exists(preferred):
        return preferred, True
    for r in allr:
        if fam and os.path.basename(os.path.dirname(r)).startswith(fam + "-"):
            return r, True
    return None, False


def build_ok(i, rb):
    """录制版本 rb 和这台对不对得上：比 ro.build.display.id，小米再比 HyperOS 版本号。"""
    return (not rb) or i["build"].startswith(rb) or (i.get("os") or "").startswith(rb)


def input_blocked(serial, brand):
    """小米系没开「USB 调试（安全设置）」时，电脑发出的点击会被拒。KEYCODE_UNKNOWN 不触发任何操作。"""
    if FAMILY.get((brand or "").lower()) != "xiaomi":
        return False
    return troubleshooting.input_blocked(sh_all(serial, "input keyevent 0"))


def locked(serial):
    return adb_link.keyguard_showing(sh(serial, adb_link.KEYGUARD_CMD))


def wait_unlocked(serial, timeout=90):
    """锁屏时点亮屏幕，等机主解锁（不代替解锁）。开始执行时手机已锁屏的报告约 15 份（错误日志 10-27）。"""
    sh(serial, "input keyevent KEYCODE_WAKEUP")
    if not locked(serial):
        return True
    print(f"  ! 手机锁屏了：请解锁手机并保持亮屏，解锁后自动继续（最多等 {timeout} 秒）", flush=True)
    events.emit("locked")
    t = time.time()
    while time.time() - t < timeout:
        time.sleep(1)
        if not locked(serial):
            time.sleep(0.8)
            return True
    return False


def latest_backup(serial, create=False):
    m = info(serial)["model"]
    backups = Backups(BACKUPS)
    latest = backups.latest(m)
    if latest and not create:
        return latest
    return backups.create(m)


def display_backup_path(path):
    """Windows 程序和备份可能位于不同盘符，此时不能计算相对路径。"""
    path = os.fspath(path)
    home = os.path.expanduser("~")
    if root_from_env():
        return "~" + path[len(home):] if path.startswith(home + os.sep) else path
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def suspended(serial, pkg):
    out = sh(serial, f"dumpsys package {pkg} | grep -m1 -o 'suspended=[a-z]*'")
    return out.endswith("true")


def installed(serial, pkg):
    return "package:" in sh(serial, f"pm path {pkg}")


def pkg_list(serial, args=""):
    """包列表。部分 ROM 上 `pm list packages` 无论带什么参数都无输出且 exit 0
    （HyperOS 4，Issue #192），这时换 `cmd package list packages`，参数一样。
    两条通路都没读到包名时返回读到的报错原文，快照里留着排障；带过滤参数的清单本来就可能为空。"""
    suffix = f" {args}" if args else ""
    diagnostic = ""
    for command in (f"pm list packages{suffix}", f"cmd package list packages{suffix}"):
        out = sh(serial, command)
        if re.search(r"(?m)^package:", out):
            return out
        diagnostic = diagnostic or out
    return diagnostic


VIVO_QUICKAPP = "switch_quick_app_service"


def quickapp_switch(serial):
    if prop(serial, "ro.product.brand").lower() not in ("vivo", "iqoo"):
        return None
    value = sh(serial, f"settings --user 0 get secure {VIVO_QUICKAPP}")
    return value if value in ("0", "1") else None


def quickapp_setting_backup(serial):
    """跨多次 backup 找回本设备未还原的记录；不借用另一台同型号手机的设置。"""
    for path in sorted(glob.glob(os.path.join(BACKUPS, "*", "quickapp-setting.json")), reverse=True):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("serial") == serial and data.get("key") == VIVO_QUICKAPP and data.get("original") in ("0", "1"):
            return path, data
    return None, None


def set_quickapp_service(serial, restore=False):
    value = quickapp_switch(serial)
    if value is None:
        raise RuntimeError("读不到 vivo 快应用服务开关，未修改")
    path, data = quickapp_setting_backup(serial)
    if restore:
        if data is None:
            raise RuntimeError("没有找到本设备的快应用开关备份，未按默认值开启；请在手机上手动核对")
        target = data["original"]
    else:
        if value == "0":
            return "快应用服务已经关闭，未改动"
        if path is None:
            path = os.path.join(latest_backup(serial), "quickapp-setting.json")
            # 先落盘再改设置；重复关闭不能把最初原值覆盖成 0。
            with open(path, "x", encoding="utf-8") as f:
                json.dump({"serial": serial, "key": VIVO_QUICKAPP, "original": value}, f)
        target = "0"
    sh(serial, f"settings --user 0 put secure {VIVO_QUICKAPP} {target}")
    if quickapp_switch(serial) != target:
        raise RuntimeError("快应用服务开关写入后校验失败，保留原值备份")
    if restore:
        os.remove(path)
    else:
        sh(serial, "am force-stop --user 0 com.vivo.hybrid")
    return f"快应用服务{'已恢复原值 ' + target if restore else '已关闭'}"


def quickapps(serial, with_usage=True):
    """装着的快应用组件，带状态。with_usage=False 跳过 usagestats（部分机型上是大文件，
    只有 check 的「近期打开次数」读它；off / on 不展示这项，不白拉）。
    装机判定先用一次包清单批量过滤，清单两条通路都没读到包名时（HyperOS 4，Issue #192）
    退回逐包 pm path，行为与批量前一致。"""
    ev = sh(serial, "dumpsys usagestats") if with_usage else ""
    disabled = set(re.findall(r"(?m)^package:(\S+)", pkg_list(serial, "--user 0 -d")))
    batch = pkg_list(serial, "--user 0")
    listed = re.search(r"(?m)^package:", batch) is not None
    known = set(re.findall(r"(?m)^package:(\S+)", batch))
    out = []
    for pkg, name, brand, tested in QUICKAPP:
        if listed:
            if pkg not in known:
                continue
        elif not installed(serial, pkg):
            continue
        fg = len(re.findall(rf"type=ACTIVITY_RESUMED package={re.escape(pkg)}\b", ev))
        switch = quickapp_switch(serial) if pkg == "com.vivo.hybrid" else None
        is_suspended = suspended(serial, pkg)
        out.append({
            "pkg": pkg, "name": name, "brand": brand, "tested": tested,
            "keep": pkg in QUICKAPP_KEEP,
            "suspended": is_suspended,
            "closed": is_suspended or switch == "0" or pkg in disabled,   # 以前手动 disable-user 的也算关闭
            "method": "setting" if switch is not None else "suspend",
            "service_switch": switch,
            "running": bool(sh(serial, f"pidof {pkg}") or sh(serial, f"pidof {pkg}:provider")),
            "used": fg,
        })
    return out


def fold_open(serial):
    """折叠屏展开时屏幕接近正方形：引擎会找错位置，要合上用外屏。"""
    out = sh(serial, "wm size")
    m = re.search(r"(\d+)x(\d+)", out.splitlines()[-1] if out else "")
    if not m:
        return False
    w, h = int(m.group(1)), int(m.group(2))
    return min(w, h) / max(w, h) > 0.8


def record(serial, pkgs, fn="suspended.txt", backup=None):
    """记进快照，供 unsuspend 还原。写前去重：同名包反复挂起/关闭时文件不再越写越长
    （读侧 sorted(set(...)) 一直有兜底，这里只是别让文件先胀起来）。
    backup：调用方已经定位过快照目录就传进来，免得再打一轮 info()。"""
    path = os.path.join(backup if backup is not None else latest_backup(serial), fn)
    seen = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            seen.update(line.strip() for line in f)
    with open(path, "a", encoding="utf-8") as f:
        for p in pkgs:
            if p not in seen:
                f.write(p + "\n")
                seen.add(p)


DEV_REMINDER = """
================ 最后一步：关闭开发者模式 ================
收尾不代表每一步都成功，请先核对执行结果。若不再继续排查或重试，建议关闭开发者模式和 USB 调试：
  · 部分银行、支付、游戏 App 检测到 USB 调试开着会提醒或拒绝运行
  · 关掉以后，别人拿你的手机插电脑也连不上

两种关法，选一种：
  1) 手机上：设置 → 搜索「开发者选项」→ 关掉页面最上方的总开关
  2) 电脑上：python3 tool/run.py -s {s} dev-off --yes
     （执行后电脑和手机断开，这是正常的）

关掉开发者模式不会撤销这次的改动：关掉的开关、挂起的包、关掉的通知都保持原样。
以后要还原挂起的包，重新打开开发者模式和 USB 调试即可（见 docs/00-打开开发者模式.md）。
==========================================================
"""


def py(script, *args):
    return subprocess.call(script_cmd(script, *args))


def script_cmd(script, *args):
    """启动 tool/ 里的另一个脚本。打包版（客户端）里 sys.executable 是客户端本身，
    必须带 --cli，否则会再打开一个客户端窗口、引擎没跑起来（Windows 小米 18 Pro Max 反馈）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--cli", script, *args]
    return [sys.executable, os.path.join(TOOL, script), *args]


def cmd_devices(rest):
    out = subprocess.run([adb(), "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    rows = [l.split("\t") for l in out.splitlines()[1:] if "\t" in l]
    if not rows:
        print("没有连着的手机。检查数据线、USB 调试，见 docs/01-准备工作.md")
    for ser, st in rows:
        if st != "device":
            print(f"{ser}\t{st}\t（unauthorized=手机上点「允许 USB 调试」；offline=重插或重开无线调试）"); continue
        i = info(ser); r, ref = recipe_for(i["model"], i["brand"], i)
        tag = (os.path.relpath(r, ROOT) + ("（同品牌参考）" if ref else "")) if r else "无（只能跑通用部分）"
        print(f"{ser}\t{i['name'] or i['brand']+' '+i['model']}\t{i['model']}\t{i['build']}\t机型脚本：{tag}")
    return 0


def cmd_ui_check(serial, rest):
    return py("fast.py", "-s", serial, "check")


def cmd_check(serial, rest):
    i = info(serial); r, ref = recipe_for(i["model"], i["brand"], i)
    print(f"机型：{i['name'] if i['name'].upper().startswith(i['brand'].upper()) else i['brand']+' '+i['name']}（{i['model']}），系统 {i['build']}，Android {i['android']}")
    print(f"锁屏：{'是（请机主解锁）' if locked(serial) else '否'}")
    if input_blocked(serial, i["brand"]):
        print("电脑点击：被系统拒绝。" + troubleshooting.XIAOMI_INPUT)
    if r and ref:
        print(f"机型脚本：本型号没有；同品牌参考 {os.path.relpath(r, ROOT)}。要用：recipe --ref（安全模式：只关脚本里点名的开关，找不到就跳过）")
    elif r:
        rb = recipe_meta(r)["build"]
        ok = build_ok(i, rb)
        print(f"机型脚本：{os.path.relpath(r, ROOT)}；录制版本 {rb or '未标'}，{'版本一致' if ok else '版本不同：用安全模式跑，部分步骤可能找不到入口'}")
    else:
        print("机型脚本：没有。可跑：通知渠道 chan-scan/chan-off、广告包挂起；其余照 docs/清单 手动做，或用 tool/explore.py 探路")
    for n, p in enumerate(ad_packages(i["brand"])):
        exists = "package:" in sh(serial, f"pm path {p}")
        if n and not exists:        # 同族的其他地区包名（海外版 msa）没装就不提，国行不多出一行「未安装」
            continue
        print(f"  广告包 {p}：{'未安装' if not exists else ('已挂起' if suspended(serial, p) else '未挂起')}")
    for q in quickapps(serial, with_usage=False):
        print(f"  快应用 {q['pkg']}（{q['name']}）：{'已关闭' if q['closed'] else '未关闭'}"
              f"（{'系统服务开关' if q['method'] == 'setting' else '挂起状态'}）")
    print(f"插电常亮：{sh(serial, 'settings get global stay_on_while_plugged_in')}")
    return 0


def cmd_backup(serial, rest):
    # 先探活再建目录：读不到包列表时不留半成品快照（后续步骤会把最新目录当成改动前的快照）。
    # 带过滤参数的清单可以合法为空，只有不带参数的完整清单不可能为空。
    probe = pkg_list(serial)
    if not re.search(r"(?m)^package:", probe):
        detail = f"；手机返回：{probe[-180:]}" if probe else ""
        return fail(f"✗ 读不到包列表（pm list 与 cmd package list 都没有包名），未生成快照{detail}")
    d = latest_backup(serial, create=True)
    Path(d, "info.txt").write_text("\n".join(f"{k}={v}" for k, v in info(serial).items()), encoding="utf-8")
    for name, args in (("sys.txt", "--user 0 -s"), ("user.txt", "--user 0 -3"), ("disabled.txt", "--user 0 -d")):
        Path(d, name).write_text(pkg_list(serial, args), encoding="utf-8")
    Path(d, "notif.txt").write_text(sh(serial, "dumpsys notification --noredact"), encoding="utf-8")
    st = "\n".join(f"## {n}\n" + sh(serial, f"settings list {n}") for n in ("system", "secure", "global"))
    Path(d, "settings-before.txt").write_text(st, encoding="utf-8")
    Path(d, "stay_on.txt").write_text(sh(serial, "settings get global stay_on_while_plugged_in"), encoding="utf-8")
    print(f"快照已存：{display_backup_path(d)}")
    return 0


def cmd_recipe(serial, rest):
    i = info(serial); r, ref = recipe_for(i["model"], i["brand"], i)
    use_ref = "--ref" in rest
    rest = [x for x in rest if x != "--ref"]
    if not r or (ref and not use_ref):
        return fail("这个型号没有机型脚本。" + (f"同品牌有参考脚本 {os.path.relpath(r, ROOT)}，加 --ref 试用。" if r else "") +
                    "写法见 docs/04-给新机型写脚本.md")
    safe_mode = bool(ref or not build_ok(i, recipe_meta(r)["build"]))
    if safe_mode:
        print("⚠ 安全模式：这份机型脚本不是按这台的型号和系统版本录的。只关脚本里点名的开关，找不到入口的步骤跳过。")
    stay_on = sh(serial, "settings get global stay_on_while_plugged_in")
    message, rc = "", 0
    try:
        sh(serial, "settings put global stay_on_while_plugged_in 7")
        if wait_unlocked(serial):
            rc = py("fast.py", "-s", serial, "run", r, *(["--ref"] if safe_mode else []), *rest)
        else:
            message = "✗ 手机一直锁屏，本步骤没有执行。请解锁手机、保持亮屏后重试"
    finally:
        # 恢复插电常亮先于报错：旧代码里 sys.exit 挂起的文案要等 finally 跑完才打印，
        # 恢复这一步自己失败时，stderr 上只有那一条（恢复的错顶掉了锁屏文案）。
        sh(serial, f"settings put global stay_on_while_plugged_in {int(stay_on) if stay_on.isdigit() else 0}")
    return fail(message) if message else rc


def cmd_chan_scan(serial, rest):
    d = latest_backup(serial)
    result = subprocess.run(script_cmd("chan_fast.py", "-s", serial, "scan"),
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode
    out = result.stdout
    f = os.path.join(d, "channels.tsv")
    Path(f).write_text(
        "# 包名\t渠道id\t渠道名\t应用名。人工核对：删掉服务类（热点共享、红包、防盗、直播提醒等）后再 chan-off\n" + out, encoding="utf-8")
    print(out); print(f"候选清单：{display_backup_path(f)}（共 {out.count(chr(10))} 条）")
    return 0


def chan(serial, rest, action):
    if not rest:
        return fail("要给清单文件，比如 backups/<型号>-<时间>/channels.tsv")
    return py("chan_fast.py", "-s", serial, action, rest[0])


def cmd_chan_off(serial, rest):
    return chan(serial, rest, "off")


def cmd_chan_on(serial, rest):
    return chan(serial, rest, "on")


def cmd_suspend(serial, rest):
    bad = [p for p in rest if p in NEVER]
    if bad:
        return fail(f"这些包挂了会坏功能，不挂：{bad}")
    d = latest_backup(serial)        # 动手前先有改动前的快照目录
    failures = 0
    for p in rest:
        out = sh_all(serial, f"pm suspend --user 0 {p}")
        if suspended(serial, p):
            record(serial, [p], backup=d)
            extra = ""
            if p in MSA_PKGS:
                sh(serial, f"am force-stop {p}")
                network = msa_net(serial, False, p)
                if network["ok"]:
                    extra = "，已禁止联网"
                elif not network["supported"]:
                    # 系统没有这个接口，用户也改不了：挂起已完成，不算失败（错误日志 10-27，7 份报告）
                    extra = "（这台手机的系统没有 msa 断网接口，只做了挂起）"
                else:
                    extra = "；部分完成：" + network["reason"]
                    failures += 1
            print(f"  {p}：已挂起{extra}")
        else:
            failures += 1
            print(f"  {p}：挂起失败（{(out.splitlines() or ['系统没给原因'])[-1][:160]}）")
    return 1 if failures else 0


def cmd_unsuspend(serial, rest):
    pk = rest
    if not pk:
        f = os.path.join(latest_backup(serial), "suspended.txt")
        pk = sorted(set(open(f, encoding="utf-8").read().split())) if os.path.exists(f) else []
    failures = 0
    for p in pk:
        sh(serial, f"pm unsuspend --user 0 {p}")
        extra = ""
        if p in MSA_PKGS:
            network = msa_net(serial, True, p)
            if network["supported"] and not network["ok"]:
                failures += 1
                extra = "；联网还原失败：" + network["reason"]
            elif not network["supported"]:
                extra = "；本机无 msa 断网接口，未更改联网设置"
        still = suspended(serial, p)
        failures += still
        print(p, ("解除挂起失败" if still else "已恢复挂起状态") + extra)
    return 1 if failures else 0


def cmd_quickapp(serial, rest):
    sub = rest[0] if rest else "check"
    qs = quickapps(serial, with_usage=(sub == "check"))
    if not qs:
        print("没有检测到快应用组件。"); return 0
    if sub == "check":
        print(f"检测到 {len(qs)} 个快应用组件：")
        for q in qs:
            if q["keep"]:
                note = "  （保留：%s）" % QUICKAPP_KEEP[q["pkg"]]
            elif q["method"] == "setting":
                note = "  （系统服务开关）"
            else:
                note = "" if q["tested"] else "  （这个包的挂起效果还没实测）"
            print(f"  {q['name']:<10} {q['pkg']:<34} {'已关闭' if q['closed'] else '未关闭'}  "
                  f"{'后台在跑' if q['running'] else '没在跑'}  "
                  f"{'近期打开过 %d 次' % q['used'] if q['used'] else '近期没打开过'}"
                  f"{note}")
        h = sh(serial, "pm query-activities --brief -a android.intent.action.VIEW -d hap://app/x")
        who = list(dict.fromkeys(re.findall(r"^\s*(\S+/\S+)$", h, re.M)))
        handlers = "、".join(who)
        if [q for q in qs if not q["closed"] and not q["keep"]]:
            if who:
                print(f"hap:// 链接由 {handlers} 接管：网页或 App 里的广告可以用这类链接跳进快应用。")
            print("关闭：python3 tool/run.py -s %s quickapp off（要机主同意，可还原）" % serial)
        else:
            print("可挂起的快应用组件已关闭（保留项除外）；恢复：quickapp on")
            if who:
                # 保留平台就等于留着 hap:// 入口，不能写成广告已拦下
                print(f"hap:// 链接仍由 {handlers} 接管（保留项）：广告仍可能跳进快应用。")
        return 0
    if sub == "off":
        todo = [q["pkg"] for q in qs if not q["closed"] and q["method"] == "suspend" and not q["keep"]]
        why = {}
        for q in qs:
            if q["keep"]:
                print(f"  保留 {q['name']}（{q['pkg']}）：{QUICKAPP_KEEP[q['pkg']]}")
            elif q["method"] == "setting":
                try:
                    print(set_quickapp_service(serial))
                except (adb_link.DeviceLost, NoAdb):
                    raise                      # 断线不是这条命令的失败，别降级成「某个组件没关掉」（#293）
                except (RuntimeError, OSError, ValueError) as e:
                    why[q["pkg"]] = str(e)
        for p in todo:
            why[p] = sh_all(serial, f"pm suspend --user 0 {p}")
            if suspended(serial, p):
                sh(serial, f"am force-stop --user 0 {p}")
        done = [p for p in todo if suspended(serial, p)]
        record(serial, done)
        after = quickapps(serial, with_usage=False)
        bad = []
        for q in after:
            if q["keep"]:
                print(f"  {q['name']:<10} {q['pkg']:<34} 保留（不挂起）")
                continue
            ok = q["closed"]
            reason = "" if ok else "（" + ((why.get(q["pkg"]) or "").splitlines() or ["系统没给原因"])[-1][:160] + "）"
            print(f"  {q['name']:<10} {q['pkg']:<34} {'已关闭' if ok else '关闭失败' + reason}")
            if not ok:
                bad.append(q)
        if not bad:
            print("快应用组件已关闭（保留项除外）。请按常用入口核对效果；恢复：quickapp on")
            if any(q["keep"] and not q["closed"] for q in after):
                print("保留项仍接管 hap:// 链接：广告仍可能跳进快应用。")
            return 0
        # Issue #7：vivo 的快应用挂起被系统拒绝。如实报失败，不说「已关闭」
        print(f"有 {len(bad)} 个快应用组件关闭失败。可以在手机上检查快应用服务开关，或仅关掉它的通知："
              "设置 → 通知 → 找到「" + "」「".join(q["name"] for q in bad) + "」→ 关掉「允许通知」。")
        return 1
    if sub == "on":
        failures = 0
        for q in qs:
            if q["method"] == "setting":
                try:
                    print(set_quickapp_service(serial, restore=True))
                except (adb_link.DeviceLost, NoAdb):
                    raise                      # 同上：断线交给出口，不写成「还原失败」
                except (RuntimeError, OSError, ValueError) as e:
                    print(f"  ✗ {e}"); failures += 1
            if q["suspended"]:
                sh(serial, f"pm unsuspend --user 0 {q['pkg']}")
                failed = suspended(serial, q['pkg'])
                failures += failed
                print(f"  {q['name']}: {'还原挂起失败' if failed else '已解除挂起'}")
        return 1 if failures else 0
    return fail("quickapp 后面跟 check / off / on")


def cmd_finish(serial, rest):
    f = os.path.join(latest_backup(serial), "stay_on.txt")
    v = open(f, encoding="utf-8").read().strip() if os.path.exists(f) else "0"
    sh(serial, f"settings put global stay_on_while_plugged_in {v or 0}")
    sh(serial, "input keyevent HOME")
    print(f"插电常亮已改回 {v or 0}")
    on = sh(serial, "settings get global development_settings_enabled") == "1"
    if on:
        msg = DEV_REMINDER.format(s=serial)
        if os.environ.get("AAC_GUI"):
            msg = msg.replace(f"2) 电脑上：python3 tool/run.py -s {serial} dev-off --yes", "2) 电脑上：点客户端完成页的「帮我关闭」")
        print(msg)
    return 0


def cmd_status_json(serial, rest):
    i = info(serial); r, ref = recipe_for(i["model"], i["brand"], i); steps, rb, ok = [], "", True
    if r:
        meta = recipe_meta(r)
        steps, rb = meta["steps"], meta["build"]
        ok = (not ref) and build_ok(i, rb)
    ads = [{"pkg": p, "suspended": suspended(serial, p)} for p in ad_packages(i["brand"]) if installed(serial, p)]
    backup = Backups(BACKUPS).latest(i["model"])
    print(json.dumps({
        "info": i, "locked": locked(serial),
        "recipe": os.path.relpath(r, ROOT) if r else None, "recipe_ref": ref, "recipe_build": rb, "recipe_ok": ok, "steps": steps,
        "ads": ads, "quickapps": quickapps(serial),
        "stay_on": sh(serial, "settings get global stay_on_while_plugged_in"),
        "dev": sh(serial, "settings get global development_settings_enabled") == "1",
        "backup": os.path.relpath(backup, BACKUPS) if backup else None,
        "fold_open": fold_open(serial),
        "input_blocked": input_blocked(serial, i["brand"]),
    }, ensure_ascii=False))
    return 0


def cmd_dev_off(serial, rest):
    if "--yes" not in rest:
        return fail("这一步会关闭开发者模式和 USB 调试，电脑随后与手机断开。确认后加 --yes 再执行")
    print("正在关闭开发者模式……执行后电脑会和手机断开，这是正常的。")
    sh(serial, "settings put global adb_wifi_enabled 0; settings put global development_settings_enabled 0; "
               "settings put global adb_enabled 0")
    print("已发出关闭指令。请在手机上打开 设置 → 搜索「开发者选项」，确认总开关是关着的。")
    return 0


COMMANDS = {
    "ui-check": cmd_ui_check,
    "check": cmd_check,
    "backup": cmd_backup,
    "recipe": cmd_recipe,
    "chan-scan": cmd_chan_scan,
    "chan-off": cmd_chan_off,
    "chan-on": cmd_chan_on,
    "suspend": cmd_suspend,
    "unsuspend": cmd_unsuspend,
    "quickapp": cmd_quickapp,
    "finish": cmd_finish,
    "status-json": cmd_status_json,
    "dev-off": cmd_dev_off,
}


def dispatch(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return 0
    if a[0] == "devices":
        return cmd_devices(a[1:])
    if a[0] == "adapt":
        return py("adapt.py", *a[1:])
    # 以前 adb 在 import 期就解析，找不到时**任何**调用（含参数写错）都先报这一句；保留同样的先后。
    adb()
    if a[0] != "-s" or len(a) < 3:
        return fail("命令格式：run.py -s <序列号> <命令>。先跑 run.py devices 看序列号")
    handler = COMMANDS.get(a[2])
    if handler is None:
        print(__doc__); return 0
    return handler(a[1], a[3:])


def main(argv=None):
    """唯一出口：命令只返回退出码，断线与「找不到 adb」在这里变成文案 + 退出码 1。"""
    try:
        return dispatch(list(sys.argv[1:] if argv is None else argv))
    except (adb_link.DeviceLost, NoAdb) as error:
        return fail(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
