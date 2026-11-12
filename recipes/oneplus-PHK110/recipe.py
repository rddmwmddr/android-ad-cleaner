# 一加 Ace 2（PHK110，ColorOS 16 / Android 16）机型脚本。
# 路径实测：2026-10-25。只收录已走通的系统广告跟踪、商店、浏览器设置。
# 不挂包、不动通知渠道；这些操作仍走 run.py 的独立、需确认流程。
BUILD = "PHK110_16.0.5.1201"

import time
RESULTS = []

# 仅关闭明确的推广入口。没有列出的入口（包括未来新增项）不主动处理。
STORE_PROMOTIONS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "游戏专区：找游戏-种草", "游戏专区：重磅更新卡片", "游戏详情页：游戏活动卡片",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：积分商城", "我的专区：休闲一刻",
    "我的专区：安装有礼", "我的专区：福利中心", "我的专区：金豆乐园",
    "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动", "游戏详情页：游戏礼包",
    "手机管家：应用推荐", "文件管理：应用推荐", "游戏专区：活动集合", "详情页：限时活动", "福利专区",
]


def off_exact(names, page, max_screens=16):
    """逐页传入当前可见的精确标题，不把“福利”之类子串扩展到未知服务。"""
    wanted, seen, failed = set(names), set(), set()
    for _ in range(max_screens):
        root = p.tree()
        visible = {title for title, _, _ in p.switches(root)}
        targets = wanted & visible
        seen.update(targets)
        if targets:
            before = len(p.changed)
            expected_changes = {title for title, on, _ in p.switches(root)
                                if on and title in targets}
            # fast.off 的 only 是子串匹配；把所有非精确命中的可见标题排除。
            # max_screens=1 仍可能翻一页，所以每轮重新获取实际可见页面。
            p.off(only=list(targets), keep=list(visible - targets), page=page, max_screens=1)
            changed = {title for _, title in p.changed[before:]}
            failed.update(expected_changes - changed)
        elif not p.scroll_more():
            break
        # off 已尝试翻到下一屏；只在全局滚动到底后收尾。
        current = {title for title, _, _ in p.switches()}
        if current == visible:
            break
    if failed or wanted - seen:
        print(f"  ! 未关闭 {sorted(failed)}；未找到 {sorted(wanted - seen)}")
        return False
    return True


def guard():
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PHK110" or not build.startswith(BUILD):
        skip("型号或系统版本不同，跳过；请重新核对页面")


@step("广告跟踪")
def _():
    # 此版本的 OAIDActivity 不能由 shell 直接拉起，必须走系统设置中的搜索结果。
    skip_in_safe_mode()
    if not p.setting("设备标识与广告"):
        raise RuntimeError("没搜到「设备标识与广告」")
    result = p.d(resourceId="android:id/title", text="设备标识与广告")
    if result.exists:
        result.click()
    if not wait_page("com.android.settings.SubSettings", "设备标识与广告"):
        return False
    if not p.find("重置设备标识符", exact=True):
        return False
    if not tap_page("广告跟踪", "com.oplus.settings.feature.notification.oaid.OAIDActivity", "广告跟踪"):
        return False
    # 等应用列表真正加载，不能把只有标题的空白加载页视为完成。
    for _ in range(30):
        if p.switches():
            break
        time.sleep(0.2)
    if not p.switches():
        print("  ✗ 广告跟踪列表未加载")
        return False
    p.top(n=16)
    p.off(page="广告跟踪", max_screens=40)
    return True


@step("软件商店")
def _():
    store_promotions()


@step("浏览器首页")
def _():
    browser_home()


@step("浏览器广告")
def _():
    browser_ads()


@step("浏览器个性化")
def _():
    browser_personalized()


print("\n本机型脚本不处理：下拉搜索、负一屏、主题服务模式、视频和游戏中心。")
print("广告包、乐划锁屏、快应用和通知渠道请按 run.py 标准流程另行确认。")
print("分段结果：", RESULTS)
