# REDMI K90 Ultra（M332BF）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 主题的换页等待靠运行时读到的页面签名，留在这里。
from entries import THEME_DEAD_ENDS


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]
import recipe_nav as nav
import recipe_steps as steps


def step_theme(p, rt):
    # 直达主题管理包的代理页（沿用 #730 的做法：它没有 LAUNCHER，monkey 拉不起来）；经主题商店冷启动
    # 还要过一道重定向过渡窗，前台校验容易误判（#906）。落点被系统转走时仍按跳过收尾。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    rt.start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    tap_sig = p.sig()
    if not p.tab("我的"):
        raise RuntimeError("主题底部「我的」标签没找到；" + p.page_evidence())
    p.settle(tap_sig, 2)
    # 导航失败以前与「本页没有目标开关」同形：三步都校验，报错带页面现场（#906）。
    if not nav.gear(p, rt):                              # 精确认「设置」，不点「设置壁纸」（沿用 #305 的做法）
        raise RuntimeError("主题设置入口没找到；" + p.page_evidence())
    p.await_page()                              # 齿轮点完这一页可能还没画完
    before = {}
    for _ in range(2):                          # 行也可能在首屏之下，off() 自己会翻页找
        before.update({title: on for title, on, _ in p.switches()})
        if not p.scroll_more():
            break
    p.top(2)
    rt.require_switches(before, ["每次联网时通知"], "主题·设置", contains=True)
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if nav.maybe(p, rt, "隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)

