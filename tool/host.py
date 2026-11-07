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
