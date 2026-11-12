"""各系统广告 / 推荐入口速查：品牌家族 × 分组，按快慢排三档。

1. direct：直达页面（`am start -n 包名/页面`），不点菜单，最快。有的页面要裸启动、或者没导出、要权限，
   `note` 里写着；有的 App 只认公开 Intent（`am start -f 0x10008000 -a <action> -p 包名`），用 `Direct.action` 声明。
2. search：系统设置顶部搜索（`Phone.setting(关键词, 结果)`），只对系统设置里的项有用；搜到但点不跳的版本记在 `note`。
3. menu：人工路径，与 docs/清单 一致，前两档都不行时照它走。

「分组」是按开关归属分的一档（系统广告、应用商店、浏览器…），也是家族内的键（见 CONTEXT.md）；
机型脚本里 `@step` 的段落就是脚本覆盖到的那些分组，同名但覆盖面更小。

条目全部来自已有机型脚本与清单的实测记录：每条直达页面、每个搜索词都要在某个机型脚本里用过，
或在 docs/清单 里写着（tests/test_entries.py 守着）。哪些机型用过由 `used_by()` 从脚本现算，不在这里手写。
没有出处的不写进来：猜的包名、页面名会让引擎跳到别处。快应用不在这里——它按包名与设置项处理，
见 run.py 的 `QUICKAPP` 与 vivo 的 `switch_quick_app_service`，不走界面。
"""
import re
import shlex
from dataclasses import dataclass

import recipe_source

# 品牌（ro.product.brand 小写）→ 家族。run.py 的广告包、参考脚本与版本比较都用这一份，别再另建。
FAMILY = {
    "xiaomi": "xiaomi", "redmi": "xiaomi", "poco": "xiaomi",
    "oppo": "oppo", "oneplus": "oppo", "realme": "oppo",
    "vivo": "vivo", "iqoo": "vivo",
    "honor": "honor", "huawei": "huawei", "meizu": "meizu", "samsung": "samsung",
}

# 家族在文档里的写法。
LABEL = {"xiaomi": "小米", "oppo": "OPPO", "vivo": "vivo", "honor": "荣耀",
         "huawei": "华为", "meizu": "魅族", "samsung": "三星"}

# 没有主题商店的小米 / 红米机型上，主题管理包的代理页会被系统转去这两个包：应用商店详情页
# 或桌面。落在这里说明主题设置不可达，段体按跳过收尾（#902）。
THEME_DEAD_ENDS = frozenset({"com.xiaomi.market", "com.miui.home"})

# NEW_TASK | CLEAR_TASK，与 Launcher._launch 同值：直达与公开 Intent 都带它。
CLEAR_TASK = "0x10008000"

# ColorOS 商店 / 浏览器共用的公开设置 Intent。条目表与 used_by() 的源码扫描都取这一份，
# 改动作名时两边不会脱节（那边认不出就会静默少几台机）。
APP_SETTINGS_ACTION = "oppo.intent.action.APP_SETTINGS"


@dataclass(frozen=True)
class Direct:
    pkg: str
    activity: str               # 落点判据：前台应当是这一页
    expect: str = ""            # 落点判据：页面上应当出现的一段文字
    keep_task: bool = False     # 带清栈参数会把这一页顶掉，只能裸启动（ColorOS 17 浏览器设置页，#165）
    action: str = ""            # 公开 Intent：`am start -f 0x10008000 -a <action> -p <pkg>`（OPPO / 一加的设置页）


@dataclass(frozen=True)
class Search:
    keyword: str
    result: str                 # 搜索结果里要点的那一行标题
    path: str = ""              # 结果下一行的位置文字；同名结果有多条时按它挑


@dataclass(frozen=True)
class Entry:
    menu: str
    direct: tuple = ()
    search: tuple = ()
    app: str = ""               # 只能从 App 里走菜单时，先拉起的包
    note: str = ""


