"""仓库工具链（CI 与本机跑的脚本），不随包发到手机上（ADR-0041）。

边界对半分：`tool/` 是出厂引擎，随 APK 发到桌面与手机上；`devtools/` 是仓库侧的票务、发版与
校验脚本，只在 CI 与本机跑。两者只靠 `tool/stdio.py` 相连——工具链 import 引擎，引擎不 import
工具链，`tests/test_tool_package.py` 守着这条方向。

19 个模块在这里平铺，同一份源码要同时成立两种入口：`python3 devtools/claim.py <票号>` 与
`from devtools.claim import claim`。所以同包兄弟写成「相对导入优先、裸名兜底」——直接跑文件时
`sys.path[0]` 就是 `devtools/`，相对导入抛 `ImportError` 落到裸名；包导入时只剩相对导入那一个
模块对象。两种写法混用会让 `sys.modules` 里同时有 `gh` 与 `devtools.gh`，`GhError` 一类的
类型判等随之失效。

`stdio` 留在引擎目录，两种入口都取不到它，所以这里把 `tool/` 补一次。
"""
import sys
from pathlib import Path

_TOOL = Path(__file__).resolve().parent.parent / "tool"
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))
