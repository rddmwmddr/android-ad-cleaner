# OPPO Find X9 Ultra（PMA110），ColorOS 17.0.0.106(CN01) / Android 17。
# 2026-10-29 真机逐页记录；仅收录本机已识别的开关，不包含包操作和通知渠道。
BUILD = "PMA110_17.0.0.106(CN01)"

import os
import re
import time

from fast import ScreenLocked, bounds
RESULTS = []
VERIFIED_SWITCHES = 0

SETTINGS = "com.android.settings/com.oplus.settings.feature.homepage.OplusSettingsHomepageActivity"
OAID = "com.android.settings/com.oplus.settings.feature.notification.oaid.OAIDActivity"
BROWSER = "com.heytap.browser/com.heytap.browser.settings.component."
SEARCH = "com.heytap.quicksearchbox/com.heytap.quicksearchbox.ui.activity."
MARKET = "com.heytap.market/com.heytap.market.mine.cn.setting.ui."
THEME = "com.heytap.themestore/com.nearme.themespace.activities."
VIDEO = "com.heytap.yoli/com.heytap.yoli.mine.setting."
ADVICE = "com.oplus.pantanal.ums/com.oplus.advice.settings.ui."
ASSISTANT = "com.coloros.assistantscreen/com.oplus.assistantscreen."
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"


def wait_page(activity, title, timeout=6):
    """只在实际 Activity、标题及可见文字稳定后继续；不在账号页读开关或截图。"""
    end, previous = time.monotonic() + timeout, None
    while time.monotonic() < end:
        if p.locked():
            raise ScreenLocked("手机锁屏，请机主解锁")
        if p.focus() == activity:
            root = p.tree()
            texts = p.texts(root)
            consent = {"同意", "同意并继续", "同意并使用", "允许"}
            require(not any(t in consent and "Button" in n.get("class", "")
                            for t, _, n in texts), "出现协议或权限申请，本段停止，不代为同意")
            signature = tuple((t, xy) for t, xy, _ in texts)
            if any(t == title for t, _, _ in texts) and signature == previous:
                return
            previous = signature
        time.sleep(.15)
    raise RuntimeError(f"未确认页面「{title}」，不操作开关")


def open_page(command, activity, title):
    result = p.d.shell(command)
    require(not result.exit_code and not re.search(
        r"Error|Exception|Permission Denial|unable to resolve", result.output, re.I),
        f"系统未允许打开「{title}」，未继续操作")
    wait_page(activity, title)


def tap_page(text, activity, title=None, scrolls=4, exact=True):
    require(p.tap(text, exact=exact, scrolls=scrolls), f"未找到入口「{text}」")
    wait_page(activity, title or text)


def read_switches(activity, title, max_screens=8):
    """完整读取有界列表；未读完不改，空标题不作为可操作目标。"""
    wait_page(activity, title)
    p.top(max_screens)
    states = {}
    for _ in range(max_screens):
        require(p.focus() == activity, "读取时离开目标页面，停止本段")
        states.update({name: on for name, on, _ in p.switches() if name})
        if not p.scroll_more():
            return states
    raise RuntimeError("列表超过读取上限，未执行关闭")


def close_named(names, page, activity, title, max_screens=8, reopen=None, dependent=()):
    """精确核对标题再调用引擎；回读关闭状态，同时保留其他功能开关。"""
    global VERIFIED_SWITCHES
    before = read_switches(activity, title, max_screens)
    require(all(name in before for name in names), f"{page}：未识别全部目标开关，未操作")
    if any(before[name] for name in names):
        p.top(max_screens)
        # off 的 only 为子串匹配，keep 排除所有非精确目标（包括未知的相似标题）。
        p.off(only=list(names), keep=[name for name in before if name not in names],
              page=page, max_screens=max_screens)
        if reopen:
            reopen()
        current = read_switches(activity, title, max_screens)
        require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
        require(all(current.get(name) == state for name, state in before.items()
                    if name not in names and name not in dependent), f"{page}：其他开关状态变化，请核对")
    VERIFIED_SWITCHES += len(names)
    print(f"  · {page}：回读确认 {len(names)} 项关闭", flush=True)


