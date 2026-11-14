# Redmi Note 14 Pro（24090RA29C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 主题段按文字坐标点「我的」标签（它在 65% 屏高以下，p.tab() 只认最下面那道带），留在过程化实现里。
import time
from entries import THEME_DEAD_ENDS
import recipe_nav as nav
import recipe_steps as steps


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


def step_theme(p, rt):
    # 直接起主题管理包的代理页（沿用 #730 的做法：它没有 LAUNCHER，monkey 拉不起来）；前台就是它自己，
    # 交给 start() 等落点。经主题商店冷启动的过渡窗会误判，也可能续在上次留下的子页上（#906）。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    rt.start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    time.sleep(3)                               # 首页要几秒才画完，早读会找不到底部标签
    p.dismiss()
    # 底部「我的」标签在 65% 屏高以下，p.tab() 只认最下面那道带，这里按位置找
    xy = next((((l + r) // 2, (t + b) // 2) for text, (l, t, r, b), node in p.texts()
               if text == "我的" and t >= p.H * 0.65), None)
    if xy is None:
        raise RuntimeError("主题「我的」标签没找到；" + p.page_evidence())
    tap_sig = p.sig()
    p.click(*xy)
    p.settle(tap_sig, 1.5)
    p.dismiss()
    # 导航失败以前与「本页没有目标开关」同形：进设置页、点名开关也校验，带页面现场（#906）。
    if not nav.gear(p, rt):
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