ENTRIES = {
    "xiaomi": {
        "系统广告": Entry(
            menu="设置 → 隐私与安全 →（OS3 先切「安全」标签）→ 更多安全设置 → 广告服务",
            direct=(Direct("com.android.settings", ".ad.AdServiceSettings", "个性化广告推荐"),),
            search=(Search("系统广告", "系统广告"),
                    Search("广告服务", "广告服务")),
            note="「系统工具广告」只在「系统广告」页，要搜「系统广告」进；Redmi K70（OS3.0.307）搜不到「广告服务」"),
        "应用商店": Entry(
            menu="应用商店 → 我的 → 设置（通知设置 / 隐私设置）",
            direct=(Direct("com.xiaomi.market", ".ui.MarketPreferenceActivity", ""),),
            app="com.xiaomi.market"),
        "手机管家": Entry(
            menu="手机管家 → 右上齿轮（隐私设置在设置页最底部）",
            direct=(Direct("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity", ""),)),
        "下载管理": Entry(
            menu="下载管理 → 右上「更多」→ 设置 → 信息流设置",
            direct=(Direct("com.android.providers.downloads.ui", ".activity.InfoFlowSettingActivity", "资源推荐"),),
            app="com.android.providers.downloads.ui"),
        "主题": Entry(
            menu="主题 → 我的 → 右上设置",
            direct=(Direct("com.android.thememanager", ".ThemeResourceProxyTabActivity", ""),),
            note="themestore 冷启动的重定向过渡窗会让前台校验误判，主题管理包的首页更稳（#906 起统一走这一条）"),
        "浏览器": Entry(
            menu="浏览器 → 底部「菜单」或「我的」→ 设置",
            direct=(Direct("com.android.browser", ".BrowserSettingsActivity", ""),
                    Direct("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity", "个性化推荐设置")),
            search=(Search("浏览器", "浏览器"),),
            note="个性化内容 / 广告推荐在独立页「个性化推荐设置」；「隐私和安全」在设置页最底部要滚"),
        "全局搜索": Entry(
            menu="桌面下滑 → 搜索页右上齿轮",
            direct=(Direct("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity", ""),),
            note="有的机型桌面下滑拉的是通知栏，用直达页"),
        "负一屏": Entry(
            menu="负一屏 → 设置 → 推荐卡片、热门活动；隐私设置 → 个性化推荐",
            direct=(Direct("com.miui.personalassistant", ".settings.PASettingActivity", ""),)),
        "天气和日历": Entry(
            menu="天气 → 右上「更多设置」→ 设置 → 用户体验计划；日历 → 右上「设置」→ 设置 → 用户体验计划",
            direct=(Direct("com.android.calendar", ".settings.UserExperienceActionBarActivity", ""),
                    Direct("com.android.calendar", ".settings.CalendarActionbarSettingsActivity",
                           "显示跨月日期")),
            app="com.miui.weather2",
            note="日历右上「更多」对读屏点击不响应，只能 input tap；"
                 "第二条直达是日历设置页本身，没有「用户体验计划」的版本（MIX Flip 2，#832）到此为止"),
    },
    "oppo": {
        "广告跟踪": Entry(
            menu="设置 → 隐私（ColorOS 17 叫「隐私与安全」）→ 设备标识与广告 → 广告跟踪",
            search=(Search("广告跟踪", "限制广告跟踪", path="隐私与安全 > 隐私 > 设备标识与广告"),
                    Search("设备标识与广告", "设备标识与广告")),
            note="ColorOS 17 用 oplus.intent.action.settings.MAIN_SEARCH 直接打开搜索页（Phone.setting 先试它）；"
                 "搜「广告跟踪」时点位置为「隐私与安全 > 隐私 > 设备标识与广告」的那条。部分版本搜得到但点结果不跳转，"
                 "这时走菜单。列表用右上菜单「全部关闭」整表关，「全部关闭」置灰即全部已关（PMX110，#650）"),
        "下拉搜索": Entry(
            menu="桌面中间向下滑 → 搜索页底部「设置」",
            direct=(Direct("com.heytap.quicksearchbox", ".ui.activity.SearchHomeActivity", ""),),
            note="SearchSettingActivity 未导出，只能直达搜索首页再点最靠下的「设置」；adb 下桌面下滑手势不稳"),
        "软件商店": Entry(
            menu="软件商店 → 我的 → 右上齿轮",
            direct=(Direct("com.heytap.market",
                           "com.heytap.market.mine.cn.setting.ui.SettingActivity",
                           action=APP_SETTINGS_ACTION),),
            app="com.heytap.market",
            note="公开设置 Intent 直接落到设置页，绕开含账号信息的「我的」页；PJA110 旧版商店的落点是 "
                 "`com.heytap.market.mine.ui.SettingActivity`（没有 `.cn.`），与本档不同，那条照菜单走"),
        "浏览器": Entry(
            menu="浏览器 → 底部 ☰ 或「我的」→ 设置",
            direct=(Direct("com.heytap.browser", ".settings.component.BrowserPreferencesPage",
                           action=APP_SETTINGS_ACTION),
                    Direct("com.heytap.browser", ".settings.component.BrowserPreferencesPage",
                           keep_task=True)),
            note="带清栈参数用 `-n` 启动会立刻退出，这一档只能裸 am start；首页切成「简洁」后没有「我的」和菜单（#165）"),
        "小布建议": Entry(
            menu="设置 → OPPO AI → 小布建议 → 资讯服务（「内容资讯」是分组标题，点不动）"),
        "负一屏": Entry(
            menu="桌面从偏左向右滑（最左边缘会拉出返回 / 侧边栏手势）→ 左上头像 → 设置",
            direct=(Direct("com.coloros.assistantscreen",
                           "com.oplus.assistantscreen.card.infoflow.setting.activity.InfoFlowSettingActivity", "热点资讯"),),
            note="设置页受 oppo.permission.OPPO_COMPONENT_SAFE 保护，am start 被拒，只能走手势；"
                 "其中「热点资讯」那一页有导出，可以直达（PMX110，#650）"),
        "主题商店": Entry(menu="主题商店 → 我的 → 右上设置", app="com.heytap.themestore",
                          note="设置页认 oppo.intent.action.APP_SETTINGS，直达"),
        "视频": Entry(menu="视频 → 我的 → 设置 → 个性化内容管理", app="com.heytap.yoli",
                      note="设置页没导出，深链 yoli://yoli.com/mine_act_lib_yoli/settings 直达（PMX110，#650）"),
        "游戏中心": Entry(menu="游戏中心 → 我的 → 设置 → 隐私开关设置 → 个性化推荐管理", app="com.nearme.gamecenter",
                          note="设置页认 oppo.intent.action.APP_SETTINGS，直达；设置页上的「隐私」是分组标题、点不动（PMX110，#650）"),
    },
    "vivo": {
        "系统广告": Entry(
            menu="设置 → 安全 → 更多安全设置 → 广告与隐私",
            direct=(Direct("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo", "智能推荐服务"),),
            search=(Search("广告与隐私", "广告与隐私"),),
            note="OriginOS 7 搜索结果点了直达；个性化广告、个性化推荐、智能推荐服务三个开关在同一页"),
        "阅图锁屏": Entry(
            menu="设置 → 桌面、锁屏与壁纸 → 锁屏设置 → 阅图锁屏",
            direct=(Direct("com.vivo.magazine", ".ui.MagazineSettings", ""),)),
        "全局搜索": Entry(
            menu="设置 → 系统管理与升级 → 全局搜索",
            direct=(Direct("com.vivo.globalsearch", ".view.SearchSettingsActivity", ""),)),
        "应用商店": Entry(
            menu="应用商店 → 我的 → 设置",
            direct=(Direct("com.bbk.appstore", ".ui.menu.AppstoreSettingsActivity", ""),),
            app="com.bbk.appstore",
            note="V2417A 上设置页未导出，冷启动可能落「月度精品」，先点「进入首页」"),
        "i管家": Entry(
            menu="i 管家 → 设置 → 关于 → 个性化设置",
            direct=(Direct("com.iqoo.secure", ".MainSettings", ""),),
            note="首屏体检动画期间点「设置」会被吞"),
        "天气": Entry(
            menu="天气 → 设置（齿轮或右上「更多 → 设置」）→ 天气服务",
            direct=(Direct("com.vivo.weather", ".WeatherSettings", ""),)),
        "浏览器": Entry(menu="浏览器 → 我的 → 齿轮", app="com.vivo.browser"),
        "负一屏": Entry(
            menu="桌面从中间向右滑（最左边缘会拉出侧边栏）→ 右上齿轮 → 更多设置 → 个性化推荐",
            note="设置页未导出，只能走手势"),
    },
    "honor": {
        "广告跟踪": Entry(
            menu="设置 → 搜索「广告」→ 广告与隐私",
            direct=(Direct("com.hihonor.id", ".oaid.ui.AdvertisingPrivacyActivity", "应用广告跟踪管理"),),
            search=(Search("广告", "广告与隐私"),)),
        "智能推荐服务": Entry(
            menu="设置 → 搜索「广告」→ 广告与隐私 → 智能推荐服务",
            direct=(Direct("com.hihonor.id", ".oaid.ui.IntelligentRecommendActivity", ""),)),
        "YOYO": Entry(
            menu="设置 → 搜索「新闻资讯」",
            search=(Search("新闻资讯", "新闻资讯"),)),
        "魔法画报": Entry(
            menu="设置 → 搜索「杂志」→ 魔法画报",
            search=(Search("杂志", "魔法画报"), Search("画报", "魔法画报"))),
        "桌面文件夹": Entry(
            menu="打开文件夹 → 底部「更多推荐」→ 设置；「热门推荐」文件夹 → 设置",
            direct=(Direct("com.hihonor.appmarket", ".module.topapps.TopAppsSettingActivity", ""),
                    Direct("com.hihonor.appmarket", ".popularapps.activity.PopularAppsSettingActivity", ""))),
        "系统管家": Entry(
            menu="系统管家 → 右上齿轮",
            direct=(Direct("com.hihonor.systemmanager", ".mainscreen.SettingActivity", ""),)),
        "视频": Entry(
            menu="视频 → 设置 → 其他设置",
            direct=(Direct("com.hihonor.youku.video", "com.youku.android.youkusetting.activity.SettingsActivity", ""),)),
        "下拉搜索": Entry(
            menu="桌面中间向下滑 → 按返回收起键盘 → 搜索框旁「更多」→ 设置",
            direct=(Direct("com.hihonor.search", ".feature.mainpage.presentation.page.HomeActivity", "更多"),),
            note="SearchSettingActivity 未导出，只能直达搜索首页再点「更多 → 设置」；主屏上键盘盖着「更多」，先按返回收起"),
        "负一屏": Entry(
            menu="桌面从左边缘向右滑 → 头像 → 设置",
            direct=(Direct("com.hihonor.hiboard", "com.hihonor.intelligent.LauncherActivity", "头像"),),
            note="直达的是负一屏首页，设置入口在右上「头像」；后台屏上没有负一屏（CLE-AN00）"),
        "应用市场": Entry(menu="应用市场 → 我的 → 设置", app="com.hihonor.appmarket"),
        "浏览器": Entry(menu="经典首页：我的 → 右上第三个图标；简洁首页：更多 → 设置", app="com.hihonor.baidu.browser"),
        "主题": Entry(menu="主题 → 我的 → 设置", app="com.hihonor.android.thememanager"),
        "音乐": Entry(menu="音乐 → 我的 → 右上齿轮 → 更多设置", app="com.hihonor.cloudmusic"),
        "阅读": Entry(menu="阅读 → 我的 → 更多设置", app="com.hihonor.dz.reader"),
    },
    "huawei": {
        "系统广告": Entry(menu="设置 → 隐私 → 华为广告 → 智能推荐服务"),
        "跟踪管理": Entry(menu="设置 → 隐私 → 跟踪管理 → 允许全部应用跟踪"),
    },
    "meizu": {
        "系统跟踪": Entry(menu="设置 → 权限和隐私 → 应用跟踪控制"),
        "全局搜索": Entry(menu="全局搜索 → 设置"),
        "浏览器": Entry(menu="浏览器 → 工具 → 设置"),
        "应用商店": Entry(menu="应用商店 → 我的 → 设置 → 个性化推荐"),
        "主题美化": Entry(menu="主题美化 → 头像 → 设置 → 个性化推荐"),
        "天气": Entry(menu="天气 → 更多选项 → 设置"),
        "手机管家": Entry(menu="手机管家 → 设置"),
        "锁屏画报": Entry(menu="主题美化 → 头像 → 锁屏画报 → 设置 → 个性化推荐"),
    },
    "samsung": {
        "系统广告": Entry(
            menu="Google 广告设置 → 选择停用广告个性化功能（点整行标题，弹确认后点「确定」）",
            direct=(Direct("com.google.android.gms", ".adid.settings.AdsSettingsActivity", "广告"),),
            note="点开关圆点不弹框也不改状态，必须点整行标题；关掉后广告 ID 变全零"),
        "应用商店": Entry(
            menu="Galaxy 应用商店 → 侧边菜单 → 设置（齿轮）→ 允许使用个人信息 / 获取新闻和特惠",
            note="设置齿轮与账号按钮只隔 28px，按文字点击会命中账号页；启动弹窗点「取消」后仍会自更新"),
        "通知渠道": Entry(
            menu="设置 → 应用程序通知 → 选择应用 → 通知类别 → 分组名 → 渠道名",
            note="One UI 4 首层没有渠道行，chan-off 停在这一层报「同名 0 行」，只能照清单手动关"),
    },
}


