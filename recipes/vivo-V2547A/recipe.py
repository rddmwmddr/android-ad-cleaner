# vivo X300 Ultra（V2547A，OriginOS 7，Android 17）机型脚本
# 2026-10-25 在真机逐页实测，8 段整段跑通，重跑 126 秒。
BUILD = "PD2547B_A_17.1.10.2"          # ro.build.display.id 的开头；对不上引擎只提示，不阻断
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
#
# 这台和 docs/清单/vivo-OriginOS.md 里实测的 V2547DA（OriginOS 6）不是同一版系统，入口有几处不同：
#   · 浏览器冷启动停在首页，底部没有「我的」，只能走右上「菜单 → 设置」
#   · 应用商店的「服务管理」「个性化推荐」在「设置 → 关于」里，且必须点行中间（点左侧文字不转发点击）
#   · 天气的设置藏在右上 more_btn 后面（页面里那个「更多」是展开按钮，按文字找会点错）
#   · 关推荐类开关会弹「温馨提示 → 取消 / 确认关闭」，按钮节点 text 是空的，文字挂在 vbutton_title 里（#397）
#   · 开关行是「整行 + 开关」两个 checkable 节点（y 差 7px），整行节点的标题还会串到上一行，
#     所以下面自己扫了一遍树，按行还原标题、排除单选钮，再逐行只点一次
import re
import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []


def step(name):
    def deco(f):
        if (not ONLY or name in ONLY) and p.locked():
            print(f"\n== {name}：手机锁屏了，后面的都不跑"); return f
        if not ONLY or name in ONLY:
            print(f"\n== {name}"); p.miss = 0
            t = time.time()
            try:
                f()
            except Exception as e:
                FAILED_STEPS.append(name)
                print(f"  ✗ 未完成：{e}")
            print(f"  ({time.time()-t:.0f} 秒)")
        return f
    return deco


# ---------- vivo 专用 ----------
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
# 关推荐类开关后的二次确认框。注意顺序：长词优先，避免 "关闭" 抢先命中
CONFIRM = ("确认关闭", "仍要关闭", "仍然关闭", "确定关闭", "继续关闭", "关闭推荐", "确定", "确认", "关闭")


def bounds_of(n):
    m = BOUNDS.match(n.get("bounds") or "")
    return tuple(map(int, m.groups())) if m else (0, 0, 0, 0)


