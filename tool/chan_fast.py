#!/usr/bin/env python3
"""营销通知渠道（通用版，走 fast 引擎）。
  chan_fast.py -s SERIAL scan             只读：列出开着的、名字像营销的渠道（候选，人工挑）
  chan_fast.py -s SERIAL verify 清单.tsv   只读：清单里还开着几个
  chan_fast.py -s SERIAL off 清单.tsv      逐个打开渠道页关掉
  chan_fast.py -s SERIAL on  清单.tsv      还原
清单.tsv：包名<TAB>渠道id<TAB>说明，一行一个；# 开头是注释。
"""
import re, shlex, sys, time, os
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fast import Phone, bounds

KW = re.compile(r"营销|活动|推荐|推广|热点|热门|资讯|新闻|福利|优惠|特惠|精选|精彩|运营|促销|红包|直播|种草|内容|头条|猜你|好物|权益|会员|签到|广告|recommend|promo|market|deal|news|topstory|upsell|offer", re.I)
SKIP = re.compile(r"下载|更新|安装|上传|订单|物流|快递|交易|支付|账号|安全|验证|通话|来电|消息|聊天|私信|评论|互动|提醒|闹钟|日程|天气预警|系统|前台|后台|服务运行|播放|媒体"
                  r"|热点和网络共享|智能热点|红包助手|盗窃|驾驶状态|权限建议|运营商", re.I)   # 后一行：服务类，不是营销


def parse(p):
    txt = p.d.shell("dumpsys notification --noredact", timeout=60).output
    if "PackagePreferences:" not in txt:
        raise RuntimeError("读不到通知渠道状态，停止操作；请检查 USB 调试连接和系统权限")
    txt = txt[txt.find("PackagePreferences:"):]
    cur, app_off, d = None, {}, {}
    for line in txt.splitlines():
        m = re.match(r"\s*AppSettings: (\S+)", line)
        if m:
            cur = m.group(1); app_off[cur] = "importance=NONE" in line; continue
        m = re.search(r"NotificationChannel\{mId='(.*?)', mName=(.*?), mDescription=.*?mImportance=(-?\d+).*?mDeleted=(\w+)", line)
        if m and cur and (cur, m.group(1)) not in d:
            d[(cur, m.group(1))] = (m.group(2), int(m.group(3)), m.group(4) == "true")
    return d, app_off


def load(path):
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\r\n")
            if line.strip() and not line.lstrip().startswith("#"):
                pk, cid, label = (line.split("\t") + ["", ""])[:3]
                if not re.fullmatch(r"[\w.]+", pk) or not cid:
                    raise ValueError(f"清单第 {lineno} 行缺少有效包名或渠道 ID")
                out.append((pk, cid, label or cid))
    return out


def state(d, app_off, pk, cid):
    if (pk, cid) not in d:
        return "--"
    name, imp, deleted = d[(pk, cid)]
    if imp == 0: return "off"
    if deleted: return "del"
    if app_off.get(pk): return "app"
    return "ON"


ALLOW = {"允许通知", "显示通知", "Allow notifications", "Show notifications"}


def notification_focus(p):
    focus = p.focus()
    if "com.vivo.systemuiplugin" in focus:
        raise RuntimeError("此 vivo 通知页的开关会影响整个 App，已跳过以保留订单、聊天等通知")
    package, _, activity = focus.partition("/")
    return focus if "settings" in package.lower() and ("notification" in activity.lower() or "SubSettings" in activity) else ""


def channel_switch(p, name):
    """同时确认渠道标题、设置页身份和明确的通知开关；绝不取页面第一个开关。"""
    focus = notification_focus(p)
    if not focus or "AppNotification" in focus or not name:
        return None
    root = p.tree()
    if not any(t == name and b[1] < p.H * 0.22 for t, b, _ in p.texts(root)):
        return None
    switches = [s for s in p.switches(root) if s[0] in ALLOW]
    return switches[0] if len(switches) == 1 else None


def wait_page(p, name, rounds=12):
    previous, stable = None, 0
    for _ in range(rounds):
        if p.locked():
            raise RuntimeError("手机锁屏了，请机主解锁后再跑")
        sw = channel_switch(p, name)
        stable = stable + 1 if sw and sw == previous else (1 if sw else 0)
        previous = sw
        if stable >= 3:
            return sw
        time.sleep(0.2)
    return None


