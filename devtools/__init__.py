"""仓库工具链（CI 与本机跑的脚本），不随包发到手机上（ADR-0041）。

边界对半分：`tool/` 是出厂引擎，随 APK 发到桌面与手机上；`devtools/` 是仓库侧的票务、发版与
校验脚本，只在 CI 与本机跑。两者只靠 `tool/stdio.py` 相连——工具链 import 引擎，引擎不 import
工具链，`tests/test_tool_package.py` 守着这条方向。

19 个模块在这里平铺、保留「直接跑文件」的用法（`python3 devtools/claim.py <票号>`），所以同一份
源码要同时成立两种导入方式：

- 直接跑文件：`sys.path[0]` 就是 `devtools/`，同包的裸 import（`from gh import`）自己成立。
- 包导入（`from devtools.claim import …`）：这两个目录都不在 `sys.path` 上，所以下面补一次。

`tool/` 是 `from stdio import` 的落点（引擎不搬），`devtools/` 是各模块裸 import 同包兄弟的落点。
只在缺的时候补，避免重复 import 把这两个目录反复顶到最前面。
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _path in (_HERE, _HERE.parents[1] / "tool"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
