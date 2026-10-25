#!/usr/bin/env python3
"""手机去广告 · 总入口。所有命令都要带 -s <序列号>（adb devices 第一列）。

  python3 tool/run.py devices                      列出连着的手机、型号、系统版本、有没有现成机型脚本
  python3 tool/run.py -s 序列号 check              只读：锁屏、机型脚本匹配、广告包挂起状态
  python3 tool/run.py -s 序列号 backup             改动前快照，存到 backups/<型号>-<时间>/
  python3 tool/run.py -s 序列号 recipe [段名 …]     跑本机型机型脚本（不带段名=全跑）
  python3 tool/run.py -s 序列号 chan-scan          只读：列出开着的营销通知渠道 → backups/.../channels.tsv
  python3 tool/run.py -s 序列号 chan-off 清单.tsv   关掉清单里的渠道
  python3 tool/run.py -s 序列号 chan-on  清单.tsv   还原
  python3 tool/run.py -s 序列号 notif-off 包名 …    整包关通知（走 POST_NOTIFICATIONS 权限，不用 root）
  python3 tool/run.py -s 序列号 notif-on  [包名 …]  整包恢复通知（不给包名=恢复 notif-off.txt 里的全部）
  python3 tool/run.py -s 序列号 suspend 包名 …       挂起广告包（先征得机主同意），记录到 backups/.../suspended.txt
  python3 tool/run.py -s 序列号 unsuspend [包名 …]   解除挂起（不给包名=解除记录里的全部）
  python3 tool/run.py -s 序列号 quickapp          只读：检测快应用组件（装没装、挂没挂、在不在跑、用没用过）
  python3 tool/run.py -s 序列号 quickapp off      关闭快应用（vivo/iQOO 改总开关 switch_quick_app_service，
                                                  其他品牌挂起组件；先征得机主同意）
  python3 tool/run.py -s 序列号 quickapp on       恢复快应用
  python3 tool/run.py -s 序列号 finish             收尾：插电常亮改回备份时的值，提醒关闭开发者模式
  python3 tool/run.py -s 序列号 dev-off --yes      从电脑上关闭开发者模式和 USB 调试（执行后电脑与手机断开）
  python3 tool/run.py -s 序列号 status-json        只读：一次输出全部状态（JSON，给图形界面用）
"""
import datetime, glob, os, re, shutil, subprocess, sys
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
# vivo / iQOO 例外：suspend / disable-user / uninstall --user 0 一律要求 root，
# 真正能关掉快应用的是 secure 里的 switch_quick_app_service（见 quickapp_switch）。
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


def prop(serial, k):
    return sh(serial, f"getprop {k}")


def info(serial):
    return {
        "brand": prop(serial, "ro.product.brand"),
        "model": prop(serial, "ro.product.model"),
        "name": prop(serial, "ro.vendor.oplus.market.name") or prop(serial, "ro.product.marketname") or prop(serial, "ro.product.vendor.marketname"),
        "build": prop(serial, "ro.build.display.id"),
        "android": prop(serial, "ro.build.version.release"),
    }


def recipe_for(model):
    hits = glob.glob(os.path.join(ROOT, "recipes", f"*-{model}", "recipe.py"))
    return hits[0] if hits else None


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


def suspended(serial, pkg):
    out = sh(serial, f"dumpsys package {pkg} | grep -m1 -o 'suspended=[a-z]*'")
    return out.endswith("true")


def installed(serial, pkg):
    return "package:" in sh(serial, f"pm path {pkg}")


QUICKAPP_SWITCH = "switch_quick_app_service"      # vivo / iQOO：快应用总开关（secure），0=关 1=开
SUSPEND_ERR = ("挂起失败：这台机器的 pm suspend 需要 root（SecurityException: Cannot suspend … no root permission）。"
               "vivo / iQOO 用 quickapp off 走总开关，别用 suspend")


def quickapp_switch(serial):
    """vivo / iQOO 的快应用总开关值；读不到（其他品牌）返回 None。"""
    v = sh(serial, f"settings get secure {QUICKAPP_SWITCH}")
    return v if v in ("0", "1") else None


def app_notif_states(serial, pkgs):
    """整包通知状态：importance=NONE 就是关。一次 dumpsys 覆盖多个包（它将近 1MB，别循环读）。"""
    out = sh(serial, "dumpsys notification --noredact")
    res = {}
    for p in pkgs:
        m = re.search(rf"AppSettings: {re.escape(p)} \(\d+\) importance=(\w+)", out)
        res[p] = m.group(1) if m else ""
    return res


