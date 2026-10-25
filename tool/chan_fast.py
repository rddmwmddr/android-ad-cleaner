#!/usr/bin/env python3
"""营销通知渠道（通用版，走 fast 引擎）。
  chan_fast.py -s SERIAL scan             只读：列出开着的、名字像营销的渠道（候选，人工挑）
  chan_fast.py -s SERIAL verify 清单.tsv   只读：清单里还开着几个
  chan_fast.py -s SERIAL off 清单.tsv      逐个打开渠道页关掉
  chan_fast.py -s SERIAL on  清单.tsv      还原
清单.tsv：包名<TAB>渠道id<TAB>说明，一行一个；# 开头是注释。

注意 vivo / iQOO：渠道设置页由 com.vivo.systemuiplugin 渲染，页面上那个「允许通知」
是**应用级**总开关（关它=整个 App 的通知全关），没有真正的渠道级开关，所以这里会直接跳过。
这类机型请按「应用级」关通知（应用信息 → 通知），别按渠道关。
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
    for line in open(path, encoding="utf-8"):
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


def allow_switch(p):
    """渠道页「允许通知」那一行的开关位置与当前状态：(x, y, on) / None。

    不能直接用 p.switches()[0]：
      · vivo 的渠道页由 com.vivo.systemuiplugin 渲染，同一行上有「整行 Switch（content-desc=允许通知）」
        和「开关本体」两个 checkable 节点，标题还会串到相邻行 —— sw[0] 可能是「智能静默」，点了等于
        改了别的设置，而且不报错。
      · 所以按标题行对齐：找 text/content-desc 为「允许通知」且最靠上的那一行，取该行最右的开关。
    """
    root = p.tree()
    p.switches(root)                      # 让引擎先标出自绘开关
    titles, knobs = [], []
    for n in root.iter("node"):
        cls = n.get("class") or ""
        if "Radio" in cls:
            continue
        l, t, r, b = bounds(n)
        if r - l <= 0 or b - t <= 0:
            continue
        s = (n.get("text") or n.get("content-desc") or "").strip()
        cy = (t + b) // 2
        if s in ("允许通知", "通知", "Allow notifications"):
            titles.append((cy, l))
        if n.get("checkable") == "true":
            knobs.append(((l + r) // 2, cy, n.get("checked") == "true"))
    if not titles or not knobs:
        return None
    ty = min(titles)[0]                   # 最上面那个才是渠道总开关
    row = [k for k in knobs if abs(k[1] - ty) <= 60]
    if not row:
        return None
    return max(row, key=lambda k: k[0])   # 同行取最右


def toggle(p, pk, cid, want_on, name=""):
    # -f NEW_TASK|CLEAR_TASK：不加的话荣耀/OPPO 会复用上一个渠道页
    p.d.shell("am start -f 0x10008000 -a android.settings.CHANNEL_NOTIFICATION_SETTINGS"
              f" --es android.provider.extra.APP_PACKAGE {shlex.quote(pk)}"
              f" --es android.provider.extra.CHANNEL_ID {shlex.quote(cid)}")
    sw, foc = None, ""
    for _ in range(12):
        foc = p.focus()
        if "NotificationSettings" in foc:            # 确认真进了渠道页，不是停在上一页
            sw = allow_switch(p)
            if sw:
                break
        time.sleep(0.25)
    if not sw:
        return "没进到渠道页或找不到「允许通知」开关，跳过"
    # vivo 的渠道页是自家 systemuiplugin 画的，页面顶部的「允许通知」其实是**应用级**总开关
    # （关掉后 dumpsys 里 AppSettings importance 变 NONE，而该渠道 mImportance 一动不动），
    # 在这里做「渠道级」操作等于把这个 App 的通知全部关掉 —— 直接跳过，不冒这个险。
    if "com.vivo.systemuiplugin" in foc:
        return ("vivo 的渠道页只有应用级总开关（关它=整个 App 的通知全关），"
                "不是只关这个渠道；已跳过，要关就整个 App 关：应用信息 → 通知")
    for attempt in range(3):                # 页面动画没完时点击会被吞：点完读回来，没变就再点
        if sw[2] == want_on:
            return "already" if attempt == 0 else None
        time.sleep(0.25 + 0.3 * attempt)
        p.click(sw[0], sw[1]); time.sleep(0.5); p.confirm()
        sw = allow_switch(p) or sw
    return "点了 3 次没变"



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
        t0 = time.time(); n = 0; fail = 0
        for pk, cid, label in items:
            st = state(d, app_off, pk, cid)
            if st in ("--", "del", "app"):
                continue
            err = toggle(p, pk, cid, want, d[(pk, cid)][0])
            n += 1
            if err == "already":
                print(f"  · 本来就是{'开' if want else '关'}  {label}")
            elif err:
                fail += 1
                print(f"  ✗ {err}  {label}")
            else:
                print(f"  {'开' if want else '关'}  {label}")
        p.d.shell("input keyevent HOME")   # 别走 u2 的 press：连接断过一次
        print(f"处理 {n} 个（失败 {fail}），{time.time()-t0:.0f} 秒")
    d, app_off = parse(p)
    bad = 0
    for pk, cid, label in items:
        st = state(d, app_off, pk, cid)
        if st == "ON": bad += 1
        if cmd == "verify":
            print(f"{st:4} {label}")
    print(f"营销渠道仍开着: {bad} 个")
    if bad and cmd == "verify":
        print("（dumpsys 与手机通知设置页可能不一致：vivo/部分机型把开关存在自家通知服务里，"
              "dumpsys notification 不跟着变——以手机页面为准）")


if __name__ == "__main__":
    main()
