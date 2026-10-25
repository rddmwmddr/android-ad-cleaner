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
from fast import Phone

KW = re.compile(r"营销|活动|推荐|推广|热点|热门|资讯|新闻|福利|优惠|特惠|精选|精彩|运营|促销|红包|直播|种草|内容|头条|猜你|好物|权益|会员|签到|广告|recommend|promo|market|deal|news|topstory|upsell|offer", re.I)
SKIP = re.compile(r"下载|更新|安装|上传|订单|物流|快递|交易|支付|账号|安全|验证|通话|来电|消息|聊天|私信|评论|互动|提醒|闹钟|日程|天气预警|系统|前台|后台|服务运行|播放|媒体", re.I)


def parse(p):
    txt = p.d.shell("dumpsys notification --noredact", timeout=60).output
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
    # utf-8-sig：Windows PowerShell 另存的 tsv 带 UTF-8 BOM，否则首行包名会带上 \ufeff 而被静默跳过
    for line in open(path, encoding="utf-8-sig"):
        line = line.rstrip("\n")
        if line.strip() and not line.startswith("#"):
            pk, cid, label = (line.split("\t") + ["", ""])[:3]
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


def toggle(p, pk, cid, want_on, name=""):
    """开/关一个渠道。优先深链直跳（旧 MIUI/荣耀/OPPO 正常）。
    HyperOS 会拦截 CHANNEL_NOTIFICATION_SETTINGS 深链导致跳不过去，
    此时自动回退到「App 通知页 → 点渠道行 → 拨开关」。"""
    err = _toggle_deeplink(p, pk, cid, want_on, name)
    if err is None:
        return None
    err2 = _toggle_app_page(p, pk, name, want_on)
    return None if err2 is None else err2


def _toggle_deeplink(p, pk, cid, want_on, name=""):
    # -f NEW_TASK|CLEAR_TASK：不加的话荣耀/OPPO 会复用上一个渠道页
    p.d.shell("am start -f 0x10008000 -a android.settings.CHANNEL_NOTIFICATION_SETTINGS"
              f" --es android.provider.extra.APP_PACKAGE {shlex.quote(pk)}"
              f" --es android.provider.extra.CHANNEL_ID {shlex.quote(cid)}")
    sw = None
    for _ in range(12):
        tx = [t for t, _, _ in p.texts()]
        if (not name or name in tx):
            sw = p.switches()
            if sw:
                break
        time.sleep(0.2)
    if not sw:
        return f"页面不是「{name}」或没开关"
    for attempt in range(3):                   # 页面动画没完时点击会被吞：点完读回来，没变就再点
        t, c, xy = sw[0]                       # 渠道页第一个开关=允许通知
        if c == want_on:
            return None
        time.sleep(0.25 + 0.3 * attempt)
        p.click(*xy); time.sleep(0.4); p.confirm()
        sw = p.switches() or sw
    return "点了 3 次没变"


def _toggle_app_page(p, pk, name, want_on):
    """HyperOS 回退路径：开 App 通知设置页 → 按名字点渠道行进详情 → 拨「允许通知」开关。"""
    if not name:
        return "无渠道名，无法回退"
    p.d.shell("input keyevent KEYCODE_HOME"); time.sleep(0.6)
    # 0x10008000=NEW_TASK|CLEAR_TASK：不加会恢复上次深潜的详情页而非顶层列表
    p.d.shell("am start -f 0x10008000 -a android.settings.APP_NOTIFICATION_SETTINGS"
              f" --es android.provider.extra.APP_PACKAGE {shlex.quote(pk)}")
    time.sleep(2.2)
    for _scroll in range(8):                   # 渠道行靠页尾，最多翻 8 屏
        el = p.d(text=name)                    # 不加 clickable：文字节点本身不可点，u2 会点到其可点父容器
        if el.exists:
            el.click(); time.sleep(1.6)
            for _try in range(4):              # 详情页第一个 checkable 开关 = 允许通知
                sw = next((n for n in p.tree().iter("node") if n.get("checkable") == "true"), None)
                if sw is None:
                    time.sleep(0.4); continue
                if (sw.get("checked") == "true") == want_on:
                    return None
                m = re.findall(r"\d+", sw.get("bounds"))
                p.click((int(m[0]) + int(m[2])) // 2, (int(m[1]) + int(m[3])) // 2)
                time.sleep(0.7)
                sw2 = next((n for n in p.tree().iter("node") if n.get("checkable") == "true"), None)
                if sw2 is not None and (sw2.get("checked") == "true") == want_on:
                    return None
            return "详情页开关未拨动"
        p.d.swipe_ext("up", 0.6); time.sleep(0.6)
    return f"App 通知页无「{name}」行"



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
        t0 = time.time(); n = 0
        for pk, cid, label in items:
            st = state(d, app_off, pk, cid)
            if st in ("--", "del", "app") or (st == "off") == (not want):
                continue
            err = toggle(p, pk, cid, want, d[(pk, cid)][0])
            n += 1
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


if __name__ == "__main__":
    main()