def confirm2():
    """关掉推荐开关后，vivo 会弹「温馨提示 → 取消 / 确认关闭」。
    这个框的按钮 text 是空的（android:id/button1=取消、button2=确认关闭），
    标题挂在下层 TextView（resource-id=...vbutton_title）里。

    PR #239 起 p.confirm() 也会读 Button 下级整段等于确认词的文字，理论上已覆盖这个形状；
    但没在 V2547A 真机上验过，暂留这份（#397）。真要换掉，先用 dialog_open() 断言弹窗真的消失：
    p.confirm() 不要求 clickable="true"，落在不可点击的 Button 上同样返回确认词。"""
    time.sleep(0.35)
    root = p.tree()
    for n in root.iter("node"):
        if n.get("clickable") != "true" or "Button" not in (n.get("class") or ""):
            continue
        labels = [(x.get("text") or "").strip() for x in n.iter("node")]
        hit = next((w for w in CONFIRM if w in labels), None)
        if not hit:
            continue
        l, t, r, b = bounds_of(n)
        if r - l <= 0 or b - t <= 0:
            continue
        p.click((l + r) // 2, (t + b) // 2)
        time.sleep(0.35)
        return hit
    return None


def dialog_open():
    """当前屏是不是挡着一个带「取消」的确认框（用来发现没关掉的弹窗）。"""
    root = p.tree()
    tx = {(n.get("text") or "").strip() for n in root.iter("node")}
    return "取消" in tx and not p.switches(root)


def rows():
    """当前屏的开关行：[(真实标题, 是否开着, (x, y))]，一行一条。

    引擎自带的 p.switches() 有两个坑，在这台机器上都会踩到：
    1) 标题是「往上找父节点里的第一段文字」，遇到分组容器会串成页标题 ——
       负一屏「热点资讯」页 8 行全都叫「热点资讯」、阅图锁屏页的「锁屏底部壁纸功能」会被叫成「阅图锁屏」，
       照着标题关就会关错东西。这里改成按行还原：取同一行、开关左侧、最靠上的那段文字
       （vivo 的列表行都是「标题在上、说明在下」，按纵向最近取会把长说明当标题 ——
       全局搜索·个性化内容 的「广告个性化」就因此永远匹配不上）。
    2) 单选组（热点资讯页的悬浮/经典/卡片形态）也是 checkable+clickable，会被当成开关一起「关掉」。
       单选钮一律排除。
    """
    root = p.tree()
    p.switches(root)                        # 先让引擎把自绘开关标成 SelfDrawnSwitch，再自己扫
    texts = []
    for n in root.iter("node"):
        s = (n.get("text") or n.get("content-desc") or "").strip()
        if not s:
            continue
        l, t, r, b = bounds_of(n)
        if r - l <= 0 or b - t <= 0:
            continue
        texts.append((s, l, t, r, b, (t + b) // 2))

    found = []                              # [左, 右, 中线y, 上, 下, 是否开, 原始文案, 宽]
    for n in root.iter("node"):
        cls = n.get("class") or ""
        if n.get("checkable") != "true" or "Radio" in cls:
            continue
        if not any(k in cls for k in ("Switch", "CheckBox", "ToggleButton", "SelfDrawnSwitch")):
            continue
        l, t, r, b = bounds_of(n)
        if r - l <= 0 or b - t <= 0:
            continue
        raw = (n.get("text") or n.get("content-desc") or "").strip()
        found.append([l, r, (t + b) // 2, t, b, n.get("checked") == "true", raw, r - l])

    # 同一行的「整行节点」和「开关节点」合成一条：点在真开关上、行范围取两者的并集
    merged = []
    for f in sorted(found, key=lambda f: f[2]):
        for m in merged:
            if abs(m[2] - f[2]) <= 40:
                m[3] = min(m[3], f[3])
                m[4] = max(m[4], f[4])
                if f[7] > m[7]:             # 整行节点的文案更完整，留作兜底
                    m[6], m[7] = f[6], f[7]
                if (f[0] + f[1]) > (m[0] + m[1]):
                    m[0], m[1], m[2], m[5] = f[0], f[1], f[2], f[5]
                break
        else:
            merged.append(list(f))

    out = []
    for l, r, cy, top, bot, ck, raw, _w in merged:
        best = None
        for s, tl, tt, tr, tb, tc in texts:
            if tr > l:                      # 只要开关左边的文字
                continue
            if not (top - 25 <= tc <= bot + 25):
                continue
            if best is None or (tt, tl) < (best[0], best[1]):
                best = (tt, tl, s)
        title = best[2] if best else (raw.split(".")[0].strip() if raw else "")
        out.append((title, ck, ((l + r) // 2, cy)))
    return out


def tap_row(w, scrolls=0, wait=1.3):
    """点列表项：先找到文字，再点整行水平中间。
    有的 vivo 页面左侧文字节点不转发点击（应用商店「关于」页的「服务管理」就是这样，
    点文字没反应，点行中间才进得去）。
    进页后立刻找会对着还没画完的页面报「没找到」，先等这一页站稳（#331）。"""
    p.await_page()
    xy = p.find(w, exact=True)
    for _ in range(scrolls):
        if xy:
            break
        if not p.scroll_more():
            break
        xy = p.find(w, exact=True)
    if not xy:
        return False
    b = p.sig()
    p.click(p.W // 2, xy[1])
    p.settle(b, wait + 0.4)
    time.sleep(wait)
    return True


def off(only=None, keep=(), page="", max_screens=30):
    """只关匹配的开关，每行点一次。引擎自带的 p.off 在 vivo 上会把同一行点两遍。"""
    done = 0
    tried = {}                                  # 标题 -> 点过几次，防止在同一行上反复空点
    for _ in range(2 if p.miss else 8):          # 页面刚打开还没画完
        if p.switches():
            break
        time.sleep(0.25)
    for _ in range(max_screens):
        todo = []
        for t, c, xy in rows():
            if not c or not t:
                continue
            if any(k in t for k in keep):
                continue
            if only is not None and not any(k in t for k in only):
                continue
            if tried.get(t, 0) >= 2:            # 点两次还是开着：多半被弹窗挡着，交给下面的检查
                continue
            if not (0 < xy[0] < p.W and p.H * 0.08 < xy[1] < p.H * 0.985):
                print(f"  ! {t} 坐标异常 {xy}，跳过不乱点")
                continue
            todo.append((t, xy))
        for t, xy in todo:
            p.click(*xy)
            time.sleep(0.3)
            hit = confirm2()                    # 这个弹窗按钮没有 text，见 confirm2() 的说明
            if hit:
                print(f"  · 二次确认点了「{hit}」")
            time.sleep(0.15)
            if dialog_open():                   # 弹窗还在：不再点了，避免又被遮罩关掉、来回拨
                print(f"  ✗ {page}：确认框关不掉，停止本页")
                p.back(1)
                return done
            tried[t] = tried.get(t, 0) + 1
            if any(tt == t and cc for tt, cc, _ in rows()):
                continue                        # 还开着，下一屏再看
            print(f"  关 {t}")
            p.changed.append((page, t))
            done += 1
        if not p.scroll_more():
            break
    left = [t for t, c, _ in rows() if c and t and t in tried]
    for t in dict.fromkeys(left):
        print(f"  ✗ 关不掉 {t}")
    return done


def tap_text(w, scrolls=0, wait=1.3):
    ok = p.tap(w, exact=True, scrolls=scrolls)
    time.sleep(wait)
    return ok


def goto(name, scrolls=0):
    """点进一个列表项，并把结果打出来。
    不打印就没法区分「这页确实没开关可关」和「压根没进到这页」，跑完看到 0 个也敢信。"""
    ok = tap_row(name, scrolls=scrolls)
    print(f"  · {name}" if ok else f"  ✗ 没找到「{name}」")
    return ok


def result_xy(kw, root=None):
    """搜索结果里挑真正那一条。
    ⚠ 搜索框本身是个 EditText，里面也有刚输入的关键词（y 在页面顶部），
    p.find(keyword) 按文档顺序会先命中它 —— 点上去等于又点了一次输入框，页面根本不跳，
    而且不会报错，整段就这么静默空跑。所以这里排除 EditText，并跳过顶部搜索栏那块。"""
    root = root if root is not None else p.tree()
    for t, (l, tp, r, b), n in p.texts(root):
        if t != kw or "EditText" in (n.get("class") or ""):
            continue
        cy = (tp + b) // 2
        if b <= tp or cy < p.H * 0.13:
            continue
        return ((l + r) // 2, cy)
    return None


def search_setting(kw, pick=True):
    """在系统设置里搜 kw 并点进第一条结果。
    引擎的 p.setting 依赖 focused 输入框，在 vivo 上时而等不到（会抛异常），这里直接按 resourceId 取输入框。
    点完还要确认焦点窗口真的变了，否则返回 False —— 宁可报错，也不要装作进去了。"""
    p.miss = 0
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    for _ in range(24):
        if p.find("搜索设置项"):
            break
        time.sleep(0.25)
    if not p.tap("搜索设置项", scrolls=0, wait=0.6):
        print("  ✗ 设置首页没找到搜索框"); return False
    try:
        p.d(resourceId="com.android.settings:id/vigour_search_edit").set_text(kw)
    except Exception as e:
        print(f"  ✗ 搜索框输入失败：{e}"); return False
    xy = None
    for _ in range(12):
        xy = result_xy(kw)
        if xy:
            break
        time.sleep(0.25)
    if not xy:
        print(f"  ✗ 没搜到「{kw}」"); return False
    if not pick:
        return True
    before = p.focus()
    p.click(p.W // 2, xy[1])
    for _ in range(15):
        if p.focus() != before:
            time.sleep(0.7)
            return True
        time.sleep(0.2)
    print(f"  ✗ 点「{kw}」的搜索结果没有跳转")
    return False


# ---------- 各段 ----------
@step("广告与隐私")
def _():
    if not search_setting("广告与隐私"):
        print("  ✗ 没进到广告与隐私"); return
    print("  · 广告与隐私")
    off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")
    # 「生活服务」推送建议不在本机型清单范围内，不动
    p.back(1)


def hiboar_panel():
    """回到负一屏的设置面板（com.vivo.hiboard/.settings.AppletSettingActivity）。
    子页来来回回地 back 很容易多退一层回到负一屏主页，后面的项就全找不到了 ——
    所以每进一个子页之前都用 Activity 确认一次，不在面板上就重新滑进来。
    不能用「屏上有『热点资讯』」来判断：负一屏主页上本来就有资讯卡片，会误判成面板。"""
    if "AppletSettingActivity" in p.focus():
        return True
    p.d.shell("input keyevent HOME"); time.sleep(1.0)
    for _ in range(3):
        p.d.shell(f"input swipe {p.W//10} {p.H//2} {p.W*9//10} {p.H//2} 250")
        time.sleep(1.5)
        if p.find("添加组件") or p.find("小V建议"):
            break
    p.tap("设置", exact=True, scrolls=0, wait=1.3)
    return "AppletSettingActivity" in p.focus()


@step("负一屏")
def _():
    if not hiboar_panel():
        print("  ✗ 没滑到负一屏（桌面可能没开负一屏），跳过"); return
    print("  · 负一屏设置面板")
    if goto("更多设置"):
        if goto("个性化推荐"):
            off(only=["服务推荐", "资讯推荐"], page="负一屏·个性化推荐")
    # ⚠ 便捷生活里的「推荐服务」不要关：那 10 个图标（扫码、手电筒、计算器）都靠它补位，关了整块变空
    for name in ("内容精选", "热点资讯"):
        if not hiboar_panel():
            print("  ✗ 回不到负一屏设置面板"); break
        p.top()
        # 热点资讯页的标题会串成页标题，rows() 已按行还原真实标题；
        # 悬浮/经典/卡片形态是单选钮，rows() 也排除了，不会被当开关拨
        if goto(name, scrolls=6):
            off(only=[name], page=f"负一屏·{name}")
    # 小V建议（航班、快递提醒）保留不动
    p.back(3)


@step("全局搜索")
def _():
    p.start("com.vivo.globalsearch", ".view.SearchSettingsActivity", settle=0.8)
    if "globalsearch" not in p.focus():
        print("  ✗ 没拉起全局搜索设置"); return
    if goto("首页展示内容"):
        off(only=["搜索框推荐词", "推荐卡片"], page="搜索·首页展示内容")
        if goto("推荐热搜榜单", scrolls=4):
            off(only=["热门搜索"], page="搜索·推荐热搜榜单")
            p.back(1)
        p.back(1)
    p.top()
    if goto("个性化内容"):
        off(only=["广告个性化"], page="搜索·个性化内容")   # 应用建议、搜索结果个性化保留
        p.back(1)
    # 「搜索项」是搜索范围本身，不动
    p.back(1)


@step("应用商店")
def _():
    p.start("com.bbk.appstore", settle=1.0)
    if not tap_text("我的"):
        print("  ✗ 没找到「我的」"); return
    if not tap_text("设置"):
        print("  ✗ 「我的」页没找到设置"); return
    print(f"  · 商店设置页 {p.focus()}")
    if goto("关于"):
        if goto("个性化推荐"):
            off(only=["个性化推荐"], page="商店·个性化推荐")
            p.back(1); time.sleep(0.8)
        p.top()
        if goto("服务管理", scrolls=2):
            # 这一页用白名单：「我的服务」「空间清理」要留着
            off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                keep=["我的服务", "空间清理"], page="商店·服务管理")
            p.back(1); time.sleep(0.8)
        p.back(1)
    p.back(3)


def browser_settings():
    """进浏览器设置。首选右上「菜单 → 设置」：首页就有，不依赖底部有没有「我的」标签页。
    （实测冷启动会直接停在首页，底部只有菜单/窗口，没有「我的」，走「我的」会整段跑空。）"""
    try:
        p.d(resourceId="com.vivo.browser:id/menu_btn").click()
        time.sleep(1.4)
        if p.tap("设置", exact=True, scrolls=0, wait=1.3) and "SettingActivity" in p.focus():
            return True
    except Exception:
        pass
    p.d.shell("input keyevent BACK")
    time.sleep(0.8)
    if p.tap("我的", exact=True, scrolls=4, wait=1.2):     # 兜底：「我的」页顶部也有设置入口
        p.top()
        if p.tap("设置", exact=True, scrolls=0, wait=1.3) and "SettingActivity" in p.focus():
            return True
    return False


@step("浏览器")
def _():
    p.start("com.vivo.browser", settle=1.5)
    if not browser_settings():
        print("  ✗ 没进到浏览器设置"); return
    print(f"  · 浏览器设置页 {p.focus()}")
    if goto("首页设置"):
        if p.tap("极简首页", exact=True, scrolls=0):    # 三选一的卡片，不能点行中间
            confirm2()
            print("  · 首页切成极简首页")
        p.back(1); time.sleep(0.6); p.top()
    for name, words in (("网页浏览设置", ["网页下载相关推荐"]),
                        ("更多设置", ["WiFi连接跳转新闻资讯"]),        # 在设置页中段
                        ("隐私权限设置", ["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"])):
        p.top()                                   # 每次都从顶部开始翻，位置才可预期
        if goto(name, scrolls=10):
            off(only=words, page=f"浏览器·{name}")
            p.back(1); time.sleep(0.6)
    p.back(3)


@step("阅图锁屏")
def _():
    if not search_setting("阅图锁屏"):
        print("  ✗ 没进到阅图锁屏"); return
    if "MagazineSettings" not in p.focus():        # 万一停在搜索结果页，再点一次结果
        p.tap("阅图锁屏", exact=True, scrolls=4)
        time.sleep(1.5)
    print(f"  · 阅图锁屏页 {p.focus()}")
    off(only=["阅图锁屏", "锁屏横滑进入阅图"],
        keep=["锁屏底部壁纸", "移动网络自动更新"], page="系统·阅图锁屏")
    # 锁屏壁纸保持原样
    p.back(2)


@step("i管家")
def _():
    p.start("com.iqoo.secure", settle=2.0)
    time.sleep(1.2)                            # 首屏有体检动画，动画期间点设置会被吞
    ok = False
    for _ in range(3):
        if p.tap("设置", exact=True, scrolls=0):
            time.sleep(1.2)
            if "MainSettings" in p.focus():
                ok = True
                break
    if not ok:
        print("  ✗ 没进到 i 管家设置"); return
    if goto("关于", scrolls=2):
        if goto("个性化设置", scrolls=2):
            off(only=["应用个性化推荐", "清理个性化推荐"], page="i管家·个性化设置")
            p.back(1)
        p.back(1)
    p.back(2)


@step("天气")
def _():
    p.start("com.vivo.weather", settle=1.2)
    # 页面上也有个「更多」文字（展开按钮），右上角才是菜单，按 resourceId 点
    try:
        p.d(resourceId="com.vivo.weather:id/more_btn").click()
    except Exception:
        print("  ✗ 没找到天气右上角的更多按钮"); return
    time.sleep(1.3)
    if not tap_text("设置"):
        print("  ✗ 天气菜单里没找到设置"); return
    print(f"  · 天气设置页 {p.focus()}")
    off(only=["天气服务"], keep=["气象预警", "异常天气", "地震预警"], page="天气·设置")
    # 气象预警、异常天气、地震预警、提醒城市都保留
    p.back(2)
