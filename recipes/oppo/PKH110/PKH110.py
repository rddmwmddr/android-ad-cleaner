# OPPO Find N5（PKH110，ColorOS 17.0.0.103）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 八段全是数据，这里只剩型号守卫、收尾打印与推广位名单这一类模块级常量。

BUILD = "PKH110_17.0.0.103"
MODELS = ["PKH110"]

# 仅关闭明确列名的推广入口。没有列出的入口（包括未来新增项）不主动处理。
STORE_PROMOTIONS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "游戏专区：找游戏-种草", "游戏专区：重磅更新卡片", "游戏详情页：游戏活动卡片",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：积分商城", "我的专区：休闲一刻",
    "我的专区：安装有礼", "我的专区：福利中心", "我的专区：金豆乐园",
    "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动", "游戏详情页：游戏礼包",
    "手机管家：应用推荐", "文件管理：应用推荐", "游戏专区：活动集合", "详情页：限时活动", "福利专区",
]

# 段体（store_promotions）按 `g["off_exact"]` 取这个钩子，实现住在 recipe_strategies 的
# `off_exact_paged_optional`（本机「未找到」不算失败），这里绑回旧名字（#1253）。


def guard(p, rt):
    model = p.shell("getprop ro.product.model").strip()
    build = p.shell("getprop ro.build.display.id").strip()
    if model not in MODELS or not build.startswith(BUILD):
        rt.skip("型号或系统版本不同，跳过；请重新核对页面")


def tail(p, rt):
    print("\n本机型脚本不处理：负一屏（设置页受 oppo.permission.OPPO_COMPONENT_SAFE 保护，"
          "adb 边缘手势进不去，需机主手动在负一屏内关「热点资讯」「轮播推荐」）、OPPO 视频、游戏中心。")
    print("分段结果：", rt.results)
