"""vocab 族的用例表（#1400）：六张「按脚本冻结」的读不出词条表，一行一条。

每行是 `tool/vocab.py` 的 `scan()` 在这份仓库上的一条冻结事实：某份脚本有几条读不出的
`only=` / `close_named()` / `keep=`、几段模块级字典里的说明、几条归不到分组的页面标签，
或者它整份一条词条都读不出来。这些行原先是一张张模块级 `dict` 常量，删一行是静默的
（断言两边同时变）；搬进族之后，删一行就少了快照里的一个 id。

**这是「无产出、只冻结 id 集合」模式的样本**：族不给 `produce`（没有任何要落盘的产出物，
快照里也就没有 `outputs` 键），不给 `expected`。不给 `expected` 是因为这些表只收「读不出
词条」的脚本，仓库里另外那些读得出词的脚本不该被算成缺口——`expected` 会把它们全报成
「结构项没有 case」。冻结表只覆盖一部分脚本（当前 21 / 47），所以也不能退一步拿全部脚本当
期望：那样另外 26 份没有冻结行的脚本会被整份算成缺口。「哪些脚本该被冻结」目前没有可程序
访问的结构来源，**结构推导管新增这一向仍未接入**；要补齐，得先有一份这样的来源（实现侧或
文档侧的冻结清单），再由族按同一口径反推。

句柄（`handles`）从行自己的 `script` 字段现算，不写字符串字面量句柄——手写句柄等于给脚本
清单造第二个 owner。`unclassified` 行按 `(家族, 页面标签)` 冻结、不带单一脚本（同一条标签
可能散在多份脚本里），句柄为空。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import recipe_source  # noqa: E402

from family import Family, cli  # noqa: E402

CASES = [
    # 解析不出的 only=，按脚本冻结。新脚本多了这种写法，先看能不能写成字面量或模块级常量，确实不能再改这里。
    {"id": "unresolved-only/honor/WKL-AN20/WKL-AN20.toml",
     "kind": "unresolved-only", "script": "honor/WKL-AN20/WKL-AN20.toml", "count": 1},
    {"id": "unresolved-only/meizu/MEIZU 21 Pro/MEIZU 21 Pro.toml",
     "kind": "unresolved-only", "script": "meizu/MEIZU 21 Pro/MEIZU 21 Pro.toml", "count": 1},
    {"id": "unresolved-only/oppo/PHK110/PHK110-android15.toml",
     "kind": "unresolved-only", "script": "oppo/PHK110/PHK110-android15.toml", "count": 1},
    {"id": "unresolved-only/oppo/PJA110/PJA110-android16.toml",
     "kind": "unresolved-only", "script": "oppo/PJA110/PJA110-android16.toml", "count": 1},
    {"id": "unresolved-only/oppo/PJA110/PJA110.toml",
     "kind": "unresolved-only", "script": "oppo/PJA110/PJA110.toml", "count": 1},
    {"id": "unresolved-only/oppo/PKH110/PKH110.toml",
     "kind": "unresolved-only", "script": "oppo/PKH110/PKH110.toml", "count": 1},
    {"id": "unresolved-only/oppo/PKT110/PKT110.toml",
     "kind": "unresolved-only", "script": "oppo/PKT110/PKT110.toml", "count": 2},
    {"id": "unresolved-only/oppo/PKX110/PKX110.toml",
     "kind": "unresolved-only", "script": "oppo/PKX110/PKX110.toml", "count": 1},
    {"id": "unresolved-only/oppo/PLG110/PLG110.toml",
     "kind": "unresolved-only", "script": "oppo/PLG110/PLG110.toml", "count": 3},
    {"id": "unresolved-only/oppo/PLP120/PLP120.toml",
     "kind": "unresolved-only", "script": "oppo/PLP120/PLP120.toml", "count": 1},
    {"id": "unresolved-only/oppo/PLZ110/PLZ110.toml",
     "kind": "unresolved-only", "script": "oppo/PLZ110/PLZ110.toml", "count": 2},
    {"id": "unresolved-only/oppo/PMA110/PMA110.toml",
     "kind": "unresolved-only", "script": "oppo/PMA110/PMA110.toml", "count": 2},
    {"id": "unresolved-only/oppo/PMX110/PMX110.toml",
     "kind": "unresolved-only", "script": "oppo/PMX110/PMX110.toml", "count": 2},
    {"id": "unresolved-only/vivo/V2303A/V2303A.toml",
     "kind": "unresolved-only", "script": "vivo/V2303A/V2303A.toml", "count": 1},
    {"id": "unresolved-only/vivo/V2417A/V2417A.toml",
     "kind": "unresolved-only", "script": "vivo/V2417A/V2417A.toml", "count": 1},
    {"id": "unresolved-only/xiaomi/23117RK66C/23117RK66C.toml",
     "kind": "unresolved-only", "script": "xiaomi/23117RK66C/23117RK66C.toml", "count": 1},
    {"id": "unresolved-only/xiaomi/24129PN74C/24129PN74C-os4.toml",
     "kind": "unresolved-only", "script": "xiaomi/24129PN74C/24129PN74C-os4.toml", "count": 2},
    {"id": "unresolved-only/xiaomi/24129PN74C/24129PN74C.toml",
     "kind": "unresolved-only", "script": "xiaomi/24129PN74C/24129PN74C.toml", "count": 1},
    # close_named() 第一个参数解析不出的，和上面分开冻结，免得一个口径盖住另一个。
    {"id": "unresolved-close/oppo/PJA110/PJA110-android16.toml",
     "kind": "unresolved-close", "script": "oppo/PJA110/PJA110-android16.toml", "count": 1},
    {"id": "unresolved-close/oppo/PKT110/PKT110.toml",
     "kind": "unresolved-close", "script": "oppo/PKT110/PKT110.toml", "count": 2},
    {"id": "unresolved-close/oppo/PLZ110/PLZ110.toml",
     "kind": "unresolved-close", "script": "oppo/PLZ110/PLZ110.toml", "count": 1},
    {"id": "unresolved-close/oppo/PMX110/PMX110.toml",
     "kind": "unresolved-close", "script": "oppo/PMX110/PMX110.toml", "count": 1},
    {"id": "unresolved-close/xiaomi/23117RK66C/23117RK66C.toml",
     "kind": "unresolved-close", "script": "xiaomi/23117RK66C/23117RK66C.toml", "count": 1},
    # 解析不出的 keep=，同样按脚本冻结：它只影响同页保留项，读不出时那页的约束就整段丢了。
    {"id": "unresolved-keep/oppo/PHK110/PHK110-android15.toml",
     "kind": "unresolved-keep", "script": "oppo/PHK110/PHK110-android15.toml", "count": 1},
    {"id": "unresolved-keep/oppo/PKH110/PKH110.toml",
     "kind": "unresolved-keep", "script": "oppo/PKH110/PKH110.toml", "count": 1},
    {"id": "unresolved-keep/oppo/PKX110/PKX110.toml",
     "kind": "unresolved-keep", "script": "oppo/PKX110/PKX110.toml", "count": 1},
    {"id": "unresolved-keep/oppo/PLG110/PLG110.toml",
     "kind": "unresolved-keep", "script": "oppo/PLG110/PLG110.toml", "count": 2},
    {"id": "unresolved-keep/oppo/PLZ110/PLZ110.toml",
     "kind": "unresolved-keep", "script": "oppo/PLZ110/PLZ110.toml", "count": 1},
    {"id": "unresolved-keep/oppo/PMA110/PMA110.toml",
     "kind": "unresolved-keep", "script": "oppo/PMA110/PMA110.toml", "count": 1},
    {"id": "unresolved-keep/oppo/PMX110/PMX110.toml",
     "kind": "unresolved-keep", "script": "oppo/PMX110/PMX110.toml", "count": 1},
    {"id": "unresolved-keep/vivo/V2417A/V2417A.toml",
     "kind": "unresolved-keep", "script": "vivo/V2417A/V2417A.toml", "count": 1},
    # 模块级字典里的说明文字，按脚本冻结。
    {"id": "dict-notes/honor/WKL-AN20/WKL-AN20.toml",
     "kind": "dict-notes", "script": "honor/WKL-AN20/WKL-AN20.toml", "count": 37},
    # 一条词条都读不出来的脚本（判据就是零词条）：开关点名散在自建函数里（vivo-V2547A 的 off()、
    # oneplus-PHK110 的 off_exact()、samsung-SM-N9760 的 protect()），或者名单运行时才算。
    {"id": "silent/oppo/PHK110/PHK110-android15.toml",
     "kind": "silent", "script": "oppo/PHK110/PHK110-android15.toml"},
    {"id": "silent/oppo/PHK110/PHK110.toml",
     "kind": "silent", "script": "oppo/PHK110/PHK110.toml"},
    {"id": "silent/samsung/SM-N9760/SM-N9760.toml",
     "kind": "silent", "script": "samsung/SM-N9760/SM-N9760.toml"},
    {"id": "silent/vivo/V2547A/V2547A.toml",
     "kind": "silent", "script": "vivo/V2547A/V2547A.toml"},
    # 页面标签归不到分组的调用。多出来的先看能不能加进 vocab.PAGES。按 (家族, 标签) 冻结，不带单一脚本。
    {"id": "unclassified/honor/<title>",
     "kind": "unclassified", "family": "honor", "text": "<title>", "count": 1},
    {"id": "unclassified/meizu/<page>",
     "kind": "unclassified", "family": "meizu", "text": "<page>", "count": 3},
    {"id": "unclassified/oppo/<page>",
     "kind": "unclassified", "family": "oppo", "text": "<page>", "count": 27},
    {"id": "unclassified/oppo/<title>",
     "kind": "unclassified", "family": "oppo", "text": "<title>", "count": 2},
    {"id": "unclassified/oppo/个性化管理",
     "kind": "unclassified", "family": "oppo", "text": "个性化管理", "count": 3},
    {"id": "unclassified/oppo/隐私",
     "kind": "unclassified", "family": "oppo", "text": "隐私", "count": 4},
    {"id": "unclassified/vivo/<page>",
     "kind": "unclassified", "family": "vivo", "text": "<page>", "count": 1},
    {"id": "unclassified/xiaomi/<page>",
     "kind": "unclassified", "family": "xiaomi", "text": "<page>", "count": 6},
]


def handles(case):
    """这条行依赖的脚本，从它自己的 `script` 字段现算；`unclassified` 行没有单一脚本，句柄为空。"""
    script = case.get("script")
    return [("script", script)] if script else []


def structure():
    """仓库里真实存在的机型脚本，取自事实层唯一的目录遍历口径 `recipe_source.scan_dir()`。"""
    recipes_dir = Path(__file__).resolve().parents[1] / "recipes"
    return {("script", rel) for rel in recipe_source.scan_dir(str(recipes_dir))}


FAMILY = Family("vocab-frozen-per-script", CASES, handles=handles, structure=structure)

if __name__ == "__main__":
    sys.exit(cli())