def system_settings():
    open_page("am start -f 0x10008000 -a android.settings.SETTINGS", SETTINGS, "设置")


def app_settings(package, activity, title):
    open_page("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package,
              activity, title)


def browser_settings():
    # 直达入口可能复用旧子页；只从已识别的浏览器设置子页返回，不清数据或历史。
    result = p.d.shell("am start -n com.heytap.browser/.settings.component.BrowserPreferencesPage")
    require(not result.exit_code and "Error" not in result.output, "浏览器设置未打开")
    time.sleep(.5)
    for _ in range(4):
        current = p.focus()
        if current == BROWSER + "BrowserPreferencesPage":
            wait_page(current, "浏览器")
            return
        require(current == BROWSER + "BrowserPreferenceActivity", "浏览器进入了未知页面，停止本段")
        p.back()
    raise RuntimeError("浏览器未回到设置首页")


def assistant_settings():
    # 本机子页未导出，走桌面入口，不尝试绕过权限。不截图「我的」页。
    p.d.shell("input keyevent HOME")
    time.sleep(.8)
    for _ in range(4):
        texts = {text for text, _, _ in p.texts()}
        if {"我的服务", "添加卡片"} <= texts:
            break
        require(p.focus().startswith("com.android.launcher/"), "未停在系统桌面，请勿同时操作手机")
        p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250")
        time.sleep(.8)
    else:
        raise RuntimeError("未进入负一屏，未继续操作")
    require(p.tap("我的", exact=True, scrolls=0), "未找到负一屏「我的」入口")
    tap_page("设置", ASSISTANT + "setting.AssistantScreenSettingActivity", scrolls=0)


def carousel_choices(root):
    """只识别有明确 checked 状态的单选控件；预览图的同名文字不能作为点击目标。"""
    parents = {child: node for node in root.iter() for child in node}
    choices = {}
    labels = {"显示轮播推荐", "不显示轮播推荐"}
    for node in root.iter("node"):
        if node.get("checkable") != "true" or "RadioButton" not in node.get("class", ""):
            continue
        row = node
        for _ in range(5):
            captions = {x.get("text", "") for x in row.iter("node")} | {
                x.get("content-desc", "") for x in row.iter("node")}
            matched = captions & labels
            if len(matched) == 1:
                name = matched.pop()
                require(name not in choices, "轮播单选项不唯一，未点击")
                require(p.on_screen(node) and node.get("enabled") == "true", "轮播单选项不可操作")
                require(node.get("checked") in ("true", "false"), "轮播单选状态未知，未点击")
                choices[name] = (node.get("checked") == "true", bounds(node))
                break
            row = parents.get(row)
            if row is None or len(matched) > 1:
                break
    require(set(choices) == labels and sum(on for on, _ in choices.values()) == 1,
            "无法确认轮播单选状态，未使用固定坐标")
    return choices


