"""honor 家族库（#1269）：只被 honor 家族用到的实现住在这里。

上半是词汇（原 `recipe_nav`），下半是策略（原 `recipe_strategies` / `recipe_steps`）。
跨家族用到的实现不放在这里，见 `recipe_lib/shared.py`。
"""

from recipe_lib.shared import tap

__all__ = ('baidu_browser', 'close_named_honor', 'no_agreement', 'scan_switches')

# ---------- 词汇 ----------
def _honor_my_tab(p, rt, app):
    """底栏可能被晚到的弹窗盖住（阅读开屏广告之后才弹「发现新版本」）：关掉再找。

    协议框不关，只跳过（CLE-AN00）。"""
    for _ in range(4):
        no_agreement(p, rt, app)
        if p.find("我的", edge_ok="tab"):
            break
        p.dismiss()
        rt.clock.sleep(1.5)
    if not p.tab("我的"):
        raise RuntimeError(f"{app}底部「我的」没找到")
    rt.clock.sleep(1)

def _honor_browser_settings_mounted(p, rt):
    if "package:" not in p.d.shell("pm path com.honor.browser").output:
        return baidu_browser(p, rt)
    p.start("com.honor.browser")
    p.dismiss()
    if p.find("我的", exact=True):                       # 经典首页：我的 → 右上第三个图标
        p.tap("我的", exact=True, scrolls=0)
        p.d(resourceId="com.honor.browser:id/top_local_icon")[2].click()
        rt.clock.sleep(1)
    else:                                                # 简洁首页：更多 → 设置
        p.tap("更多", exact=True, scrolls=0)
        p.tap("设置", exact=True, scrolls=0)

def _honor_browser_settings_plain(p, rt):
    package = "com.honor.browser"
    if p.focus().split("/", 1)[0] == package and {"模式选择", "隐私管理"} <= labels(p):
        return package
    p.start(package)
    # 本机已验证「更多 → 设置」；经典首页的未知图标位置不猜。
    tap(p, rt, "更多", scrolls=0)
    tap(p, rt, "设置", scrolls=0)
    settle_page(p, rt, package, "模式选择", "隐私管理")
    return package

def _honor_app_settings(p, rt, package, *markers):
    p.start(package)
    rt.require(p.go("我的", "设置"), "未找到应用设置入口")
    tap(p, rt, "设置", scrolls=0)
    settle_page(p, rt, package, *markers)

def labels(p, root=None):
    """这一页读到的全部文字（WKL-AN20 的落点判据）。"""
    return {text for text, _, _ in p.texts(root)}

def no_agreement(p, rt, app):
    """App 还弹着用户协议就停（CLE-AN00）。"""
    if p.find("同意", exact=True, edge_ok="tab") or p.find("同意并继续", exact=True, edge_ok="tab"):
        rt.skip(f"{app}还没同意用户协议，不代为同意。需要的话打开{app}同意后，单独跑这一段")

def settle_page(p, rt, package, *markers, timeout=5):
    """包名、可见标题和节点位置连续稳定后才使用坐标；不输出账号内容（WKL-AN20）。"""
    deadline, previous = rt.clock.monotonic() + timeout, None
    while rt.clock.monotonic() < deadline:
        rt.require(not p.locked(), "手机锁屏，请机主解锁后重跑")
        root = p.tree()
        texts = p.texts(root)
        if any(text in ("同意", "同意并继续", "同意并使用", "允许")
               and "Button" in node.get("class", "")
               for text, _, node in texts):
            p.dismiss()
            raise RuntimeError("遇到协议或权限申请，未代为同意，本段停止")
        signature = (p.focus(), tuple((text, box) for text, box, _ in texts))
        if signature[0].split("/", 1)[0] == package and set(markers) <= labels(p, root):
            if texts and signature == previous:
                return root
        previous = signature
        rt.clock.sleep(.25)
    raise RuntimeError("未确认目标设置页：" + "、".join(markers))

