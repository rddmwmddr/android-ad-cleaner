# OPPO Find N6（PLP120，ColorOS 16.0.9）机型脚本。路径 2026-10-22 实测，机型脚本整段跑待验证
BUILD = "PLP120_16.0.9"
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
import time

ONLY = globals().get("ONLY") or []


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
                print(f"  ✗ 出错：{e}")
            print(f"  ({time.time()-t:.0f} 秒)")
        return f
    return deco


def settings_page(*path):
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    for t in path:
        if not p.tap(t, exact=True):
            return False
    return True


@step("广告跟踪")
def _():
    # 每个 App 一个开关、没有总开关；新装的 App 默认开。ColorOS 17 首页改叫「隐私与安全」（#165 社区实测）
    found = settings_page("隐私", "设备标识与广告", "广告跟踪")
    if not found:
        p.miss = 0
        found = settings_page("隐私与安全", "设备标识与广告", "广告跟踪")
    if found:
        p.off(page="广告跟踪")


@step("负一屏")
def _():
    p.d.shell("input keyevent HOME"); time.sleep(0.6); p.d.shell("input keyevent HOME"); time.sleep(0.6)
    for _ in range(3):
        p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
        if "assistantscreen" in p.focus():
            break
    # 左上头像 → 设置
    av = [n for n in p.tree().iter("node") if "头像" in (n.get("content-desc") or "") + (n.get("text") or "")]
    if av:
        from fast import bounds
        l, t, r, b = bounds(av[0]); p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
    p.tap("设置", exact=True, scrolls=0)
    p.off(only=["搜索框提示词"], page="负一屏")
    # ⚠ 「推荐服务」总开关不要关：会删掉天气/步数/清理卡片
    if p.tap("推荐服务", exact=True):
        if p.tap("轮播推荐", exact=True):
            p.tap("不显示", exact=True, scrolls=0)
            p.back()
        p.back()
    p.back(2)


SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 设置页上的标题；搜索首页也有「搜索范围」这类文字，所以还要看前台 Activity（SearchSettingActivity）。
SEARCH_TITLES = {"搜索范围", "功能管理", "搜索引擎", "消息管理", "账号与隐私"}


def wait_search_settings(tries=30):
    from wait import until

    def sample():
        focus = p.focus()
        if "com.heytap.quicksearchbox" not in focus or "Setting" not in focus:
            return False
        return bool(SEARCH_TITLES & {text for text, _, _ in p.texts()})

    return bool(until(sample, tries=tries, same=2, now=time.monotonic, sleep=time.sleep))


def search_settings():
    """先走 scheme，打不开再退回桌面下滑进搜索页、点底部「设置」的旧入口（#165）。"""
    p.d.shell(SEARCH_SETTING)
    if wait_search_settings():
        return True
    # ColorOS 16 及更早版本：桌面下滑进搜索页，底部「设置」。别往下拉，会退出。
    p.d.shell("input keyevent HOME"); time.sleep(0.6)
    p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); time.sleep(1.5)
    p.d.shell("input keyevent BACK"); time.sleep(0.4)      # 收键盘
    return p.tap("设置", exact=True) and wait_search_settings()


def search_sources():
    """借给别的机型（安全模式）时只关推荐位：ColorOS 17 上榜单 / 小说 / 购物是内容源，关掉会搜不到东西。"""
    if p.safe_mode:
        return ["个性化推荐", "精选资讯"]
    return ["榜单", "小说", "购物", "个性化推荐", "精选资讯"]


@step("下拉搜索")
def _():
    if not search_settings():
        print("  · 跳过：没有认出全局搜索设置页（入口不可用或被系统限制）", flush=True)
        return
    if p.tap("搜索范围", exact=True):
        p.off(only=search_sources(), page="下拉搜索·搜索范围")
        p.back()
    if p.tap("功能管理", exact=True):
        p.off(only=["搜索框提示词"], page="下拉搜索·功能管理")
        p.back()
    p.miss = 0
    if not p.tap("账号与隐私", exact=True):
        p.miss = 0                     # ColorOS 17：「账号与隐私」只是分组标题，直接找「隐私」
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="下拉搜索·隐私")
        p.back(2)
    p.back(2)


STORE_KEEP = ["帮助与客服", "应用安全", "应用工具", "存储空间清理", "我的资产", "安全守护",
              "小i客服", "应用使用记录", "首页 AI 搜索", "自动检测风险应用"]


@step("软件商店")
def _():
    p.start("com.heytap.market")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="商店·隐私")
        p.back()
    if p.tap("服务管理", exact=True):
        p.off(keep=STORE_KEEP, page="商店·服务管理")
        p.back()
    p.back(2)


@step("浏览器")
def _():
    p.start("com.heytap.browser")
    if p.find("我的", exact=True, edge_ok="tab"):          # X9 Ultra：底部「我的」→ 设置
        p.go("我的", "设置"); p.tap("设置", exact=True, scrolls=0)
    elif p.find("菜单") or p.find("更多"):                 # Find N6：底部 ☰ → 齿轮
        p.tap("菜单", scrolls=0) or p.tap("更多", scrolls=0)
        p.tap("设置", scrolls=0)
    else:
        # 首页切成「简洁」后没有「我的」和菜单（ColorOS 17，#165）：浏览器在前台时直达设置页；带清栈参数会立刻退出
        p.d.shell("am start -n com.heytap.browser/.settings.component.BrowserPreferencesPage"); time.sleep(1.2)
        if "com.heytap.browser" not in p.focus():
            print("  ✗ 浏览器设置页没有打开"); return
    if p.tap("主页设置", exact=True):
        if p.tap("页面布局", exact=True):
            p.tap("简洁", exact=True, scrolls=0); p.back()
        p.back()
    if p.tap("隐私", exact=True) and p.tap("广告管理", exact=True):
        p.off(only=["开屏广告", "资讯列表广告", "摇一摇"], page="浏览器·广告管理")
        p.back(2)
    p.back(2)


@step("主题")
def _():
    p.start("com.heytap.themestore")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("服务管理", exact=True) and p.tap("消息与广告", exact=True):
        p.off(only=["消息通知", "开屏广告"], page="主题·消息与广告")
        p.back(2)
    if p.tap("隐私", exact=True) and p.tap("个性化推荐设置", exact=True):
        p.off(only=["个性化推荐"], page="主题·个性化推荐")
        p.back(2)
    p.back(2)


@step("视频")
def _():
    p.start("com.heytap.yoli")
    p.go("我的", "设置")
    p.tap("设置", exact=True)
    if p.tap("个性化内容管理", exact=True):
        p.off(only=["个性化推荐"], page="视频·个性化")
    p.back(3)


@step("游戏中心")
def _():
    p.start("com.nearme.gamecenter")
    if not p.tap("我的", exact=True, scrolls=0):
        raise RuntimeError("没找到底部「我的」")
    time.sleep(1.2)
    p.dismiss()
    # ColorOS 17 的「设置」是右上角没有文字的齿轮，按文字找不到（#292）
    if not p.tap("设置", exact=False, scrolls=0) and not p.tap_icon(["隐私开关设置", "隐私"]):
        raise RuntimeError("没找到设置入口：右上角图标都点过")
    if p.tap("隐私开关设置", exact=True) and p.tap("个性化推荐管理", exact=True):
        p.off(only=["个性化推荐"], page="游戏中心·个性化")
    p.back(4)


@step("小布建议")
def _():
    if settings_page("OPPO AI", "小布建议", "内容资讯"):
        p.off(only=["资讯服务"], page="小布建议·内容资讯")   # 商圈服务保留
