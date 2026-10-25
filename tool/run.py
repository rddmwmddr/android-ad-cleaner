#!/usr/bin/env python3
"""手机去广告 · 总入口。所有命令都要带 -s <序列号>（adb devices 第一列）。

  python3 tool/run.py devices                      列出连着的手机、型号、系统版本、有没有现成机型脚本
  python3 tool/run.py -s 序列号 check              只读：锁屏、机型脚本匹配、广告包挂起状态
  python3 tool/run.py -s 序列号 backup             改动前快照，存到 backups/<型号>-<时间>/
  python3 tool/run.py -s 序列号 recipe [段名 …]     跑本机型机型脚本（不带段名=全跑）
  python3 tool/run.py -s 序列号 chan-scan          只读：列出开着的营销通知渠道 → backups/.../channels.tsv
  python3 tool/run.py -s 序列号 chan-off 清单.tsv   关掉清单里的渠道
  python3 tool/run.py -s 序列号 chan-on  清单.tsv   还原
  python3 tool/run.py -s 序列号 notif-off 包名 …     整包关通知（走 POST_NOTIFICATIONS 权限，不用 root）
  python3 tool/run.py -s 序列号 notif-on  [包名 …]   整包恢复通知（不给包名=恢复 notif-off.txt 里的全部）
  python3 tool/run.py -s 序列号 suspend 包名 …       挂起广告包（先征得机主同意），记录到 backups/.../suspended.txt
  python3 tool/run.py -s 序列号 unsuspend [包名 …]   解除挂起（不给包名=解除记录里的全部）
  python3 tool/run.py -s 序列号 quickapp          只读：检测快应用组件（装没装、挂没挂、在不在跑、用没用过）
  python3 tool/run.py -s 序列号 quickapp off      关闭快应用：挂起全部快应用组件（先征得机主同意）
  python3 tool/run.py -s 序列号 quickapp on       恢复快应用
  python3 tool/run.py -s 序列号 finish             收尾：插电常亮改回备份时的值，提醒关闭开发者模式
  python3 tool/run.py -s 序列号 dev-off --yes      从电脑上关闭开发者模式和 USB 调试（执行后电脑与手机断开）
  python3 tool/run.py -s 序列号 status-json        只读：一次输出全部状态（JSON，给图形界面用）
"""
import datetime, glob, json, os, re, shutil, subprocess, sys
from pathlib import Path
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tool")
BACKUPS = os.environ.get("AAC_BACKUPS") or os.path.join(ROOT, "backups")

