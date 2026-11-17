"""entries 族的用例表（#1401）：入口速查表的一行一条，共 54 条。

每行是 `entries.ENTRIES` 里的一行入口，id 写成 `<family>/<group>`，与家族、分组的人读写法对得上。
这些行原先被 `test_every_entry_has_a_source` 的双层循环逐行扫过，owner 是票号；现在 owner 是它依赖的
那一行入口，行退场，case 跟着退场。

句柄（`handles`）从 case 自己的 `family` / `group` 现算，不写字符串字面量——手写的句柄等于给入口表
造第二个 owner。`structure()` 与 `expected()` 都从 `entries.ENTRIES` 现算：前者让「case 指向的表行
已不存在」显形，后者让「表新增一行却没有配套 case」显形。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import entries  # noqa: E402

from family import Family, cli  # noqa: E402

CASES = [
    {"id": "xiaomi/系统广告", "family": "xiaomi", "group": "系统广告"},
    {"id": "xiaomi/应用商店", "family": "xiaomi", "group": "应用商店"},
    {"id": "xiaomi/手机管家", "family": "xiaomi", "group": "手机管家"},
    {"id": "xiaomi/下载管理", "family": "xiaomi", "group": "下载管理"},
    {"id": "xiaomi/主题", "family": "xiaomi", "group": "主题"},
    {"id": "xiaomi/浏览器", "family": "xiaomi", "group": "浏览器"},
    {"id": "xiaomi/全局搜索", "family": "xiaomi", "group": "全局搜索"},
    {"id": "xiaomi/负一屏", "family": "xiaomi", "group": "负一屏"},
    {"id": "xiaomi/天气和日历", "family": "xiaomi", "group": "天气和日历"},
    {"id": "oppo/广告跟踪", "family": "oppo", "group": "广告跟踪"},
    {"id": "oppo/下拉搜索", "family": "oppo", "group": "下拉搜索"},
    {"id": "oppo/软件商店", "family": "oppo", "group": "软件商店"},
    {"id": "oppo/浏览器", "family": "oppo", "group": "浏览器"},
    {"id": "oppo/小布建议", "family": "oppo", "group": "小布建议"},
    {"id": "oppo/负一屏", "family": "oppo", "group": "负一屏"},
    {"id": "oppo/主题商店", "family": "oppo", "group": "主题商店"},
    {"id": "oppo/视频", "family": "oppo", "group": "视频"},
    {"id": "oppo/游戏中心", "family": "oppo", "group": "游戏中心"},
    {"id": "vivo/系统广告", "family": "vivo", "group": "系统广告"},
    {"id": "vivo/阅图锁屏", "family": "vivo", "group": "阅图锁屏"},
    {"id": "vivo/全局搜索", "family": "vivo", "group": "全局搜索"},
    {"id": "vivo/应用商店", "family": "vivo", "group": "应用商店"},
    {"id": "vivo/i管家", "family": "vivo", "group": "i管家"},
    {"id": "vivo/天气", "family": "vivo", "group": "天气"},
    {"id": "vivo/浏览器", "family": "vivo", "group": "浏览器"},
    {"id": "vivo/负一屏", "family": "vivo", "group": "负一屏"},
    {"id": "honor/广告跟踪", "family": "honor", "group": "广告跟踪"},
    {"id": "honor/智能推荐服务", "family": "honor", "group": "智能推荐服务"},
    {"id": "honor/YOYO", "family": "honor", "group": "YOYO"},
    {"id": "honor/魔法画报", "family": "honor", "group": "魔法画报"},
    {"id": "honor/桌面文件夹", "family": "honor", "group": "桌面文件夹"},
    {"id": "honor/系统管家", "family": "honor", "group": "系统管家"},
    {"id": "honor/视频", "family": "honor", "group": "视频"},
    {"id": "honor/下拉搜索", "family": "honor", "group": "下拉搜索"},
    {"id": "honor/负一屏", "family": "honor", "group": "负一屏"},
    {"id": "honor/应用市场", "family": "honor", "group": "应用市场"},
    {"id": "honor/浏览器", "family": "honor", "group": "浏览器"},
    {"id": "honor/主题", "family": "honor", "group": "主题"},
    {"id": "honor/音乐", "family": "honor", "group": "音乐"},
    {"id": "honor/阅读", "family": "honor", "group": "阅读"},
    {"id": "huawei/系统广告", "family": "huawei", "group": "系统广告"},
    {"id": "huawei/跟踪管理", "family": "huawei", "group": "跟踪管理"},
    {"id": "meizu/系统跟踪", "family": "meizu", "group": "系统跟踪"},
    {"id": "meizu/全局搜索", "family": "meizu", "group": "全局搜索"},
    {"id": "meizu/浏览器", "family": "meizu", "group": "浏览器"},
    {"id": "meizu/应用商店", "family": "meizu", "group": "应用商店"},
    {"id": "meizu/主题美化", "family": "meizu", "group": "主题美化"},
    {"id": "meizu/天气", "family": "meizu", "group": "天气"},
    {"id": "meizu/手机管家", "family": "meizu", "group": "手机管家"},
    {"id": "meizu/锁屏画报", "family": "meizu", "group": "锁屏画报"},
    {"id": "samsung/系统广告", "family": "samsung", "group": "系统广告"},
    {"id": "samsung/应用商店", "family": "samsung", "group": "应用商店"},
    {"id": "samsung/通知渠道", "family": "samsung", "group": "通知渠道"},
    {"id": "freeme/安全管家", "family": "freeme", "group": "安全管家"},
]


def handles(case):
    """这条 case 依赖的入口表行，从它自己的 `family` / `group` 现算。"""
    return [(case["family"], case["group"])]


def structure():
    """当前存在的全部入口表行：`(家族, 分组)`。"""
    return {(family_name, group_name)
            for family_name, groups in entries.ENTRIES.items()
            for group_name in groups}


def expected():
    """入口表有几行，就该有几条 case：新增一行入口会要求配套 case。"""
    return structure()


FAMILY = Family("entries-source-rows", CASES, handles=handles, structure=structure,
                expected=expected)

if __name__ == "__main__":
    sys.exit(cli())
