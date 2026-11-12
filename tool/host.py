"""这次执行跑在哪个宿主上：手机版由 aac_android.main.boot() 设 AAC_HOST=phone（#729）。

手机版没有电脑、数据线和 USB，点击由本 App 自己发出，连接也断在 App 内部，所以排查提示要换一套说法。
引擎每次执行前清掉 `tool/` 下已加载的模块、换上这次的环境变量再导入，导入时读一次就够。
"""
import os

ON_PHONE = os.environ.get("AAC_HOST") == "phone"
CLICKER = "本 App" if ON_PHONE else "电脑"
# 「本 App」后面要留空格、直接拼会变成「本 App点击」，所以整句放在这里。
# 两种桌面说法（「电脑点击」「电脑发出的点击」）历史不同，各自保留，别合并（#747）。
CLICK = f"{CLICKER} 发出的点击" if ON_PHONE else f"{CLICKER}点击"
TAPPED = f"{CLICKER} 发出的点击" if ON_PHONE else f"{CLICKER}发出的点击"

# 结果页「这次用的机型脚本验到什么程度」那两句（#1188）。桌面版要引导用户回 App 里核对，
# 手机版不劝人去一个已经待着的地方。判定在 tool/coverage_note.py，这里只有措辞。
# `on_phone` 由调用方给、没有默认值：默认取 `ON_PHONE` 会把继承来的环境变量带进桌面结果页（#747）。
def coverage_notes(on_phone: bool) -> dict[str, str]:
    """按宿主给出负面两档的整句；`全部` 与未知档不在这张表里（不占行）。"""
    where = "" if on_phone else "在 App 里"
    return {
        "部分": f"这套机型脚本只在一部分步骤上做过真机验证，其余步骤这次是照脚本直接跑的，建议{where}顺手核对一眼。",
        "未记录": f"这套机型脚本没有真机验证记录，改动结果建议{where}自己核对一遍。",
    }