def family(brand):
    return FAMILY.get((brand or "").strip().lower(), "")


def lookup(brand, group):
    """这台手机的品牌在某个分组的入口；没有记录返回 None。"""
    return ENTRIES.get(family(brand), {}).get(group)


def full(pkg, activity):
    """「.ad.AdServiceSettings」与「com.android.settings.ad.AdServiceSettings」是同一页。"""
    return pkg + activity if activity.startswith(".") else activity


def start_command(d, wait=False):
    """这一档在手机上执行的拉起命令。Intent 档（`d.action`）指定包，其余指定页面；
    `keep_task` 的页面带清栈参数会立刻退出，只能裸启动（#165）。`wait` 给 `adapt survey` 加 `-W`。"""
    flags = " -W" if wait else ""
    if d.action:
        return f"am start{flags} -f {CLEAR_TASK} -a {d.action} -p {d.pkg}"
    page = d.pkg + "/" + full(d.pkg, d.activity)
    if d.keep_task:
        return f"am start{flags} -n {shlex.quote(page)}"
    return f"am start{flags} -f {CLEAR_TASK} -n {shlex.quote(page)}"


def describe(d):
    """入口速查里怎么写这一档：直达写页面，Intent 档写拉起命令再把落点跟在后面。"""
    if d.action:
        return f"`{start_command(d)}` 落 `{d.pkg}/{d.activity}`"
    return f"`{d.pkg}/{d.activity}`"


