# 荣耀 PNM-AN10（MagicOS 10）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 browser_settings / SkipStep 由装载器注入执行作用域。
# 线性段已转成 `.toml` 数据；这里只留过程化的段（坐标、dumpsys、条件分支）与四个助手
# （`dismiss` / `dismiss_no` / `open_entry` / `close_all_oaid`，后两个由数据按名字调用）。
import adb_link
import time
from fast import ScreenLocked
import recipe_nav as nav
from recipe_runtime import SkipStep
# 本机没装荣耀浏览器时 browser_settings 会回退到预装百度浏览器那套；这份依赖在事实层要留一条出处。
from recipe_strategies import baidu_browser


BUILD = ""
MODELS = ["PNM-AN10"]

def dismiss(p, rt, *words):
    """开 App 时的推荐弹窗/协议弹窗：一律点「取消/以后再说/禁止」，不替用户同意。"""
    for _ in range(3):
        tx = {t for t, _, _ in p.texts()}
        hit = [w for w in words if w in tx]
        if not hit:
            return
        p.tap(hit[0], exact=True, scrolls=0)


NO = ("取消", "以后再说", "禁止", "暂不", "跳过", "我知道了")


def dismiss_no(p, rt):
    dismiss(p, rt, *NO)


def open_entry(p, rt, text, scrolls=0):
    """点开会换页的菜单项，点不进去就记下停在哪一页并跳过本段。断线与锁屏照常上抛。"""
    try:
        p.enter(text, scrolls=scrolls)
    except (adb_link.DeviceLost, ScreenLocked):
        raise
    except RuntimeError as error:
        print(f"  · {error}")
        p.note_miss(text)
        return False
    return True


def close_all_oaid(p, rt):
    """点这一页的「全部关闭」并把确认框收掉；编排语义，留在本机例外函数里（ADR-0038）。

    与 CLE-AN00 的同名走法不同：本机的列表页一定有这个按钮，点不到也不退回上一页。"""
    p.tap("全部关闭", exact=True, scrolls=0)
    p.confirm()


def step_negative(p, rt):
    p.shell("am start -f 0x10008000 -n com.hihonor.hiboard/com.hihonor.intelligent.LauncherActivity")
    time.sleep(2)
    if not p.find("头像", exact=True):
        p.press("home"); time.sleep(0.6)
        for _ in range(3):
            p.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
            if p.find("头像", exact=True):
                break
        else:
            raise RuntimeError("负一屏没打开，没找到头像入口")
    p.tap("头像", exact=True, scrolls=0)
    p.tap("设置", exact=True, scrolls=0)
    p.off(only=["智能推荐", "个性化广告", "个性化消息"], page="负一屏·设置")
    p.back()
    p.tap("资讯服务", exact=True, scrolls=0)
    p.off(only=["资讯精选"], page="负一屏·资讯服务")
    p.back(3)


def step_market(p, rt):
    p.start("com.hihonor.appmarket")
    if p.find("基本服务", exact=True, edge_ok="tab") and not p.find("我的", exact=True, edge_ok="tab"):
        print("  已是基本服务模式（没有推荐、没有设置入口），跳过"); return
    p.tap("我的", exact=True, scrolls=0)
    dismiss(p, rt, *NO)
    p.tap("设置", exact=True, scrolls=0)
    p.tap("内容推荐服务", exact=True)
    p.off(only=["营销服务推荐"], page="市场·内容推荐服务")
    p.off(only=["个性化服务推荐"], page="市场·内容推荐服务")
    p.back()
    p.tap("消息通知管理", exact=True)
    p.off(only=["消息通知"], keep=["应用更新"], page="市场·消息通知管理")
    p.back()
    p.tap("消息中心提醒", exact=True)
    p.off(only=["活动福利", "游戏动态"], page="市场·消息中心提醒")
    p.back()
    p.tap("服务模式", exact=True)
    if p.tap("基本服务", exact=True, scrolls=0):
        p.confirm()
    p.back()


def step_browser(p, rt):
    if nav.browser_settings(p, rt) is False:
        return
    p.tap("模式选择", exact=True)
    p.tap("简洁首页", exact=True, scrolls=0)
    p.back()
    p.tap("消息通知", exact=True)
    p.off(only=["新闻热点", "兴趣推送"], page="浏览器·消息通知")
    p.back()
    p.tap("隐私管理", exact=True)
    p.tap("个性化推荐", exact=True, scrolls=0)
    p.off(only=["个性化内容"], page="浏览器·个性化推荐")
    p.back()
    p.tap("互动广告管理", exact=True, scrolls=0)
    p.off(page="浏览器·互动广告")
    p.back(3)


def step_magazine(p, rt):
    if not p.setting("杂志", "魔法画报"):
        raise RuntimeError("没搜到「魔法画报」")
    p.tap("魔法画报", exact=True, scrolls=0)
    if "magazine" not in p.focus():
        xy = [b for t, b, _ in p.texts() if t == "魔法画报"]
        if len(xy) > 1:
            l, t, r, b = xy[-1]; p.click((l + r) // 2, (t + b) // 2); time.sleep(1.2)
    p.off(only=["锁屏画报轮播", "锁屏进入魔法画报"], page="魔法画报")
    p.back()
