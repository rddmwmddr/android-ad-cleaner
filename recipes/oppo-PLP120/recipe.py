# OPPO Find N6（PLP120，ColorOS 16.0.9）机型脚本。路径 2026-10-22 实测，机型脚本整段跑待验证
# 2026-11-10 补 ColorOS 17（PLP120_17.0.0.109 / Android 17）的两段路径，未复测（#905）：
# 小布建议改成点「资讯服务」进二级页再关（旧「内容资讯」列表页兜底），游戏中心先试
# APP_SETTINGS 直达设置页（「我的 → 设置」兜底）。两条路径都取自同族真机实测（PMX110 / PKT110）。
BUILD = "PLP120_16.0.9"
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
import time

import adb_link
from fast import ScreenLocked

GAME = "com.nearme.gamecenter"
SETTINGS = "com.android.settings"


def enter_settings(*path):
    """设置 → path 逐跳点开，每一跳都要真的换页：点击被弹窗淡出动画吞掉时重试（#286）。"""
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    for name in path:
        p.enter(name, scrolls=6)


def read_on_page(titles, package):
    """确认落在目标页并读出这一页的开关：读不到目标时整段不动，报错带上停在哪个页与当次
    读到的标题（#903），不再「核对 0 项」静默收尾。"""
    page(titles, package)
    from wait import until
    until(p.switches, tries=10, poll=0.2, now=time.time, sleep=time.sleep)
    return {text: on for text, on, _ in p.switches()}


def open_switch_page(name, titles, package):
    """点开入口 → 确认落在目标页 → 读出开关；任一步不通就退回原页并返回空，把兜底留给调用方。
    `p.enter` 只认「页面变了」，点进别的页也算换页，所以落点必须再校验一次（#286）。
    断线、锁屏与按约定跳过照常上抛，交给段包装收场。"""
    where = p.focus()
    try:
        p.enter(name, scrolls=8)
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError as error:
        print(f"  · 入口「{name}」没进去：{error}", flush=True)
        p.note_miss(name)
        return None
    try:
        return read_on_page(titles, package)
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError as error:
        print(f"  · 落点不对：{error}", flush=True)
        if p.focus() != where:
            p.back()
            time.sleep(0.6)
        return None


@step("广告跟踪")
def _():
    # 每个 App 一个开关、没有总开关；新装的 App 默认开。ColorOS 17 首页改叫「隐私与安全」（#165 社区实测）
    skip_in_safe_mode()
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


def game_settings_direct():
    """ColorOS 17 的游戏中心设置页认 APP_SETTINGS 动作，直达（PMX110，#650）。
    旧版本不认这个动作时落不到设置页，返回假交给「我的 → 设置」兜底。"""
    result = p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + GAME)
    if result.exit_code or any(word in result.output for word in
                               ("Error", "Exception", "Permission Denial", "unable to resolve")):
        return False
    try:
        page("游戏中心", GAME, "SettingActivity")
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError:
        print("  · 直达没落在设置页，转「我的 → 设置」", flush=True)
        return False
    return True


def game_settings_entry():
    """「我的」页的「设置」：旧版是文字行（可能读作「设置,有1条新通知」），新版是右上角没有
    文字的齿轮（#292）。文字行点进了别的页就退回来改用齿轮，不把落点押在包含匹配上。"""
    where = p.focus()
    try:
        p.enter("设置", scrolls=0)
        page("隐私开关设置", GAME)
        return
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError:
        if p.focus() != where:
            p.back()
            time.sleep(0.6)
    if not p.tap_icon(["隐私开关设置", "隐私"]):
        raise RuntimeError("没找到设置入口：文字与右上角图标都试过")


def game_settings_via_mine():
    """我的 → 设置；首次进入的「页面升级」弹窗盖住这一页，先关掉。"""
    p.start(GAME)
    p.enter("我的")
    time.sleep(1.2)
    # 「页面升级」弹窗里带滚动列表，dismiss() 不点文字按钮，只能点名点（PKT110）。
    if p.find("我知道了", exact=True):
        p.tap("我知道了", exact=True, scrolls=0); time.sleep(1.2)
    else:
        p.dismiss()
    game_settings_entry()


@step("游戏中心")
def _():
    direct = game_settings_direct()
    if not direct:
        game_settings_via_mine()
    p.enter("隐私开关设置", scrolls=6)
    p.enter("个性化推荐管理", scrolls=4)
    require_switches(read_on_page("个性化推荐管理", GAME), ["个性化推荐"], "个性化推荐管理")
    p.off(only=["个性化推荐"], page="游戏中心·个性化推荐")
    p.back(3 if direct else 4)


@step("小布建议")
def _():
    # ColorOS 17：「内容资讯」是点不动的分组标题，入口是它下面那行「资讯服务」，开关在二级页
    # （PMX110 / #905）。ColorOS 16 仍是点「内容资讯」进列表页、在那页上关。
    # 这一页还有快递、航班、日程提醒与商圈服务，保持不动。
    enter_settings("OPPO AI", "小布建议")
    page("小布建议", SETTINGS)
    switches = open_switch_page("资讯服务", "资讯服务", SETTINGS)
    if switches is not None:
        require_switches(switches, ["资讯服务"], "资讯服务")
        p.off(only=["资讯服务"], page="小布建议·资讯服务")
        return
    # 旧版本这一页的标题没有实测记录，两种叫法都认。
    switches = open_switch_page("内容资讯", ["内容资讯", "资讯服务"], SETTINGS)
    if switches is not None:
        require_switches(switches, ["资讯服务"], "内容资讯")
        p.off(only=["资讯服务"], page="小布建议·内容资讯")
        return
    raise RuntimeError("小布建议：「资讯服务」与「内容资讯」两条入口都没进去")
