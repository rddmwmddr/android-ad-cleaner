"""结果页的验证档位提示（#1188）：说不说的判据只有一份，措辞按宿主从 tool/host.py 取。

与 tool/summary.py 分家是各管一件事：那一份说「这一步结果怎么样」，这一份说「这次用的机型脚本
验到什么程度」。宿主由调用方显式指定，不读 `host.ON_PHONE`——那个标记读的是继承来的环境变量，
桌面用户 shell 里碰巧导出 `AAC_HOST=phone` 时结果页会说成手机版措辞（#747 只替引擎清掉了它）。
"""
from collections.abc import Mapping
from typing import Any

import host


def note(run: Mapping[str, Any], on_phone: bool) -> str:
    """结果页要不要为脚本的验证档位多一行；要说时给整句，不说时给空串。

    说不说的判据是「这次真有脚本那一行的结果」：没勾脚本、停止在它之前、读屏占用让它跳过时都不说，
    拿别的步的结论去说脚本的事会误导。`全部` 与没有值都不占行。

    `on_phone` 只影响措辞：桌面宿主传 `False`，手机版的 `view.poll()` 传 `True`。
    """
    results = run.get("results") or []
    if not any(r.get("kind") == "recipe" and not r.get("skipped") for r in results):
        return ""
    return host.coverage_notes(on_phone).get(run.get("recipe_coverage") or "", "")