def source_key(d):
    """这一档在 `used_by()` 里的键。Intent 档按「动作 + 包」认：同一个页面有两条走法时，
    各自算各自的出处与提速提示。"""
    if d.action:
        return ("intent", d.action, d.pkg)
    return ("direct", d.pkg, full(d.pkg, d.activity))


# 一条拉起命令里的页面与公开 Intent：脚本里的几种写法（字面量、拼接变量、模板常量的
# `.format(…)`）由事实层先把字符串还原出来，这里只认还原后的整条命令。
_AM_PAGE = re.compile(r"am start\b[^\n]*?-n\s+([\w.]+)/([\w.$]+)")
_AM_INTENT = re.compile(r"am start\b[^\n]*?-a\s+([\w.]+)[^\n]*?-p\s+([\w.]+)")
# 拉起入口的调用名：Phone.start 与共享的 start_or_skip 助手（沿用 #902）。
_START_CALLS = frozenset({"p.start", "start_or_skip"})


def _value(arg):
    """一个实参解析出的单个取值。入口这一侧不复刻旧的形参回填：形参实参算未解析（#1197 接线口径）。"""
    if arg is None or arg.param is not None or not arg.values:
        return None
    return arg.values[0].text


def _arg_of(call, index, keyword=None):
    """第 index 个位置实参；不够时退回同名关键字实参（`p.start(pkg, activity=…)`）。

    `keyword is None` 时不做关键字回退：位置实参的 `keyword` 也是 None，回退会把它自己
    当成第二个实参，单实参的调用就凭空多出一档入口。"""
    positional = [arg for arg in call.args if arg.keyword is None]
    if index < len(positional):
        return positional[index]
    if keyword is None:
        return None
    for arg in call.args:
        if arg.keyword == keyword:
            return arg
    return None


