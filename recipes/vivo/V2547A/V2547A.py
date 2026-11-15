# V2547A 的本机例外函数（catalog 的 `code=`，影随 `V2547A.toml`）。其余七段都已转成数据，
# 只剩 i管家一段：首屏体检动画期间点「设置」会被吞，重试到前台换成 MainSettings 为止，是循环。
# vivo X300 Ultra（V2547A，OriginOS 7，Android 17）机型脚本；2026-10-25 在真机逐页实测，8 段整段跑通，重跑 126 秒。
import recipe_nav as nav
import recipe_strategies as strategies
BUILD = "PD2547B_A_17.1.10.2"          # ro.build.display.id 的开头；对不上引擎只提示，不阻断
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
#
# 这台和 docs/清单/vivo-OriginOS.md 里实测的 V2547DA（OriginOS 6）不是同一版系统，入口有几处不同：
#   · 浏览器冷启动停在首页，底部没有「我的」，只能走右上「菜单 → 设置」
#   · 应用商店的「服务管理」「个性化推荐」在「设置 → 关于」里，且必须点行中间（点左侧文字不转发点击）
#   · 天气的设置藏在右上 more_btn 后面（页面里那个「更多」是展开按钮，按文字找会点错）
#   · 关推荐类开关会弹「温馨提示 → 取消 / 确认关闭」，按钮节点 text 是空的，文字挂在 vbutton_title 里（#397）
#   · 开关行是「整行 + 开关」两个 checkable 节点（y 差 7px），整行节点的标题还会串到上一行，
#     所以库里自己扫了一遍树，按行还原标题、排除单选钮，再逐行只点一次（`recipe_lib/vivo.py` 的 `rows`）
import time

# 家族库按这些常量选走法（沿用 #1246），缺省档与实现见 recipe_lib/。
TAP_ROW_STYLE = "centre"
TAP_TEXT_STYLE = "vivo"
GOTO_STYLE = "vivo"
BROWSER_FLOW = "vivo_menu"


def step_i_manager(p, rt):
    p.start("com.iqoo.secure", settle=2.0)
    time.sleep(1.2)                            # 首屏有体检动画，动画期间点设置会被吞
    ok = False
    for _ in range(3):
        if p.tap("设置", exact=True, scrolls=0):
            time.sleep(1.2)
            if "MainSettings" in p.focus():
                ok = True
                break
    if not ok:
        print("  ✗ 没进到 i 管家设置"); return
    if nav.goto(p, rt, "关于", scrolls=2):
        if nav.goto(p, rt, "个性化设置", scrolls=2):
            strategies.off(p, rt, only=["应用个性化推荐", "清理个性化推荐"], page="i管家·个性化设置")
            p.back(1)
        p.back(1)
    p.back(2)
