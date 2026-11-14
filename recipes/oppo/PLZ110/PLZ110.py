# 一加 15T（PLZ110，ColorOS 17）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 七段全部落数据；这里只剩注入面按名字取用的模块常量、一个本机安装检查助手与尾钩子。
import adb_link
from fast import ScreenLocked, bounds


BUILD = "PLZ110_17.0.0.107(CN01)"

# 分段结果由引擎经 rt 记录
SKIPPED_ITEMS = []
# 回读确认数由引擎经 rt 记录

SEARCH = "com.heytap.quicksearchbox"
MARKET = "com.heytap.market"
THEME = "com.heytap.themestore"
VIDEO = "com.heytap.yoli"
GAME = "com.nearme.gamecenter"
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
SEARCH_CARDS = ["未下载应用推荐", "应用建议小卡", "热搜应用", "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片"]
# 轮播单选只有这两个选项，「不显示」是我们要的那一档（沿用 #280 的做法）。
CAROUSEL_LABELS = {"显示轮播推荐", "不显示轮播推荐"}
CAROUSEL_OFF = "不显示轮播推荐"

# 负一屏首页的两条已知文案（PLG110 / PMA110 实测）：头像入口万一改名，两条都在也算到了（#901）
LAUNCHER = "com.android.launcher/"
ASSISTANT_HOME = {"我的服务", "添加卡片"}


def tail(p, rt):
    print(f"\n逐项回读确认 {rt.verified} 项；完成 {sum(state == '完成' for _, state in rt.results)} 段，"
          f"跳过 {sum(state == '跳过' for _, state in rt.results)} 段，未显示项 {len(SKIPPED_ITEMS)} 组", flush=True)


# 负一屏 / 主题 / 视频 / 游戏中心的段体按 `g["close_named"]` 取这个钩子，实现住在
# recipe_strategies 的 `close_named_optional`，这里绑回旧名字（#1253）。

