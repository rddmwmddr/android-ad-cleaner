# V2303A 本机例外函数（catalog，#1263）：全局搜索的多页循环、应用商店的直达兜底是过程段。
# 由 catalog.loader 装进执行作用域（preamble 已注入 maybe / gear / off_unnamed / SkipStep / time）。


import time
import recipe_nav as nav
from recipe_runtime import SkipStep
def step_global_search(p, rt):
    # 每个子页都先重新 p.setting("全局搜索") 回到主页再钻，保证每段起点干净。
    for name, switches in (
        ("首页展示内容", ["搜索框推荐词", "推荐卡片"]),
        ("推荐热搜榜单", ["热门搜索"]),        # Android 17 上无此入口（#220），找不到即跳过
        ("个性化内容", ["广告个性化"]),          # 历史记录、应用建议保留
    ):
        # 放在 try 外面：搜不到要记成整段未完成，不能被下面「单页跳过」的 except 吞掉（#819）
        if not p.setting("全局搜索"):
            raise RuntimeError("没搜到「全局搜索」")
        try:
            if nav.maybe(p, rt, name, scrolls=2):
                p.off(only=switches, page=f"全局搜索·{name}"); p.back()
        except Exception as e:
            print(f"  · {name} 跳过：{e}")


def step_store(p, rt):
    # 「我的」页没有能读到的齿轮入口，设置页只能按 Activity 直达（#220）。
    try:
        p.start("com.bbk.appstore", ".ui.menu.AppstoreSettingsActivity")
        reached = "AppstoreSettingsActivity" in p.focus()
    except SkipStep:
        raise                     # App 本机没装：放行，由段包装记跳过（#908）
    except RuntimeError as e:
        print(f"  · 直达商店设置页失败（{e}），改走「我的 → 设置」")
        reached = False
    if not reached:
        p.start("com.bbk.appstore", expect=("我的",))
        if not p.tab("我的"):
            raise RuntimeError("商店底部「我的」标签没找到")
        time.sleep(0.8)
        nav.gear(p, rt)
    if nav.maybe(p, rt, "关于"):
        if nav.maybe(p, rt, "个性化推荐"):
            p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐")
            p.top()                     # p.off 会往下翻；这一页的开关在上面时别错过
            nav.off_unnamed(p, rt, "商店·个性化推荐")
            p.back(); time.sleep(0.5)
        if nav.maybe(p, rt, "服务管理"):
            p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                  keep=["我的服务", "空间清理"], page="商店·服务管理")
            p.back()
        p.back()
    p.back(2)