def quickapps(serial):
    """装着的快应用组件，带状态。"""
    ev = sh(serial, "dumpsys usagestats")
    out = []
    for pkg, name, brand, tested in QUICKAPP:
        if not installed(serial, pkg):
            continue
        fg = len(re.findall(rf"type=ACTIVITY_RESUMED package={re.escape(pkg)}\b", ev))
        out.append({
            "pkg": pkg, "name": name, "brand": brand, "tested": tested,
            "suspended": suspended(serial, pkg),
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
    return subprocess.call([sys.executable, os.path.join(TOOL, script), *args])


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
            i = info(ser); r = recipe_for(i["model"])
            print(f"{ser}\t{i['name'] or i['brand']+' '+i['model']}\t{i['model']}\t{i['build']}\t机型脚本：{os.path.relpath(r, ROOT) if r else '无（只能跑通用部分）'}")
        return
    if a[0] != "-s" or len(a) < 3:
        sys.exit("命令格式：run.py -s <序列号> <命令>。先跑 run.py devices 看序列号")
    s, cmd, rest = a[1], a[2], a[3:]

    if cmd == "check":
        i = info(s); r = recipe_for(i["model"])
        print(f"机型：{i['name'] if i['name'].upper().startswith(i['brand'].upper()) else i['brand']+' '+i['name']}（{i['model']}），系统 {i['build']}，Android {i['android']}")
        print(f"锁屏：{'是（请机主解锁）' if locked(s) else '否'}")
        if r:
            src = open(r, encoding="utf-8").read()
            m = re.search(r'^BUILD\s*=\s*"([^"]*)"', src, re.M)
            ok = (not m) or i["build"].startswith(m.group(1))
            print(f"机型脚本：{os.path.relpath(r, ROOT)}；录制版本 {m.group(1) if m else '未标'}，{'版本一致' if ok else '版本不同，部分步骤可能找不到入口'}")
        else:
            print("机型脚本：没有。可跑：通知渠道 chan-scan/chan-off、广告包挂起；其余照 docs/清单 手动做，或用 tool/explore.py 探路")
        for p in AD_PKGS.get(i["brand"], []):
            exists = "package:" in sh(s, f"pm path {p}")
            print(f"  广告包 {p}：{'未安装' if not exists else ('已挂起' if suspended(s, p) else '未挂起')}")
        for q in quickapps(s):
            print(f"  快应用 {q['pkg']}（{q['name']}）：{'已挂起' if q['suspended'] else '未挂起'}")
        swc = quickapp_switch(s)
        if swc is not None:
            print(f"  快应用总开关 {QUICKAPP_SWITCH}：{swc}（{'已关闭' if swc == '0' else '开着'}）")
        print(f"插电常亮：{sh(s, 'settings get global stay_on_while_plugged_in')}")

    elif cmd == "backup":
        d = latest_backup(s, create=True)
        open(os.path.join(d, "info.txt"), "w", encoding="utf-8").write("\n".join(f"{k}={v}" for k, v in info(s).items()))
        # 一律带 --user 0：不带的话 pm 会遍历所有用户，遇到分身/隐私空间（vivo 是 666/999）
        # 没权限就返回 "Error: Shell does not have permission to access user 666"，
        # 这行会写进备份文件，任何按行解析备份的脚本都会读脏。
        for name, c in [("sys.txt", "pm list packages -s --user 0"), ("user.txt", "pm list packages -3 --user 0"),
                        ("disabled.txt", "pm list packages -d --user 0"), ("notif.txt", "dumpsys notification --noredact")]:
            open(os.path.join(d, name), "w", encoding="utf-8").write(sh(s, c))
        st = "\n".join(f"## {n}\n" + sh(s, f"settings list {n}") for n in ("system", "secure", "global"))
        open(os.path.join(d, "settings-before.txt"), "w", encoding="utf-8").write(st)
        open(os.path.join(d, "stay_on.txt"), "w", encoding="utf-8").write(sh(s, "settings get global stay_on_while_plugged_in"))
        print(f"快照已存：{d.replace(os.path.expanduser('~'), '~') if os.environ.get('AAC_BACKUPS') else os.path.relpath(d, ROOT)}")

    elif cmd == "recipe":
        r = recipe_for(info(s)["model"])
        if not r:
            sys.exit("这个型号没有机型脚本。见 docs/04-给新机型写脚本.md")
        if locked(s):
            sys.exit("手机锁屏了，请机主解锁后再跑")
        sh(s, "settings put global stay_on_while_plugged_in 7")
        sys.exit(py("fast.py", "-s", s, "run", r, *rest))

    elif cmd == "chan-scan":
        d = latest_backup(s)
        out = subprocess.run([sys.executable, os.path.join(TOOL, "chan_fast.py"), "-s", s, "scan"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        f = os.path.join(d, "channels.tsv")
        open(f, "w", encoding="utf-8").write(
            "# 包名\t渠道id\t渠道名。人工核对：删掉服务类（热点共享、红包、防盗、直播提醒等）后再 chan-off\n" + out)
        print(out); print(f"候选清单：{os.path.relpath(f, ROOT)}（共 {out.count(chr(10))} 条）")

    elif cmd in ("chan-off", "chan-on"):
        if not rest:
            sys.exit("要给清单文件，比如 backups/<型号>-<时间>/channels.tsv")
        sys.exit(py("chan_fast.py", "-s", s, cmd.split("-")[1], rest[0]))

    elif cmd == "suspend":
        bad = [p for p in rest if p in NEVER]
        if bad:
            sys.exit(f"这些包挂了会坏功能，不挂：{bad}")
        d = latest_backup(s)
        ok = 0
        with open(os.path.join(d, "suspended.txt"), "a", encoding="utf-8") as f:
            for p in rest:
                out = sh(s, f"pm suspend --user 0 {p}")
                if suspended(s, p):
                    f.write(p + "\n")
                    ok += 1
                    print(f"  {p} 已挂起")
                else:
                    last = next((l.strip() for l in out.splitlines() if "Exception" in l or "Error" in l), "")
                    print(f"  {p} 挂起失败" + (f"：{last}" if last else ""))
        if not ok:
            sys.exit(SUSPEND_ERR)

    elif cmd == "unsuspend":
        pk = rest
        if not pk:
            f = os.path.join(latest_backup(s), "suspended.txt")
            pk = sorted(set(open(f, encoding="utf-8").read().split())) if os.path.exists(f) else []
        for p in pk:
            sh(s, f"pm unsuspend --user 0 {p}")
            print(p, "已挂起" if suspended(s, p) else "已恢复")

    elif cmd == "quickapp":
        sub = rest[0] if rest else "check"
        qs = quickapps(s)
        sw = quickapp_switch(s)
        # vivo / iQOO：pm suspend、pm disable-user、pm uninstall --user 0 全都要 root，
        # 真正生效的是这个总开关；关掉之后 hap:// 会停在「快应用服务已关闭」页，进不去应用。
        if sw is not None and sub in ("off", "on"):
            f = os.path.join(latest_backup(s), "quickapp.txt")
            if sub == "off":
                if not os.path.exists(f):
                    open(f, "w", encoding="utf-8").write(sw + "\n")     # 记原值，供 on 还原
                sh(s, f"settings put secure {QUICKAPP_SWITCH} 0")
                for q in qs:
                    sh(s, f"am force-stop {q['pkg']}")
                now = quickapp_switch(s)
                print(f"  快应用总开关 {QUICKAPP_SWITCH}：{sw} → {now}")
                if now != "0":
                    sys.exit("关闭失败：开关没写成 0。见 docs/清单/README.md 的排查表")
                print("快应用已关闭：hap:// 链接和快应用入口都会停在「快应用服务已关闭」页。恢复：quickapp on")
                return
            old = open(f, encoding="utf-8").read().strip() if os.path.exists(f) else "1"
            sh(s, f"settings put secure {QUICKAPP_SWITCH} {old or 1}")
            print(f"  快应用总开关已恢复为 {quickapp_switch(s)}")
            return
        if not qs:
            print("没有检测到快应用组件。"); return
        if sub == "check":
            print(f"检测到 {len(qs)} 个快应用组件：")
            for q in qs:
                print(f"  {q['name']:<10} {q['pkg']:<34} {'已挂起' if q['suspended'] else '未挂起'}  "
                      f"{'后台在跑' if q['running'] else '没在跑'}  "
                      f"{'近期打开过 %d 次' % q['used'] if q['used'] else '近期没打开过'}"
                      f"{'' if q['tested'] else '  （这个包的挂起效果还没实测）'}")
            if sw is not None:
                print(f"  快应用总开关 {QUICKAPP_SWITCH}={sw}（vivo/iQOO 真正起作用的是它，挂包在这类机型上要 root）")
            h = sh(s, "pm query-activities --brief -a android.intent.action.VIEW -d hap://app/x")
            who = re.findall(r"^\s*(\S+/\S+)$", h, re.M)
            if sw == "0" or (sw is None and all(q["suspended"] for q in qs)):
                print("快应用已关闭：hap:// 链接会停在「快应用服务已关闭」页，不会跳进快应用。恢复：quickapp on")
            else:
                if who:
                    print(f"hap:// 链接由 {who[0]} 接管：网页或 App 里的广告可以用这类链接跳进快应用。")
                print("关闭：python3 tool/run.py -s %s quickapp off（要机主同意，可还原）" % s)
        elif sub == "off":
            todo = [q["pkg"] for q in qs if not q["suspended"]]
            for p in todo:
                sh(s, f"am force-stop {p}")
                sh(s, f"pm suspend --user 0 {p}")
            done = [p for p in todo if suspended(s, p)]
            record(s, done)
            for q in qs:
                print(f"  {q['name']:<10} {q['pkg']:<34} {'已挂起' if suspended(s, q['pkg']) else '挂起失败'}")
            if not done:
                sys.exit(SUSPEND_ERR)
            print("快应用已关闭。广告里的 hap:// 链接会弹「应用无法使用」，不会跳进快应用。恢复：quickapp on")
        elif sub == "on":
            for q in qs:
                sh(s, f"pm unsuspend --user 0 {q['pkg']}")
                print(f"  {q['name']:<10} {q['pkg']:<34} {'已挂起' if suspended(s, q['pkg']) else '已恢复'}")
        else:
            sys.exit("quickapp 后面跟 check / off / on")

    elif cmd in ("notif-off", "notif-on"):
        # 整包关通知，走运行时权限 POST_NOTIFICATIONS：不需要 root，pm grant 可原样还原。
        # vivo / iQOO 没有真正的渠道级开关（它家渠道页那个「允许通知」是全 App 的总开关），
        # 要压掉某个 App 的营销推送就用这个。
        pk = rest
        if not pk:
            f = os.path.join(latest_backup(s), "notif-off.txt")
            pk = sorted(set(open(f, encoding="utf-8").read().split())) if (cmd == "notif-on" and os.path.exists(f)) else []
        if not pk:
            sys.exit("要给包名，比如：notif-off com.bbk.appstore com.vivo.browser")
        for p in pk:
            out = sh(s, f"pm {'revoke' if cmd == 'notif-off' else 'grant'} {p} android.permission.POST_NOTIFICATIONS")
            bad = next((l.strip() for l in out.splitlines() if "Exception" in l or "Error" in l or "Unknown" in l), "")
            if bad:
                print(f"  {p} 失败：{bad}")
        st = app_notif_states(s, pk)
        for p in pk:
            v = st[p]
            print(f"  {p}: {'关' if v == 'NONE' else ('开' if v else '读不到状态')}")
        if cmd == "notif-off":
            off = [p for p in pk if st[p] == "NONE"]
            f = os.path.join(latest_backup(s), "notif-off.txt")
            if off:
                with open(f, "a", encoding="utf-8") as fh:
                    for p in off:
                        fh.write(p + "\n")
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
        i = info(s); r = recipe_for(i["model"]); steps, rb, ok = [], "", True
        if r:
            src = open(r, encoding="utf-8").read()
            steps = re.findall(r'^@step\("([^"]+)"\)', src, re.M)
            m = re.search(r'^BUILD\s*=\s*"([^"]*)"', src, re.M)
            rb = m.group(1) if m else ""
            ok = i["build"].startswith(rb)
        ads = [{"pkg": p, "suspended": suspended(s, p)} for p in AD_PKGS.get(i["brand"], []) if installed(s, p)]
        print(json.dumps({
            "info": i, "locked": locked(s),
            "recipe": os.path.relpath(r, ROOT) if r else None, "recipe_build": rb, "recipe_ok": ok, "steps": steps,
            "ads": ads, "quickapps": quickapps(s), "quickapp_switch": quickapp_switch(s),
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
