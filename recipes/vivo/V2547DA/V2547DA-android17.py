# V2547DA Android 17 变体的本机例外函数（catalog，沿用 #1263 的页面树）：阅图锁屏是直达优先（opened(...)）的过程段。
# 由 catalog.loader 装进执行作用域（preamble 已注入 opened / settings_home / maybe）。
import recipe_nav as nav


def step_lock_screen(p, rt):
    only = ["阅图锁屏", "锁屏横滑进入阅图"]
    if nav.opened(p, rt, lambda: p.start("com.vivo.magazine", ".ui.MagazineSettings", expect="锁屏横滑进入阅图", budget=2)):
        p.off(only=only, page="阅图锁屏")
        return
    nav.settings_home(p, rt)
    if nav.maybe(p, rt, "桌面、锁屏与壁纸") and nav.maybe(p, rt, "锁屏设置") and nav.maybe(p, rt, "阅图锁屏"):
        p.off(only=only, page="阅图锁屏")