def via_app_page(p, pk, name):
    """HyperOS 拦截渠道深链时，从应用通知页进入已确认的渠道行。"""
    p.d.shell("am start -f 0x10008000 -a android.settings.APP_NOTIFICATION_SETTINGS"
              f" --es android.provider.extra.APP_PACKAGE {shlex.quote(pk)}")
    for _ in range(15):
        if notification_focus(p):
            break
        time.sleep(0.2)
    else:
        return None
    for _ in range(9):
        if p.locked() or not notification_focus(p):
            return None
        root = p.tree()
        parents = {c: n for n in root.iter() for c in n}
        for text, b, n in p.texts(root):
            if text != name or b[1] < p.H * 0.22:
                continue
            row = n
            while row is not None and row.get("clickable") != "true" and row.get("checkable") != "true":
                row = parents.get(row)
            # 内联开关不当作导航行点，避免在应用总页拨到其他开关。
            if row is None or any(x.get("checkable") == "true" for x in row.iter()):
                return None
            before = p.sig()
            l, t, r, btm = bounds(n)
            p.click((l + r) // 2, (t + btm) // 2)
            if not p.settle(before):
                return None
            return wait_page(p, name)
        if not p.scroll_more():
            break
    return None


def toggle(p, pk, cid, want_on, name=""):
    try:
        if p.locked():
            return "手机锁屏了，请机主解锁后再跑"
        before, apps_before = parse(p)
        if state(before, apps_before, pk, cid) in ("--", "del", "app"):
            return "渠道不存在、已删除或应用通知已关闭，未操作"
        # NEW_TASK|CLEAR_TASK 避免复用旧渠道；仍需核对真实页面。
        p.d.shell("am start -f 0x10008000 -a android.settings.CHANNEL_NOTIFICATION_SETTINGS"
                  f" --es android.provider.extra.APP_PACKAGE {shlex.quote(pk)}"
                  f" --es android.provider.extra.CHANNEL_ID {shlex.quote(cid)}")
        sw = wait_page(p, name)
        if not sw:
            sw = via_app_page(p, pk, name)
        if not sw:
            return f"未确认「{name}」渠道页及通知开关，跳过"
        desired = "ON" if want_on else "off"
        for attempt in range(3):
            # 每次重取页面，开关消失时不能复用旧坐标。
            if p.locked():
                return "手机锁屏了，停止操作"
            sw = wait_page(p, name, rounds=6)
            if not sw:
                return "渠道页或开关已变化，停止操作"
            if sw[1] != want_on:
                p.click(*sw[2]); time.sleep(0.4); p.confirm()
            current, apps = parse(p)
            if apps.get(pk, False) != apps_before.get(pk, False):
                raise RuntimeError("应用通知总开关发生变化，停止；请先在手机上核对并还原该 App 的通知")
            if state(current, apps, pk, cid) == desired:
                return None
            if sw[1] == want_on:
                return "界面状态与渠道实际状态不一致，未继续点击"
            time.sleep(0.25 + 0.3 * attempt)
        return "点击后渠道状态未改变"
    except RuntimeError as e:
        # 总开关异常必须终止整批；其他页面不兼容只跳过本渠道。
        if "总开关发生变化" in str(e):
            raise
        return str(e)



def main():
    a = sys.argv[1:]
    p = Phone(a[1], log=False); cmd = a[2]
    if cmd == "scan":
        d, app_off = parse(p)
        for (pk, cid), (name, imp, deleted) in sorted(d.items()):
            if imp != 0 and not deleted and not app_off.get(pk) and KW.search(name + " " + cid) and not SKIP.search(name):
                print(f"{pk}\t{cid}\t{name}")
        return
    items = load(a[3])
    if cmd in ("off", "on"):
        want = cmd == "on"
        d, app_off = parse(p)
        t0 = time.time(); n = 0; failures = 0
        for pk, cid, label in items:
            st = state(d, app_off, pk, cid)
            if st in ("--", "del", "app"):
                print(f"  · 未操作 {label}（渠道不存在、已删除或应用通知已关闭）")
                if want or st == "--":
                    failures += 1
                continue
            if (st == "off") == (not want):
                continue
            err = toggle(p, pk, cid, want, d[(pk, cid)][0])
            n += 1
            failures += bool(err)
            print(f"  {'✗ '+err if err else ('开' if want else '关')}  {label}")
        p.d.shell("input keyevent HOME")   # 别走 u2 的 press：连接断过一次
        print(f"拨了 {n} 个，{time.time()-t0:.0f} 秒")
    d, app_off = parse(p)
    bad = 0
    for pk, cid, label in items:
        st = state(d, app_off, pk, cid)
        if st == "ON": bad += 1
        if cmd == "verify":
            print(f"{st:4} {label}")
    print(f"营销渠道仍开着: {bad} 个")
    if cmd == "on":
        pending = sum(state(d, app_off, pk, cid) != "ON" for pk, cid, _ in items)
        print(f"未恢复的渠道: {pending} 个")
        if pending or failures:
            sys.exit(1)
    if cmd == "off" and (bad or failures):
        sys.exit(1)                  # 让客户端把这一步标成失败（Issue #7：以前失败了也显示成功）


if __name__ == "__main__":
    main()
