"""各系统广告 / 推荐开关的入口速查：品牌家族 × 段落，按快慢排三档。

1. direct：直达页面（`am start -n 包名/页面`），不点菜单，最快。有的页面没导出、或要权限，`note` 里写着。
2. search：系统设置顶部搜索（`Phone.setting(关键词, 结果)`），只对系统设置里的项有用；搜到但点不跳的版本记在 `note`。
3. menu：人工路径，与 docs/清单 一致，前两档都不行时照它走。

条目全部来自已有机型脚本与清单的实测记录：每条直达页面、搜索词都要在某个机型脚本里用过，
或在 docs/清单 里写着（tests/test_entries.py 守着）。哪些机型用过由 `used_by()` 从脚本现算，不在这里手写。
没有出处的不写进来：猜的包名、页面名会让引擎跳到别处。快应用不在这里——它按包名与设置项处理，
见 run.py 的 `QUICKAPP` 与 vivo 的 `switch_quick_app_service`，不走界面。
"""
from dataclasses import dataclass

# 品牌（ro.product.brand 小写）→ 家族。子品牌各自列出，免得漏（REDMI、POCO、iQOO、一加、真我）
FAMILY = {
    "xiaomi": "小米", "redmi": "小米", "poco": "小米",
    "oppo": "OPPO", "oneplus": "OPPO", "realme": "OPPO",
    "vivo": "vivo", "iqoo": "vivo",
    "honor": "荣耀",
    "huawei": "华为",
    "meizu": "魅族",
}


@dataclass(frozen=True)
class Direct:
    pkg: str
    activity: str
    expect: str = ""            # 落点判据：页面上应当出现的一段文字


@dataclass(frozen=True)
class Search:
    keyword: str
    result: str                 # 搜索结果里要点的那一行标题


@dataclass(frozen=True)
class Entry:
    menu: str
    direct: tuple = ()
    search: tuple = ()
    app: str = ""               # 只能从 App 里走菜单时，先拉起的包
    note: str = ""


