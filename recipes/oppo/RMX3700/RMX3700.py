# realme GT Neo5 SE（RMX3700，ColorOS 16）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 只剩软件商店在这里：它是四层嵌套的条件树（tap_by_scroll / wait_page / store_privacy 逐层判），
# 按 docs/04「多层嵌套的整段交给例外函数」留下。其余五段（落点断言 + 一层失败退出）已落数据。
import time

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, rt, skip, skip_in_safe_mode
    from recipe_nav import open_search_setting, open_search_sub, settings_page, tap_by_scroll, wait_page
    from recipe_strategies import close_rows

BUILD = "RMX3700_16.0.5.1300"
# 家族库按这些常量选走法（#1245），缺省档见 tool/recipe_nav.py。
WAIT_PAGE_TIMEOUT = 8

# 商店「服务管理」是「关掉后隐藏对应服务入口」的开关。服务类入口要留，推广入口才关。
STORE_KEEP = [
    "帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：存储空间清理",
    "我的专区：我的资产", "我的专区：安全守护", "我的专区：小i客服",
    "应用使用记录", "首页：AI搜索",
]

# 全局搜索的设置页 SearchSettingActivity 没有导出：am start -n 直接被系统拒绝
# （SecurityException: not exported，和 ColorOS 17 的 PKT110 一样），只能用它自己的 scheme 打开。
# 前置条件：com.heytap.quicksearchbox 不能被挂起——它一挂，这个 scheme 落到系统的
# SuspendedAppActivity「应用已被暂停」页，全局搜索整个不可用，本段也做不了。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"


def guard():
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "RMX3700" or not build.startswith(BUILD):
        skip("型号或系统版本不同，跳过；请重新核对页面")


def step_store(p, rt):
    p.start("com.heytap.market")
    p.tap("我的", exact=True, scrolls=0)
    time.sleep(1.2)
    if not p.tap("设置", exact=True, scrolls=0):
        print("  ! 商店里没找到「设置」")
        return False
    time.sleep(1.5)
    if not wait_page("com.heytap.market.mine.cn.setting.ui.SettingActivity", "设置"):
        return False

    # 服务管理：46 项推广/服务入口，只保留 STORE_KEEP 里的服务类。
    if tap_by_scroll("服务管理"):
        if wait_page("com.heytap.market.mine.cn.setting.ui.ServeManagerActivity", "服务管理"):
            p.off(keep=STORE_KEEP, page="商店·服务管理")
        else:
            print("  ! 没到「服务管理」页")
        p.back()
        time.sleep(1.2)

    # 个性化推荐不在「隐私」页，在「账号与隐私 → 隐私授权管理 → 个性化推荐」。
    # 商店 App 自己升级，这一行在有的版本里叫「隐私」（#933）；两页都可以当落点判。
    tap_by_scroll("账号与隐私")
    privacy = ("隐私", "隐私授权管理")
    if tap_by_scroll(privacy):
        if wait_page("com.heytap.market.mine.cn.setting.ui.PrivacyActivity", privacy):
            if tap_by_scroll("个性化推荐"):
                if wait_page("com.heytap.market.mine.cn.setting.ui.PersonalRecommendActivity",
                             "个性化推荐"):
                    p.off(only=["个性化推荐"], page="商店·个性化推荐")
                else:
                    print("  ! 没到「个性化推荐」页")
            else:
                print("  ! 没找到「个性化推荐」")
        else:
            print("  ! 没到「隐私授权管理」页")
        p.back()
        time.sleep(1.0)
    else:
        p.note_miss(" / ".join(privacy))
        print("  ! 没找到「隐私授权管理」")
    return True


def tail():
    print("\n== 结果", flush=True)
    for name, state in rt.results:
        print(f"  {name}: {state}")