def hide_carousel():
    global VERIFIED_SWITCHES
    activity = ASSISTANT + "setting.recommendservice.RecommendServiceSettingActivity"
    wait_page(activity, "推荐服务")
    before = read_switches(activity, "推荐服务", max_screens=1)
    require("推荐服务" in before, "未读到推荐服务总开关，未操作")
    choices = carousel_choices(p.tree())
    if not choices["不显示轮播推荐"][0]:
        # 坐标由本次单选节点的 bounds 读取，不记录屏幕像素位置。
        l, t, r, b = choices["不显示轮播推荐"][1]
        require(p.focus() == activity, "点击前页面变化，未操作")
        p.click((l+r)//2, (t+b)//2)
        time.sleep(.4)
        current = carousel_choices(p.tree())
        require(current["不显示轮播推荐"][0], "轮播推荐回读未确认不显示")
        p.changed.append(("负一屏·推荐服务", "轮播推荐：不显示"))
    require(read_switches(activity, "推荐服务", 1) == before, "推荐服务总开关变化，请核对")
    VERIFIED_SWITCHES += 1
    print("  · 轮播推荐：已确认不显示，推荐服务总开关保持原值", flush=True)


@step("广告跟踪")
def _():
    global VERIFIED_SWITCHES
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if os.environ.get("AAC_REF") or model != "PMA110" or not build.startswith(BUILD):
        skip("参考或版本不同时不批量处理逐应用广告跟踪，需重新核对")
    print("  将关闭逐应用广告跟踪许可；应用清单从本机读取，不写入脚本。", flush=True)
    system_settings()
    tap_page("隐私与安全", "com.oplus.securitypermission/com.oplusos.securitypermission.privacy.PrivacySecuritySettingsDashboardActivity", scrolls=6)
    tap_page("设备标识与广告", "com.android.settings/com.oplus.settings.OplusSettingsActivity$DevicesIdentifySettingsActivity", scrolls=8)
    tap_page("广告跟踪", OAID, scrolls=0)
    before = read_switches(OAID, "广告跟踪", max_screens=60)
    require(before, "未读到广告跟踪列表，未操作")
    if any(before.values()):
        p.top(60)
        p.off(only=list(before), page="广告跟踪", max_screens=60)
        current = read_switches(OAID, "广告跟踪", max_screens=60)
        require(set(before) <= set(current) and not any(current.values()), "广告跟踪回读未确认全部关闭")
    VERIFIED_SWITCHES += len(before)
    print(f"  · 广告跟踪：回读确认 {len(before)} 个应用关闭", flush=True)


@step("浏览器")
def _():
    print("  将关闭个性化搜索/优惠推荐、开屏/资讯列表广告。", flush=True)
    browser_settings()
    activity = BROWSER + "BrowserPreferenceActivity"
    tap_page("隐私", activity, scrolls=4)
    close_named(["个性化搜索推荐", "个性化优惠推荐"], "浏览器·隐私", activity, "隐私", 2)
    tap_page("广告管理", activity, scrolls=0)
    close_named(["开屏广告", "资讯列表广告"], "浏览器·广告管理", activity, "广告管理", 2)
    print("  · 不单独点击灰置的摇一摇项；未验证简洁首页，不改布局。", flush=True)


@step("下拉搜索")
def _():
    print("  将关闭个性化推荐、精选资讯、搜索框提示词；保留消息总开关与搜索数据源。", flush=True)
    open_page(SEARCH_SETTINGS, SEARCH + "SearchSettingActivity", "搜索设置")
    activity = SEARCH + "SearchSourceActivity"
    tap_page("搜索范围", activity, scrolls=0)
    # 「全部」是聚合状态；两个子项关掉时它会随之变化，不直接拨它。
    close_named(["个性化推荐", "精选资讯"], "下拉搜索·搜索范围", activity, "搜索范围", 6, dependent=["全部"])
    p.back()
    activity = SEARCH + "SearchFunctionManagerActivity"
    tap_page("功能管理", activity, scrolls=2)
    close_named(["搜索框提示词"], "下拉搜索·功能管理", activity, "功能管理", 2)
    p.back()
    activity = SEARCH + "PrivacySettingsActivity"
    tap_page("隐私", activity, scrolls=4)
    close_named(["个性化推荐"], "下拉搜索·隐私", activity, "隐私", 2)


@step("软件商店")
def _():
    print("  将关闭个性化推荐；保留下载、更新、应用安全与全部服务模式。", flush=True)
    app_settings("com.heytap.market", MARKET + "SettingActivity", "软件商店")
    tap_page("隐私", MARKET + "PrivacyActivity", scrolls=8)
    activity = MARKET + "PersonalRecommendActivity"
    tap_page("个性化推荐", activity, scrolls=0)
    close_named(["个性化推荐"], "软件商店·个性化推荐", activity, "个性化推荐", 4)


@step("主题商店")
def _():
    print("  将关闭开屏广告、锁屏左滑精选、个性化推荐；保留消息总开关与锁屏相机。", flush=True)
    app_settings("com.heytap.themestore", THEME + "SettingActivity", "主题商店")
    tap_page("服务管理", THEME + "SettingServiceManagerActivity", scrolls=0)
    activity = THEME + "MessageAndRecommendationSettingActivity"
    tap_page("消息与广告", activity, scrolls=0)
    close_named(["开屏广告"], "主题商店·消息与广告", activity, "消息与广告", 2)
    p.back()
    close_named(["锁屏左滑查看精选内容"], "主题商店·服务管理", THEME + "SettingServiceManagerActivity", "服务管理", 2)

    def privacy():
        app_settings("com.heytap.themestore", THEME + "SettingActivity", "主题商店")
        tap_page("隐私", THEME + "PrivacyActivity", scrolls=2)

    privacy()
    close_named(["个性化推荐设置"], "主题商店·隐私", THEME + "PrivacyActivity", "隐私", 2, reopen=privacy)


@step("视频")
def _():
    print("  将关闭 OPPO 视频个性化推荐；保留在线播放和下载设置。", flush=True)
    p.start("com.heytap.yoli")
    require(p.go("我的", "设置"), "未找到视频设置入口")
    tap_page("设置", VIDEO + "SettingActivity", scrolls=0, exact=False)
    activity = VIDEO + "PersonalizedContentManageActivity"
    tap_page("个性化内容管理", activity, scrolls=3)
    close_named(["个性化推荐"], "OPPO视频·个性化内容管理", activity, "个性化内容管理", 2)


@step("小布建议")
def _():
    print("  将关闭资讯服务、视界日报、小红书资讯；保留出行、快递、日程等服务。", flush=True)
    system_settings()
    # OPPO AI 首页 Activity 随版本变化，只在本机实测的小布建议页后开始读开关。
    require(p.tap("OPPO AI", exact=True, scrolls=6), "未找到 OPPO AI")
    tap_page("小布建议", ADVICE + "AdviceSettingActivity", scrolls=5)
    activity = ADVICE + "detail.SceneServiceActivity"
    tap_page("资讯服务", activity, title="服务设置", scrolls=8)
    close_named(["资讯服务"], "小布建议·资讯服务", activity, "服务设置", 2)
    detail = ADVICE + "detail.AdviceDetailActivity"
    tap_page("视界日报", detail, title="服务设置", scrolls=0)
    close_named(["视界日报"], "小布建议·视界日报", detail, "服务设置", 2)
    p.back()
    tap_page("小红书资讯", detail, title="服务设置", scrolls=0)
    close_named(["小红书资讯"], "小布建议·小红书资讯", detail, "服务设置", 2)


@step("负一屏")
def _():
    print("  将关闭热点资讯及其个性化推荐，轮播改为不显示；保留功能卡片和推荐服务总开关。", flush=True)
    assistant_settings()
    activity = ASSISTANT + "card.infoflow.setting.activity.InfoFlowSettingActivity"
    tap_page("热点资讯", activity, scrolls=0)
    close_named(["热点资讯"], "负一屏·热点资讯", activity, "热点资讯", 2)
    p.back()
    activity = ASSISTANT + "setting.recommendservice.RecommendServiceSettingActivity"
    tap_page("推荐服务", activity, scrolls=0)
    hide_carousel()
    p.back()
    tap_page("隐私", ASSISTANT + "setting.activity.PrivacyActivity", scrolls=4)
    activity = ASSISTANT + "setting.activity.PersonalRecommendManageActivity"
    tap_page("个性化推荐", activity, scrolls=0)
    close_named(["热点资讯"], "负一屏·个性化推荐", activity, "个性化推荐", 2)


print(f"\n已回读确认 {VERIFIED_SWITCHES} 项；分段结果：{RESULTS}", flush=True)
print("录制时本机未安装游戏中心，未录入；通知渠道与组件挂起仍走 run.py 的独立流程。", flush=True)
print("乐划须先由机主在应用内关闭锁屏功能，再按本人意愿挂起；本脚本不动乐划。", flush=True)