def _scan_command(text, model, found):
    """一条已还原的拉起命令里的入口：`-n 包名/页面` 记直达，`-a 动作 … -p 包名` 记公开 Intent。"""
    for m in _AM_PAGE.finditer(text):
        found.setdefault(("direct", m.group(1), full(m.group(1), m.group(2))), set()).add(model)
    for m in _AM_INTENT.finditer(text):
        found.setdefault(("intent", m.group(1), m.group(2)), set()).add(model)


def _scan_entries(facts, model, found):
    """从一份事实里认出这台机用过的入口：脚本自身的源码，或它调用到的注入面实现。"""
    for call in facts.calls:
        if call.name in _START_CALLS:
            pkg, act = _value(_arg_of(call, 0)), _value(_arg_of(call, 1, "activity"))
            if pkg and act:
                found.setdefault(("direct", pkg, full(pkg, act)), set()).add(model)
        elif call.name == "p.setting":
            keyword = _value(_arg_of(call, 0))
            if keyword:
                found.setdefault(("search", keyword, _value(_arg_of(call, 1)) or keyword),
                                 set()).add(model)
        elif call.name == "open_app_settings":
            pkg, page = _value(_arg_of(call, 0)), _value(_arg_of(call, 1))
            if pkg and page:
                found.setdefault(("intent", APP_SETTINGS_ACTION, pkg), set()).add(model)
        for arg in call.args:
            for item in arg.values:
                _scan_command(item.text, model, found)