# 各品牌常见的系统广告包（快应用另列在 QUICKAPP）。只在机主同意后挂起；挂起可一条命令还原。
AD_PKGS = {
    "OPPO": ["com.opos.ads", "com.heytap.pictorial"],
    "OnePlus": ["com.opos.ads", "com.heytap.pictorial"],
    "realme": ["com.opos.ads", "com.heytap.pictorial"],
    "HONOR": [],
    "Xiaomi": ["com.miui.systemAdSolution"],
    "Redmi": ["com.miui.systemAdSolution"],
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


def adb_bin():
    for c in (os.environ.get("ADB"), shutil.which("adb"),
              os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
              os.path.expanduser("~/platform-tools/adb"), os.path.expanduser("~/android-tools/platform-tools/adb")):
        if c and os.path.exists(c):
            return c
    sys.exit("找不到 adb。安装方法见 docs/01-准备工作.md")


ADB = adb_bin()


def sh(serial, cmd, check=False):
    r = subprocess.run([ADB, "-s", serial, "shell", cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=0x08000000 if os.name == "nt" else 0)
    return r.stdout.strip()


def sh_all(serial, cmd):
    """stdout + stderr：pm suspend 失败的原因在 stderr 里。"""
    r = subprocess.run([ADB, "-s", serial, "shell", cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=0x08000000 if os.name == "nt" else 0)
    return (r.stdout + r.stderr).strip()


MSA = "com.miui.systemAdSolution"


def msa_net(serial, enable):
    """小米 msa：只挂起拦不住，系统 App 启动时会把它拉起来拉广告（Issue #1）。再禁止它联网。"""
    sh(serial, f"cmd connectivity set-package-networking-enabled {'true' if enable else 'false'} {MSA}")
    if not enable:
        sh(serial, "cmd connectivity set-chain3-enabled true")
    return sh(serial, f"cmd connectivity get-package-networking-enabled {MSA}")


def prop(serial, k):
    return sh(serial, f"getprop {k}")


def info(serial):
    return {
        "brand": prop(serial, "ro.product.brand"),
        "model": prop(serial, "ro.product.model"),
        "name": prop(serial, "ro.vendor.oplus.market.name") or prop(serial, "ro.product.marketname") or prop(serial, "ro.product.vendor.marketname"),
        "build": prop(serial, "ro.build.display.id"),
        "os": prop(serial, "ro.mi.os.version.incremental") or prop(serial, "ro.build.version.opporom")
              or prop(serial, "ro.vivo.os.build.display.id") or prop(serial, "ro.build.version.magic"),
        "android": prop(serial, "ro.build.version.release"),
    }


FAMILY = {"oppo": "oppo", "oneplus": "oppo", "realme": "oppo", "honor": "honor",
          "xiaomi": "xiaomi", "redmi": "xiaomi", "poco": "xiaomi", "vivo": "vivo", "iqoo": "vivo"}


def recipe_meta(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'^BUILD\s*=\s*"([^"]*)"', src, re.M)
    models = re.search(r'^MODELS\s*=\s*\[([^\]]*)\]', src, re.M)
    return {"build": m.group(1) if m else "", "steps": re.findall(r'^@step\("([^"]+)"\)', src, re.M),
            "models": re.findall(r'"([^"]+)"', models.group(1)) if models else []}


def recipe_for(model, brand=""):
    """返回 (路径, 是否参考)。先找本型号（目录名或脚本里的 MODELS）；没有就找同品牌别的机型，作参考。"""
    allr = sorted(glob.glob(os.path.join(ROOT, "recipes", "*", "recipe.py")))
    for r in allr:
        d = os.path.basename(os.path.dirname(r))
        if d.endswith("-" + model) or model in recipe_meta(r)["models"]:
            return r, False
    fam = FAMILY.get((brand or "").lower())
    for r in allr:
        if fam and os.path.basename(os.path.dirname(r)).startswith(fam + "-"):
            return r, True
    return None, False


def build_ok(i, rb):
    """录制版本 rb 和这台对不对得上：比 ro.build.display.id，小米再比 HyperOS 版本号。"""
    return (not rb) or i["build"].startswith(rb) or (i.get("os") or "").startswith(rb)


def locked(serial):
    return "isKeyguardShowing=true" in sh(serial, "dumpsys window | grep -m1 isKeyguardShowing") or \
           "mDreamingLockscreen=true" in sh(serial, "dumpsys window | grep -m1 mDreamingLockscreen")


def latest_backup(serial, create=False):
    m = info(serial)["model"]
    hits = sorted(glob.glob(os.path.join(BACKUPS, f"{m}-*")))
    if hits and not create:
        return hits[-1]
    d = os.path.join(BACKUPS, f"{m}-{datetime.datetime.now():%Y%m%d-%H%M}")
    os.makedirs(d, exist_ok=True)
    return d


def display_backup_path(path):
    """Windows 程序和备份可能位于不同盘符，此时不能计算相对路径。"""
    path = os.fspath(path)
    home = os.path.expanduser("~")
    if os.environ.get("AAC_BACKUPS"):
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


def app_notif_states(serial, pkgs):
    """整包通知状态：importance=NONE 就是关。一次 dumpsys 覆盖多个包（它将近 1MB，别循环读）。"""
    out = sh(serial, "dumpsys notification --noredact")
    res = {}
    for p in pkgs:
        m = re.search(rf"AppSettings: {re.escape(p)} \(\d+\) importance=(\w+)", out)
        res[p] = m.group(1) if m else ""
    return res


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


def quickapps(serial):
    """装着的快应用组件，带状态。"""
    ev = sh(serial, "dumpsys usagestats")
    out = []
    for pkg, name, brand, tested in QUICKAPP:
        if not installed(serial, pkg):
            continue
        fg = len(re.findall(rf"type=ACTIVITY_RESUMED package={re.escape(pkg)}\b", ev))
        switch = quickapp_switch(serial) if pkg == "com.vivo.hybrid" else None
        is_suspended = suspended(serial, pkg)
        out.append({
            "pkg": pkg, "name": name, "brand": brand, "tested": tested,
            "suspended": is_suspended,
            "closed": is_suspended or switch == "0",
            "method": "setting" if switch is not None else "suspend",
            "service_switch": switch,
            "running": bool(sh(serial, f"pidof {pkg}") or sh(serial, f"pidof {pkg}:provider")),
            "used": fg,
        })
    return out


def fold_open(serial):
    """折叠屏展开时屏幕接近正方形：引擎会找错位置，要合上用外屏。"""
    m = re.search(r"(\d+)x(\d+)", sh(serial, "wm size").splitlines()[-1] if sh(serial, "wm size") else "")
    if not m:
        return False
    w, h = int(m.group(1)), int(m.group(2))
    return min(w, h) / max(w, h) > 0.8


def record(serial, pkgs, fn="suspended.txt"):
    with open(os.path.join(latest_backup(serial), fn), "a", encoding="utf-8") as f:
        for p in pkgs:
            f.write(p + "\n")


DEV_REMINDER = """
================ 最后一步：关闭开发者模式 ================
去广告已经做完。开发者模式和 USB 调试用不到了，建议关掉：
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


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return
    if a[0] == "devices":
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        rows = [l.split("\t") for l in out.splitlines()[1:] if "\t" in l]
        if not rows:
            print("没有连着的手机。检查数据线、USB 调试，见 docs/01-准备工作.md")
        for ser, st in rows:
            if st != "device":
                print(f"{ser}\t{st}\t（unauthorized=手机上点「允许 USB 调试」；offline=重插或重开无线调试）"); continue
            i = info(ser); r, ref = recipe_for(i["model"], i["brand"])
            tag = (os.path.relpath(r, ROOT) + ("（同品牌参考）" if ref else "")) if r else "无（只能跑通用部分）"
            print(f"{ser}\t{i['name'] or i['brand']+' '+i['model']}\t{i['model']}\t{i['build']}\t机型脚本：{tag}")
        return
    if a[0] != "-s" or len(a) < 3:
        sys.exit("命令格式：run.py -s <序列号> <命令>。先跑 run.py devices 看序列号")
    s, cmd, rest = a[1], a[2], a[3:]

    if cmd == "check":
        i = info(s); r, ref = recipe_for(i["model"], i["brand"])
        print(f"机型：{i['name'] if i['name'].upper().startswith(i['brand'].upper()) else i['brand']+' '+i['name']}（{i['model']}），系统 {i['build']}，Android {i['android']}")
        print(f"锁屏：{'是（请机主解锁）' if locked(s) else '否'}")
        if r and ref:
            print(f"机型脚本：本型号没有；同品牌参考 {os.path.relpath(r, ROOT)}。要用：recipe --ref（安全模式：只关脚本里点名的开关，找不到就跳过）")
        elif r:
            rb = recipe_meta(r)["build"]
            ok = build_ok(i, rb)
            print(f"机型脚本：{os.path.relpath(r, ROOT)}；录制版本 {rb or '未标'}，{'版本一致' if ok else '版本不同：用安全模式跑，部分步骤可能找不到入口'}")
        else:
            print("机型脚本：没有。可跑：通知渠道 chan-scan/chan-off、广告包挂起；其余照 docs/清单 手动做，或用 tool/explore.py 探路")
        for p in AD_PKGS.get(i["brand"], []):
            exists = "package:" in sh(s, f"pm path {p}")
            print(f"  广告包 {p}：{'未安装' if not exists else ('已挂起' if suspended(s, p) else '未挂起')}")
        for q in quickapps(s):
            print(f"  快应用 {q['pkg']}（{q['name']}）：{'已关闭' if q['closed'] else '未关闭'}"
                  f"（{'系统服务开关' if q['method'] == 'setting' else '挂起状态'}）")
        print(f"插电常亮：{sh(s, 'settings get global stay_on_while_plugged_in')}")

    elif cmd == "backup":
        d = latest_backup(s, create=True)
        Path(d, "info.txt").write_text("\n".join(f"{k}={v}" for k, v in info(s).items()), encoding="utf-8")
        for name, c in [("sys.txt", "pm list packages --user 0 -s"), ("user.txt", "pm list packages --user 0 -3"),
                        ("disabled.txt", "pm list packages --user 0 -d"), ("notif.txt", "dumpsys notification --noredact")]:
            Path(d, name).write_text(sh(s, c), encoding="utf-8")
        st = "\n".join(f"## {n}\n" + sh(s, f"settings list {n}") for n in ("system", "secure", "global"))
        Path(d, "settings-before.txt").write_text(st, encoding="utf-8")
        Path(d, "stay_on.txt").write_text(sh(s, "settings get global stay_on_while_plugged_in"), encoding="utf-8")
        print(f"快照已存：{display_backup_path(d)}")

    elif cmd == "recipe":
        i = info(s); r, ref = recipe_for(i["model"], i["brand"])
        use_ref = "--ref" in rest
        rest = [x for x in rest if x != "--ref"]
        if not r or (ref and not use_ref):
            sys.exit("这个型号没有机型脚本。" + (f"同品牌有参考脚本 {os.path.relpath(r, ROOT)}，加 --ref 试用。" if r else "") +
                     "写法见 docs/04-给新机型写脚本.md")
        if locked(s):
            sys.exit("手机锁屏了，请机主解锁后再跑")
        if ref or not build_ok(i, recipe_meta(r)["build"]):
            os.environ["AAC_REF"] = "1"                 # 安全模式：fast.py 不做整页全关
            print("⚠ 安全模式：这份机型脚本不是按这台的型号和系统版本录的。只关脚本里点名的开关，找不到入口的步骤跳过。")
        stay_on = sh(s, "settings get global stay_on_while_plugged_in")
        try:
            sh(s, "settings put global stay_on_while_plugged_in 7")
            rc = py("fast.py", "-s", s, "run", r, *rest)
        finally:
            sh(s, f"settings put global stay_on_while_plugged_in {int(stay_on) if stay_on.isdigit() else 0}")
        sys.exit(rc)

    elif cmd == "chan-scan":
        d = latest_backup(s)
        result = subprocess.run(script_cmd("chan_fast.py", "-s", s, "scan"),
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            print(result.stderr or result.stdout, file=sys.stderr)
            sys.exit(result.returncode)
        out = result.stdout
        f = os.path.join(d, "channels.tsv")
        Path(f).write_text(
            "# 包名\t渠道id\t渠道名。人工核对：删掉服务类（热点共享、红包、防盗、直播提醒等）后再 chan-off\n" + out, encoding="utf-8")
        print(out); print(f"候选清单：{display_backup_path(f)}（共 {out.count(chr(10))} 条）")

    elif cmd in ("chan-off", "chan-on"):
        if not rest:
            sys.exit("要给清单文件，比如 backups/<型号>-<时间>/channels.tsv")
        sys.exit(py("chan_fast.py", "-s", s, cmd.split("-")[1], rest[0]))

    elif cmd == "suspend":
        bad = [p for p in rest if p in NEVER]
        if bad:
            sys.exit(f"这些包挂了会坏功能，不挂：{bad}")
        d = latest_backup(s)
        fail = 0
        with open(os.path.join(d, "suspended.txt"), "a", encoding="utf-8") as f:
            for p in rest:
                out = sh_all(s, f"pm suspend --user 0 {p}")
                if suspended(s, p):
                    f.write(p + "\n")
                    extra = ""
                    if p == MSA:
                        sh(s, f"am force-stop {p}")
                        extra = "，已禁止联网" if "false" in msa_net(s, False).lower() else "，禁止联网没成功"
                    print(f"  {p}：已挂起{extra}")
                else:
                    fail += 1
                    print(f"  {p}：挂起失败（{(out.splitlines() or ['系统没给原因'])[-1][:160]}）")
        if fail:
            sys.exit(1)

    elif cmd == "unsuspend":
        pk = rest
        if not pk:
            f = os.path.join(latest_backup(s), "suspended.txt")
            pk = sorted(set(open(f, encoding="utf-8").read().split())) if os.path.exists(f) else []
        for p in pk:
            sh(s, f"pm unsuspend --user 0 {p}")
            if p == MSA:
                msa_net(s, True)
            print(p, "已挂起" if suspended(s, p) else "已恢复")

    elif cmd == "quickapp":
        sub = rest[0] if rest else "check"
        qs = quickapps(s)
        if not qs:
            print("没有检测到快应用组件。"); return
        if sub == "check":
            print(f"检测到 {len(qs)} 个快应用组件：")
            for q in qs:
                print(f"  {q['name']:<10} {q['pkg']:<34} {'已关闭' if q['closed'] else '未关闭'}  "
                      f"{'后台在跑' if q['running'] else '没在跑'}  "
                      f"{'近期打开过 %d 次' % q['used'] if q['used'] else '近期没打开过'}"
                      f"{'  （系统服务开关）' if q['method'] == 'setting' else ('' if q['tested'] else '  （这个包的挂起效果还没实测）')}")
            h = sh(s, "pm query-activities --brief -a android.intent.action.VIEW -d hap://app/x")
            who = re.findall(r"^\s*(\S+/\S+)$", h, re.M)
            if all(q["closed"] for q in qs):
                print("快应用组件已关闭；系统可能显示「应用无法使用」或「快应用服务已关闭」。恢复：quickapp on")
            else:
                if who:
                    print(f"hap:// 链接由 {who[0]} 接管：网页或 App 里的广告可以用这类链接跳进快应用。")
                print("关闭：python3 tool/run.py -s %s quickapp off（要机主同意，可还原）" % s)
        elif sub == "off":
            todo = [q["pkg"] for q in qs if not q["closed"] and q["method"] == "suspend"]
            why = {}
            for q in qs:
                if q["method"] == "setting":
                    try:
                        print(set_quickapp_service(s))
                    except (RuntimeError, OSError, ValueError) as e:
                        why[q["pkg"]] = str(e)
            for p in todo:
                why[p] = sh_all(s, f"pm suspend --user 0 {p}")
                if suspended(s, p):
                    sh(s, f"am force-stop --user 0 {p}")
            done = [p for p in todo if suspended(s, p)]
            record(s, done)
            bad = []
            for q in quickapps(s):
                ok = q["closed"]
                reason = "" if ok else "（" + ((why.get(q["pkg"]) or "").splitlines() or ["系统没给原因"])[-1][:160] + "）"
                print(f"  {q['name']:<10} {q['pkg']:<34} {'已关闭' if ok else '关闭失败' + reason}")
                if not ok:
                    bad.append(q)
            if not bad:
                print("快应用组件已关闭。请按常用入口核对效果；恢复：quickapp on")
            else:
                # Issue #7：vivo 的快应用挂起被系统拒绝。如实报失败，不说「已关闭」
                print(f"有 {len(bad)} 个快应用组件关闭失败。可以在手机上检查快应用服务开关，或仅关掉它的通知："
                      "设置 → 通知 → 找到「" + "」「".join(q["name"] for q in bad) + "」→ 关掉「允许通知」。")
                sys.exit(1)
        elif sub == "on":
            failures = 0
            for q in qs:
                if q["method"] == "setting":
                    try:
                        print(set_quickapp_service(s, restore=True))
                    except (RuntimeError, OSError, ValueError) as e:
                        print(f"  ✗ {e}"); failures += 1
                if q["suspended"]:
                    sh(s, f"pm unsuspend --user 0 {q['pkg']}")
                    failed = suspended(s, q['pkg'])
                    failures += failed
                    print(f"  {q['name']}: {'还原挂起失败' if failed else '已解除挂起'}")
            if failures:
                sys.exit(1)
        else:
            sys.exit("quickapp 后面跟 check / off / on")

    elif cmd in ("notif-off", "notif-on"):
        # 整包关通知：走运行时权限 POST_NOTIFICATIONS，不需要 root，pm grant 能原样还原。
        # 为什么需要它：vivo / iQOO 的通知渠道页只有应用级总开关（点它 = 整个 App 的通知全关），
        # 这些机器上「只压掉营销推送」只能整包处理，做不了逐渠道关。
        pk, f = rest, ""
        if not pk and cmd == "notif-on":
            f = os.path.join(latest_backup(s), "notif-off.txt")
            if os.path.exists(f):
                with open(f, encoding="utf-8") as fh:
                    pk = sorted({l.strip() for l in fh if l.strip()})
        if not pk:
            sys.exit("要给包名，比如：notif-off com.bbk.appstore com.vivo.browser")
        perm = "android.permission.POST_NOTIFICATIONS"
        failed = []
        for p in pk:
            # pm 的失败原因走 stderr，必须用 sh_all 才看得到
            out = sh_all(s, f"pm {'revoke' if cmd == 'notif-off' else 'grant'} {p} {perm}")
            bad = next((l.strip() for l in out.splitlines()
                        if "Exception" in l or "Error" in l or "Unknown" in l or "Failure" in l), "")
            if bad:
                print(f"  {p} 失败：{bad}")
                failed.append(p)
        st = app_notif_states(s, pk)
        for p in pk:
            v = st[p]
            print(f"  {p}: {'关' if v == 'NONE' else ('开' if v else '读不到状态')}")
        if cmd == "notif-off":
            off = [p for p in pk if st[p] == "NONE"]
            if off:
                record(s, off, "notif-off.txt")
        elif f and not failed:
            # 全部还原成功就清掉记录，和 quickapp 还原后删 quickapp-setting.json 一致；
            # 留着的话下次 notif-on 不带包名会把早已恢复的包再 grant 一遍。
            os.remove(f)
            print(f"  已全部还原，清掉 {os.path.basename(f)}")
        return

    elif cmd == "finish":
        f = os.path.join(latest_backup(s), "stay_on.txt")
        v = open(f, encoding="utf-8").read().strip() if os.path.exists(f) else "0"
        sh(s, f"settings put global stay_on_while_plugged_in {v or 0}")
        sh(s, "input keyevent HOME")
        print(f"插电常亮已改回 {v or 0}")
        on = sh(s, "settings get global development_settings_enabled") == "1"
        if on:
            msg = DEV_REMINDER.format(s=s)
            if os.environ.get("AAC_GUI"):
                msg = msg.replace(f"2) 电脑上：python3 tool/run.py -s {s} dev-off --yes", "2) 电脑上：点客户端完成页的「帮我关闭」")
            print(msg)

    elif cmd == "status-json":
        import json
        i = info(s); r, ref = recipe_for(i["model"], i["brand"]); steps, rb, ok = [], "", True
        if r:
            meta = recipe_meta(r)
            steps, rb = meta["steps"], meta["build"]
            ok = (not ref) and build_ok(i, rb)
        ads = [{"pkg": p, "suspended": suspended(s, p)} for p in AD_PKGS.get(i["brand"], []) if installed(s, p)]
        print(json.dumps({
            "info": i, "locked": locked(s),
            "recipe": os.path.relpath(r, ROOT) if r else None, "recipe_ref": ref, "recipe_build": rb, "recipe_ok": ok, "steps": steps,
            "ads": ads, "quickapps": quickapps(s),
            "stay_on": sh(s, "settings get global stay_on_while_plugged_in"),
            "dev": sh(s, "settings get global development_settings_enabled") == "1",
            "backup": os.path.relpath(latest_backup(s), BACKUPS) if glob.glob(os.path.join(BACKUPS, f"{i['model']}-*")) else None,
            "fold_open": fold_open(s),
        }, ensure_ascii=False))

    elif cmd == "dev-off":
        if "--yes" not in rest:
            sys.exit("这一步会关闭开发者模式和 USB 调试，电脑随后与手机断开。确认后加 --yes 再执行")
        print("正在关闭开发者模式……执行后电脑会和手机断开，这是正常的。")
        sh(s, "settings put global adb_wifi_enabled 0; settings put global development_settings_enabled 0; "
              "settings put global adb_enabled 0")
        print("已发出关闭指令。请在手机上打开 设置 → 搜索「开发者选项」，确认总开关是关着的。")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
