# vivo V1986A（iQOO Neo 系）机型脚本：Funtouch OS 13.0 / Android 12；路径来源：V1986A，构建 PD1986_A_8.21.29，2026-10-30 真机逐页实测、整段跑通。
from recipe_kit import step
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
#
# ── 本机型实测要点（和 OriginOS 的 vivo 脚本差别很大，不要照抄那边）────────────
# 1. 系统广告仍在 设置 → 安全 → 更多安全设置 → 广告与隐私（AdAndPrivacyActivityForOsTwo）。
# 2. 锁屏设置页在 **com.android.systemui**（com.vivo.keyguard.views.KeyguardSettings），
#    引擎默认过滤 systemui 文字（那是状态栏），所以点「阅图锁屏」前要把 p.systemui_text 打开。
# 3. 应用商店「我的」是**底部导航栏**，y 在 92% 以下，引擎的 find() 默认不点（防误触），
#    这一段用坐标点最后一个标签。
# 4. 应用商店「设置 → 关于」那行：点标题文字「关于」不跳转，要点**副标题所在行的中间**
#    （副标题以「包括禁用服务设置…」开头）。
# 5. 「个性化推荐」这一页的开关标题带状态（「个性化推荐，开启」→ 点完变「…，关闭」），
#    引擎按标题回读会误报「关不掉」，所以这里按开关本身的状态回读。
# ────────────────────────────────────────────────────────────────────────────
BUILD = "PD1986_A_8"
MODELS = ["V1986A"]
# 家族库按这些常量选走法（#1246），缺省档与实现见 tool/recipe_nav.py。
TAP_ROW_STYLE = "subtitle"
MY_TAB_STYLE = "vivo"
import time  # noqa: F401 - 基线副本，保持与旧脚本逐字一致


@step("系统广告")
def _():
    # 个性化广告、个性化推荐、智能推荐服务：本机实测三个都在这一页
    system_ads_chain()


@step("阅图锁屏")
def _():
    settings_home()
    if maybe("桌面、锁屏与壁纸") and maybe("锁屏设置"):
        p.systemui_text = True               # 锁屏设置页在 com.android.systemui 里
        try:
            if maybe("阅图锁屏"):
                # 总开关「阅图锁屏」在子页里；关掉后「锁屏横滑进入阅图」跟着关
                p.off(only=["阅图锁屏", "锁屏横滑进入阅图"], page="阅图锁屏")
        finally:
            p.systemui_text = False


@step("应用商店")
def _():
    p.start("com.bbk.appstore")
    my_tab()
    if not maybe("设置", scrolls=0):
        print("  ✗ 没进应用商店设置页"); p.back(2); return
    if not tap_row("包括禁用服务设置"):
        print("  ✗ 没找到「关于」那一行"); p.back(2); return
    # 关于页：服务管理（营销位）、个性化推荐
    if maybe("服务管理", scrolls=2):
        p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮球", "限时推广"],
              keep=["我的服务", "空间清理"], page="商店·服务管理")
        p.back()
    if maybe("个性化推荐", scrolls=2):
        off_one("个性化推荐", "商店·个性化推荐")
        p.back()
    p.back(2)


# ── 待补（本机没有入口或未实测，别凭猜加段）────────────────────────────────
# i管家 com.iqoo.secure V8.9.7.5：设置 → 关于 里没有「个性化设置」，本版无该开关。
# 全局搜索 com.vivo.globalsearch：设置里没有独立入口，「桌面下滑」实测为「无」。
# 负一屏 com.vivo.hiboard：vHidden=1（未启用），桌面左滑进不去。
# 天气 com.vivo.dream.weather：清单里的「天气服务 → 热点资讯通知」本机未实测。
# 浏览器：本机没有 com.vivo.browser。
# 营销通知渠道：这台的通知页在 com.android.systemui，chan-off 认不出来，见 issue #336。
# ────────────────────────────────────────────────────────────────────────────

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import maybe, p
    from recipe_nav import my_tab, settings_home, tap_row
    from recipe_steps import system_ads_chain
    from recipe_strategies import off_one