def _bindings(calls):
    """脚本调注入助手时按位置传的实参：实参在脚本里、形参在实现里，事实层按位置把两侧合起来。"""
    out = {}
    for call in calls:
        for index, arg in enumerate(arg for arg in call.args if arg.keyword is None):
            if arg.param is None and arg.values:
                out.setdefault(index, []).extend(item.text for item in arg.values)
    return {index: tuple(texts) for index, texts in out.items()}


def used_by(recipes_dir):
    """{("direct", 包名, 完整页面名) 或 ("intent", 动作, 包名) 或 ("search", 关键词, 结果): {机型型号}}，
    从机型脚本源码现算。

    `p.start(package, ".X")` 这种先赋值再传变量的写法也要认出来：honor-WKL-AN20 就是这么写的，
    只认字面量会把它的机型漏掉（生成表里「用过的机型」少一台）。经共享入口助手
    `start_or_skip(package, ".X", …)` 拉起的那几条同样是这台机用过的直达（#902）。
    `am start -a <action> -p <包名>` 这类公开 Intent 入口单记一档（#956）；
    经 `open_app_settings(包名, 页面, …)` 打开的那一类同样是直达（它包着 APP_SETTINGS 的 Intent）。

    搬进注入面（`tool/recipe_nav.py` 与 `tool/recipe_steps.py`）的实现，入口写在实现里、脚本只剩
    一行调用：脚本调用了哪个注入名，就把那份实现也扫一遍，否则「用过的机型」会静默漏掉（沿用 #1153 的做法）。
    包名这类实参仍在脚本里（`app_settings(MARKET)`），形参在实现里，按位置把两侧合起来才还原得出
    包名（沿用 #1154 的做法）；段体按名字取的模块常量以 `externals` 交回去（#1209）。定义了本地
    同名实现的脚本走本地那份，不扫注入版（`injected_calls()` 判这一条）。

    命令串只从调用的实参里取：变量、拼接与模板常量都还原得到，没被任何调用引用的字符串常量不算
    出处；语法错的脚本经事实层直接抛 `SyntaxError`，不再静默少算（沿用 #1195 的口径）。

    只认字面量：经 `reach(p, ENTRIES[...])` 消费的那几条（浏览器段，#912）看不出来，
    这张表会把用得上的机型算成没用过。"""
    injected = recipe_source.injected_sources()
    found = {}
    for rel, facts in recipe_source.scan_dir(recipes_dir).items():
        model = rel.split("/", 1)[0].split("-", 1)[-1]
        _scan_entries(facts, model, found)
        for name, impl in injected.items():
            calls = recipe_source.injected_calls(facts, name)
            if calls:
                _scan_entries(recipe_source.scan_source(impl, _bindings(calls),
                                                        externals=facts.constants), model, found)
    return found