ENTRIES = {
    "小米": {
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
            app="com.android.providers.downloads.ui"),
        "主题": Entry(
            menu="主题 → 我的 → 右上设置",
            direct=(Direct("com.android.thememanager", ".ThemeResourceProxyTabActivity", ""),
                    Direct("com.miui.themestore", "com.miui.thememanagerstore.ThemeResourceTabActivity", "")),
            note="themestore 冷启动的重定向过渡窗会让前台校验误判，主题管理包的首页更稳"),
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
            direct=(Direct("com.android.calendar", ".settings.UserExperienceActionBarActivity", ""),),
            app="com.miui.weather2",
            note="日历右上「更多」对读屏点击不响应，只能 input tap"),
    },
    "OPPO": {
        "广告跟踪": Entry(
            menu="设置 → 隐私（ColorOS 17 叫「隐私与安全」）→ 设备标识与广告 → 广告跟踪",
            search=(Search("设备标识与广告", "设备标识与广告"),),
            note="部分版本搜得到但点结果不跳转（停在首页弹「取消」），这时走菜单"),
        "下拉搜索": Entry(
            menu="桌面中间向下滑 → 搜索页底部「设置」",
            direct=(Direct("com.heytap.quicksearchbox", ".ui.activity.SearchHomeActivity", ""),),
            note="SearchSettingActivity 未导出，只能直达搜索首页再点最靠下的「设置」；adb 下桌面下滑手势不稳"),
        "软件商店": Entry(
            menu="软件商店 → 我的 → 右上齿轮",
            app="com.heytap.market"),
        "浏览器": Entry(
            menu="浏览器 → 底部 ☰ 或「我的」→ 设置",
            direct=(Direct("com.heytap.browser", ".settings.component.BrowserPreferencesPage", ""),)),
        "小布建议": Entry(
            menu="设置 → OPPO AI → 小布建议 → 资讯服务（「内容资讯」是分组标题，点不动）"),
        "负一屏": Entry(
            menu="桌面从左边缘向右滑 → 左上头像 → 设置",
            note="设置页受 oppo.permission.OPPO_COMPONENT_SAFE 保护，am start 被拒，只能走手势"),
        "主题商店": Entry(menu="主题商店 → 我的 → 右上设置", app="com.heytap.themestore"),
        "视频": Entry(menu="视频 → 我的 → 设置 → 个性化内容管理", app="com.heytap.yoli"),
        "游戏中心": Entry(menu="游戏中心 → 我的 → 设置 → 隐私开关设置 → 个性化推荐管理", app="com.nearme.gamecenter"),
    },
    "vivo": {
        "系统广告": Entry(
            menu="设置 → 安全 → 更多安全设置 → 广告与隐私",
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
    "荣耀": {
        "广告跟踪": Entry(
            menu="设置 → 搜索「广告」→ 广告与隐私",
            search=(Search("广告", "广告与隐私"),)),
        "智能推荐服务": Entry(
            menu="（清单只记了直达页面）",
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
        "下拉搜索": Entry(menu="桌面中间向下滑 → 按返回收起键盘 → 搜索框旁「更多」→ 设置"),
        "负一屏": Entry(menu="桌面从左边缘向右滑 → 头像 → 设置"),
        "应用市场": Entry(menu="应用市场 → 我的 → 设置", app="com.hihonor.appmarket"),
        "浏览器": Entry(menu="经典首页：我的 → 右上第三个图标；简洁首页：更多 → 设置", app="com.hihonor.baidu.browser"),
        "主题": Entry(menu="主题 → 我的 → 设置", app="com.hihonor.android.thememanager"),
        "音乐": Entry(menu="音乐 → 我的 → 右上齿轮 → 更多设置", app="com.hihonor.cloudmusic"),
        "阅读": Entry(menu="阅读 → 我的 → 更多设置", app="com.hihonor.dz.reader"),
    },
    "华为": {
        "系统广告": Entry(menu="设置 → 隐私 → 华为广告 → 智能推荐服务"),
        "跟踪管理": Entry(menu="设置 → 隐私 → 跟踪管理 → 允许全部应用跟踪"),
    },
    "魅族": {
        "系统跟踪": Entry(menu="设置 → 权限和隐私 → 应用跟踪控制"),
        "全局搜索": Entry(menu="全局搜索 → 设置"),
        "浏览器": Entry(menu="浏览器 → 工具 → 设置"),
        "应用商店": Entry(menu="应用商店 → 我的 → 设置 → 个性化推荐"),
        "主题美化": Entry(menu="主题美化 → 头像 → 设置 → 个性化推荐"),
        "天气": Entry(menu="天气 → 更多选项 → 设置"),
        "手机管家": Entry(menu="手机管家 → 设置"),
        "锁屏画报": Entry(menu="主题美化 → 头像 → 锁屏画报 → 设置 → 个性化推荐"),
    },
}


def family(brand):
    return FAMILY.get((brand or "").strip().lower(), "")


def lookup(brand, section):
    """这台手机的品牌在某一段的入口；没有记录返回 None。"""
    return ENTRIES.get(family(brand), {}).get(section)


def full(pkg, activity):
    """「.ad.AdServiceSettings」与「com.android.settings.ad.AdServiceSettings」是同一页。"""
    return pkg + activity if activity.startswith(".") else activity


def used_by(recipes_dir):
    """{("direct", 包名, 完整页面名) 或 ("search", 关键词, 结果): {机型型号}}，从机型脚本源码现算。"""
    import glob, os, re
    found = {}
    for f in glob.glob(os.path.join(recipes_dir, "*", "recipe*.py")):
        model = os.path.basename(os.path.dirname(f)).split("-", 1)[-1]
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        for m in re.finditer(r'p\.start\(\s*"([\w.]+)"\s*,\s*"([\w.$]+)"', src):
            found.setdefault(("direct", m.group(1), full(m.group(1), m.group(2))), set()).add(model)
        for m in re.finditer(r'am start[^"\']*?-n\s+([\w.]+)/([\w.$]+)', src):
            found.setdefault(("direct", m.group(1), full(m.group(1), m.group(2))), set()).add(model)
        for m in re.finditer(r'p\.setting\(\s*"([^"]+)"(?:\s*,\s*"([^"]+)")?', src):
            found.setdefault(("search", m.group(1), m.group(2) or m.group(1)), set()).add(model)
    return found


def reach(p, entry, log=print):
    """按快慢依次试：直达页面 → 设置搜索。到了返回用的是哪一档（"direct" / "search"），都不行返回 None，
    由调用方照 `entry.menu` 走菜单或跳过。直达页面要焦点落在那一页上才算；给了 `expect` 还要看见那段文字。"""
    import time
    import wait

    for d in entry.direct:
        page = full(d.pkg, d.activity)
        out = p.reader.shell(f"am start -f 0x10008000 -n {d.pkg}/{page}").output
        if "Error" in out or "Exception" in out:
            log(f"  · 直达 {page} 打不开，换下一档")
            continue
        landed = wait.until(lambda: page.rsplit(".", 1)[-1] in p.focus(), timeout=4, poll=0.2,
                            now=time.time, sleep=time.sleep)
        if landed and (not d.expect or p.expect_page(d.expect, 3)):
            return "direct"
        log(f"  · 直达 {page} 没落在设置页，换下一档")
    for s in entry.search:
        if p.setting(s.keyword, s.result):
            return "search"
    return None


def markdown(recipes_dir):
    """docs/清单/入口速查.md 的全文：每个家族一张表，一段一行。"""
    used = used_by(recipes_dir)
    lines = ["# 入口速查：广告与推荐开关在哪", "",
             "由 `tool/entries.py` 生成（`python3 tool/entries.py > docs/清单/入口速查.md`），不要手改。",
             "每一段按快慢排三档：**直达页面**（不点菜单）→ **设置搜索**（系统设置顶部搜索框）→ **菜单路径**。",
             "「用过的机型」从机型脚本里现算；没写机型的条目出自同品牌的手动清单。快应用按包名处理，不在这张表里。", ""]
    for fam, sections in ENTRIES.items():
        brands = "、".join(b for b, f in FAMILY.items() if f == fam)
        lines += [f"## {fam}（{brands}）", "", "| 段落 | 直达页面 | 设置搜索 | 菜单路径 | 注意 |", "|---|---|---|---|---|"]
        for name, e in sections.items():
            direct = "<br>".join(
                f"`{d.pkg}/{d.activity}`" + (f"（{'、'.join(sorted(used.get(('direct', d.pkg, full(d.pkg, d.activity)), ())))}）"
                                              if used.get(("direct", d.pkg, full(d.pkg, d.activity))) else "")
                for d in e.direct) or "—"
            search = "<br>".join(
                f"搜「{s.keyword}」点「{s.result}」" + (f"（{'、'.join(sorted(used.get(('search', s.keyword, s.result), ())))}）"
                                                    if used.get(("search", s.keyword, s.result)) else "")
                for s in e.search) or "—"
            menu = e.menu + (f"（先拉起 `{e.app}`）" if e.app else "")
            lines.append(f"| {name} | {direct} | {search} | {menu} | {e.note or ''} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import os
    print(markdown(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")), end="")