# ---------- 策略 ----------
def baidu_browser(p, rt):
    """新机预装 com.hihonor.baidu.browser（沿用 #87 社区实测 PTP-AN00）：我的 → 右上齿轮 → 消息设置 / 隐私设置。
    「广告设置」是网页，读不到开关；其中「不看程序化广告」「不看个性化广告」要打开，请手动处理。"""
    import re

    from fast import bounds

    p.start("com.hihonor.baidu.browser")
    p.dismiss()
    for text, (l, t, r, b), _ in p.texts():
        if text == "我的" and t >= p.H * 0.8:
            p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1); break
    else:
        print("  ✗ 没找到底部「我的」"); return False
    icons = [n for n in p.tree().iter("node") if n.get("clickable") == "true" and p.on_screen(n)
             and bounds(n)[3] < p.H * 0.15 and bounds(n)[0] > p.W * 0.5
             and re.search(r"设置|setting", (n.get("content-desc") or "") + (n.get("resource-id") or ""), re.I)]
    if len(icons) != 1:
        print("  ✗ 没找到右上角唯一的设置图标"); return False
    l, t, r, b = bounds(icons[0]); p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1)
    if p.tap("消息设置", exact=True):
        p.off(only=["新闻热点", "兴趣推送"], page="浏览器·消息设置")
        p.back()
    if p.tap("隐私设置", exact=True):
        p.off(only=["搜索个性化推荐", "搜索下一条推荐"], page="浏览器·隐私设置")
        p.back()
    print("  · 「隐私设置 → 偏好设置 → 广告设置」是网页，请手动打开「不看程序化广告」「不看个性化广告」")
    p.back(2)
    return False

def scan_switches(p, rt, max_screens):
    states = {}
    for index in range(max_screens):
        for title, state, _ in p.switches():
            rt.require(bool(title), "出现无标题开关，未操作")
            rt.require(title not in states or states[title] == state, "同名开关状态不一致，未操作")
            states[title] = state
        if not p.scroll_more():
            return states
        rt.require(index + 1 < max_screens, "列表超过扫描上限，未确认完整列表")
    return states

def close_named_honor(p, rt, names, title, package, marker, max_screens=6, drawn=False):
    """精确标题白名单；操作前完整扫描，操作后核对目标及其他开关。"""
    from fast import Phone, want_state

    # 回读确认数由引擎经 rt 记录
    settle_page(p, rt, package, marker)
    native = p.switches

    def read(root=None):
        root = root if root is not None else p.tree()
        rt.require(p.focus().split("/", 1)[0] == package and marker in labels(p, root),
                     "已离开目标设置页，停止读取开关")
        # 仅阅读的「广告推荐服务」设置页允许截图识别自绘开关，不写图片文件。
        if drawn:
            rt.require(package == "com.hihonor.dz.reader" and marker == "广告推荐服务",
                         "此页不允许自绘开关截图")
            return Phone.switches(p, root)
        return native(root)

    p.switches = read
    try:
        p.top(max_screens)
        before = scan_switches(p, rt, max_screens)
        # OAID 的应用名称随安装列表变化，不把机主应用清单写入脚本。
        wanted = set(before) if names is None else set(names)
        rt.require_switches(before, wanted, title)
        p.top(max_screens)
        p.switches = lambda root=None: [item for item in read(root) if item[0] in wanted]
        p.off(only=sorted(wanted), page=title, max_screens=max_screens)
        p.switches = read
        p.top(max_screens)
        after = scan_switches(p, rt, max_screens)
        rt.require(all(after.get(name) == want_state(name) for name in wanted),
                     title + "：回读未确认目标状态")
        rt.require(all(after.get(name) == state for name, state in before.items() if name not in wanted),
                     title + "：其他开关状态变化，请机主核对")
        rt.confirm(len(wanted))
        print(f"  · {title}：已回读 {len(wanted)} 项", flush=True)
    finally:
        p.switches = native