def open_direct(p, d, settle=1.2):
    """打开一条直达页面。默认走 Phone.start（顺手收掉开屏 / 权限弹窗、核对前台）；
    Intent 档与带清栈参数就会自己退出的页面（`keep_task`）裸启动，失败时照样抛出。
    打不开由 reach() 记一笔换下一档。

    页面名按字面量传下去：走 `Phone.start` 的那条由 `Launcher._launch` 在 shell 边界引用一次，
    这里再 quote 一层会让 used_by() 的源码扫描认不出机型（#667）；裸启动那两条不经
    `Phone.start`，引用由 `start_command()` 做。"""
    if not d.action and not d.keep_task:
        p.start(d.pkg, d.activity, settle=settle)
        return
    page = full(d.pkg, d.activity)
    result = p.reader.shell(start_command(d))
    if getattr(result, "exit_code", 0) or re.search(r"Error|Exception", result.output or "", re.I):
        raise RuntimeError(f"无法打开 {page}：{(result.output or '').strip()[-200:]}")


def landed(p, d):
    """前台是不是就是这一页：包名与页面名都要对上。只比类名尾段会让别的 App 的同名页面命中，
    22 条直达里 20 条只有这一条判据。"""
    focus = p.focus() or ""
    if "/" not in focus:
        return False
    got_pkg, got_act = focus.split("/", 1)
    got_act = full(got_pkg, got_act) if got_act.startswith(".") else got_act
    return got_pkg.lower() == d.pkg.lower() and got_act.lower() == full(d.pkg, d.activity).lower()


def reach(p, entry, log=print, now=None, sleep=None, settle=1.2, allow_search=True):
    """按快慢依次试：直达页面 → 设置搜索。到了返回用的是哪一档（"direct" / "search"），都不行返回 None，
    由调用方照 `entry.menu` 走菜单或跳过。`now` / `sleep` / `settle` 给测试换掉真实等待。

    `allow_search=False` 只试直达档：设置搜索会把设备交给系统设置（另一个 App 的搜索页），
    入口必须留在本 App 里的分组（浏览器段，#912）搜到了也是错的地方。"""
    import time
    import wait

    now = now or time.time
    sleep = sleep or time.sleep
    for d in entry.direct:
        where = start_command(d) if d.action else full(d.pkg, d.activity)
        try:
            open_direct(p, d, settle=settle)
        except Exception as e:
            import adb_link
            # 断线不是「这一档不通」：换下一档只会接着错。读屏抛的原始异常不一定转成 DeviceLost，
            # 但 _u2 会把 Phone.lost 置位，一并认。
            if isinstance(e, adb_link.DeviceLost) or p.lost:
                raise
            log(f"  · 直达 {where} 打不开（{e}），换下一档")
            continue
        ok = wait.until(lambda: landed(p, d), timeout=4, poll=0.2, now=now, sleep=sleep)  # noqa: B023 - d 当轮创建当轮消费，until 同步轮询
        if ok and (not d.expect or p.expect_page(d.expect, 3)):
            return "direct"
        log(f"  · 直达 {where} 没落在这一页，换下一档")
    if not allow_search:
        return None
    for s in entry.search:
        extra = {"path": s.path} if s.path else {}
        if p.setting(s.keyword, s.result, **extra):
            return "search"
    return None


