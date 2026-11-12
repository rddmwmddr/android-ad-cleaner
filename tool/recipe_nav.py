"""机型脚本的公共导航助手（#1150）：跨文件逐字相同的那些导航过程收在这里。

`recipe_kit.preamble()` 写完生命周期与台账之后调用 `install(p, g)`，把公共导航补进同一个
执行作用域。脚本本地定义的同名名字后执行、覆盖注入版，所以同名多簇的机型差异继续留在各自
脚本里，搬过来的只有逐字相同的副本（迁移后脚本侧只删定义、不改调用点）。

实现不 import `recipe_kit`：`skip` / `require` 这类前导名字由工厂从 `g` 取、包进闭包，
两个模块因此没有依赖关系（方向只有 `preamble()` → `install()` 这一条）。

实现体必须与被搬走的脚本副本逐字相同：守卫把工厂里返回的函数源码与脚本里还留着的本地定义
按行比对，改一边不改另一边即红（tests/test_recipe_nav.py）。
"""

import time

from wait import until

# 名字 → 工厂。工厂收 (p, g)，只造闭包、不碰手机，返回写进执行作用域的那个函数。
# 守卫按这张表取注入面的实现源码，比对脚本里还留着的逐字副本（tests/test_recipe_nav.py）。
NAV = {}


# ---------- vivo ----------
#
# `browser_settings` 收的是「不含拉起 App」那一簇：vivo 浏览器没有底部「我的」，入口在右上菜单。
# 含 `p.start` 的另一簇不在范围里：`entries.used_by` 从脚本源码扫 `p.start` / `start_or_skip` /
# `am start -n` / `p.setting` 四类入口，搬走后入口速查会静默漏机型（沿用 #1148 定案 3）。
# V2309A 与 V2547A 各有一份写法不同的同名实现，按「同名多簇一律留脚本原样」不搬。

def _vivo_settings_home(p, g):
    def settings_home():
        p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    return settings_home


def _vivo_browser_settings(p, g):
    def browser_settings(tries=2):
        """右上「菜单 → 设置」，点完要认出设置页（沿用 #753 的做法）。

        冷启动首页没有底部「我的」，入口是右上菜单。菜单浮层右上角有一个 desc 读作「返回」的 ✕
        （id 里带 cancel），等入口时按弹窗去关会把它点掉，刚打开的菜单就收起来了，「设置」再也找不到。
        所以这里只等那一行画出来、直接点，不在等待里关弹窗；点完没进设置页就退回、重开菜单再试一次。
        别的 vivo 型号可能没有这个按钮，最多等 3 秒就放弃本段。"""
        def landed():
            if p.in_settings_page():
                return True
            at = p.find("设置", exact=True)         # Activity 名不含 Setting 的 App：只认顶上那处「设置」标题
            return bool(at) and at[1] < p.H * 0.25

        for _ in range(tries):
            if not p.d(resourceId="com.vivo.browser:id/menu_btn").click_exists(timeout=3):
                return False                        # 本机没有这个按钮：交给调用方跳过本段
            p.await_page(1.6)                       # 菜单是弹层，画出来的那一帧才有「设置」
            xy = until(lambda: p.find("设置", exact=True, edge_ok="tab"), timeout=3.0, poll=0.3,
                       now=time.time, sleep=time.sleep)
            if xy:
                before = p.sig()
                p.click(*xy)
                if p.settle(before, 1.5):
                    p.await_page(1.5)               # Activity 换了、内容可能还在画：等这一页画完再认落点
                    if landed():
                        return True
            p.back()                                # 收起浮层 / 退出点错的页，下一轮重开菜单
        raise RuntimeError(f"浏览器设置页没有打开；停在 {p.focus()}")
    return browser_settings


NAV["settings_home"] = _vivo_settings_home
NAV["browser_settings"] = _vivo_browser_settings


def install(p, g):
    """把公共导航助手写进执行作用域 `g`（原地写，调用方不需要返回值）。"""
    for name, factory in NAV.items():
        g[name] = factory(p, g)