def speedups(recipes_dir):
    """同家族有机型的脚本用过这条直达、另一些机型的脚本没有：[(家族, 分组, 没用的机型, 直达)]。
    只是提示：没走这条直达可能是页面没导出、版本不同或者没装这个 App，不算缺陷。"""
    import glob, os
    models = {}
    for f in glob.glob(os.path.join(recipes_dir, "*", "recipe*.py")):
        brand, _, model = os.path.basename(os.path.dirname(f)).partition("-")
        if brand.lower() in FAMILY:
            models.setdefault(FAMILY[brand.lower()], set()).add(model)
    used = used_by(recipes_dir)
    out = []
    for fam, groups in ENTRIES.items():
        for name, e in groups.items():
            for d in e.direct:
                proven = used.get(source_key(d), set()) & models.get(fam, set())
                if proven and models[fam] - proven:
                    out.append((fam, name, sorted(models[fam] - proven), d))
    return out


def markdown(recipes_dir):
    """docs/清单/入口速查.md 的全文：每个家族一张表，一个分组一行，表尾是可提速提示。"""
    used = used_by(recipes_dir)
    lines = ["# 入口速查：广告与推荐开关在哪", "",
             "由 `tool/entries.py` 生成（`python3 tool/entries.py > docs/清单/入口速查.md`），不要手改。",
             "每个分组按快慢排三档：**直达**（页面或公开 Intent，不点菜单）→ **设置搜索**（系统设置顶部搜索框）→ **菜单路径**。",
             "「用过的机型」从机型脚本里现算；没写机型的条目出自同品牌的手动清单。快应用按包名处理，不在这张表里。", ""]
    for fam, groups in ENTRIES.items():
        brands = "、".join(b for b, f in FAMILY.items() if f == fam)
        lines += [f"## {LABEL.get(fam, fam)}（{brands}）", "",
                  "| 分组 | 直达 | 设置搜索 | 菜单路径 | 注意 |", "|---|---|---|---|---|"]
        for name, e in groups.items():
            cells = []
            for d in e.direct:
                models = used.get(source_key(d))
                cells.append(describe(d) + (f"（{'、'.join(sorted(models))}）" if models else ""))
            direct = "<br>".join(cells) or "—"
            search = "<br>".join(
                f"搜「{s.keyword}」点「{s.result}」" + (f"（位置：{s.path}）" if s.path else "")
                + (f"（{'、'.join(sorted(used.get(('search', s.keyword, s.result), ())))}）"
                   if used.get(("search", s.keyword, s.result)) else "")
                for s in e.search) or "—"
            menu = e.menu + (f"（先拉起 `{e.app}`）" if e.app else "")
            lines.append(f"| {name} | {direct} | {search} | {menu} | {e.note or ''} |")
        lines.append("")
    lines += ["## 可提速提示", "",
              "同家族里有机型的脚本用过这条直达，下面这些机型的脚本还没有。脚本未走这条直达 ≠ 缺陷："
              "页面可能没导出、版本不同或者没装这个 App，要换先真机试。", ""]
    lines += [f"- {LABEL.get(fam, fam)} / {name} / {'、'.join(missing)} / {describe(d)}"
              for fam, name, missing, d in speedups(recipes_dir)]
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import os
    print(markdown(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")), end="")
