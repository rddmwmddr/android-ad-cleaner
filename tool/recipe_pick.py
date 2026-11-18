"""这台机该跑哪份机型脚本：型号直选、同版本变体、同族参考与版本核心比较的唯一 owner。

`recipe_for()` 是选脚本的唯一入口：型号 + 品牌 + 设备版本 → `(路径, 是否参考)`。`REFERENCE` /
`build_ok` / `version_match` / `version_core` 同样是公开面，`run.py` 的命令与测试从这里取它们；
其中 `build_ok` 与 `version_match` 对「录制版本没标」的结论刻意相反，别合并成一个。
"""
import glob
import os
import re
from collections.abc import Mapping

from entries import FAMILY      # 品牌族只此一份；广告包、参考脚本与版本比较都按它归
from recipe_meta import recipe_meta

# 没给 root= 时的仓库根：`tool/` 的上一级。它要与 `run.py` 的 `ROOT` 算出同一个目录——不传
# root 的调用（测试、诊断）与各命令必须看到同一棵树。
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 没有本型号脚本时用的同品牌参考脚本。以前取目录名排第一的那份，社区每加一个机型，
# 别的手机用的参考脚本就可能跟着变（10-28 合并社区机型脚本时发现）；固定成一份经过真机验证的最全的。
# 家族 → 固定参考脚本的型号目录名（`recipes/<家族>/<型号>/recipe.py`）。
REFERENCE = {"oppo": "PLP120", "honor": "PNM-AN10", "xiaomi": "M154FF", "vivo": "V2547DA",
             "meizu": "MEIZU 21 Pro"}

# 把脚本 BUILD 或设备版本抽成版本核心时要先切掉的机型名标记（#319）。
VERSION_MARKER = {"oppo": "_", "vivo": "_A_", "honor": " ", "meizu": "Flyme"}

# vivo 的 build 不都带机型前缀：Android 17 起有的机器直接报 AOSP 平台构建号（#580 的
# CP2A.260605.016），没有 _A_ 可切，整条就是版本核心。按形状认，不写死某一代的首字母。
AOSP_BUILD_ID = re.compile(r"^[A-Z]{1,3}\d[A-Z0-9]{0,2}\.\d{6}\.\d{3}")

# 小米的 ro.build.display.id 可能是 Android 底包（BP2A.250605.031、SKQ1.210908.001）：同一代
# 机型共用一个号，对「两台机是不是同一个 ROM 版本」零信息量，抽出的核心必须为空、不参与比对
# （#942）。与上面 vivo 的方向相反——那个 AOSP 号是逐版本的，这边是跨机型共享的。
XIAOMI_BASE_BUILD = re.compile(r"^[A-Z]{1,3}\d[A-Z0-9]{0,2}\.\d{6}\.\d{3}")


def version_core(value: str, fam: str) -> str:
    """抽出可比的版本号：切掉机型名、去掉括号。抽不出来返回空串，空值不参与比对。"""
    v = (value or "").strip()
    if fam == "xiaomi" and XIAOMI_BASE_BUILD.match(v):
        return ""
    marker = VERSION_MARKER.get(fam)
    if marker:
        if marker in v:
            v = v.split(marker, 1)[1]
        elif fam != "vivo" or not AOSP_BUILD_ID.match(v):
            return ""
    return re.sub(r"\(.*$", "", v).strip()


# 版本号的分量边界：`11.0.0` 与 `11.0.0.111` 算同一版本；`11.0.0.11` 与 `11.0.0.111` 不算。
VERSION_SEPARATORS = ".-_ "


def _is_version_prefix(short: str, long: str) -> bool:
    """short 是 long 在分量边界上的前缀；空值或停在分量中间都不算。"""
    if not short or not long.startswith(short):
        return False
    return len(short) == len(long) or long[len(short)] in VERSION_SEPARATORS


def matching_device_version(device_info: Mapping[str, str] | None, core: str, fam: str) -> str:
    """设备和 core 对得上的那段版本原值；core 为空或对不上返回空串。

    `core` 与设备版本按分量对齐，短的可以是长的前缀：设备常只报到 `11.0.0`，脚本录到
    `11.0.0.111`（#1428）。同一层里不同的号仍互不命中——`11.0.0.111` 与 `11.0.0.120`
    不算同一版本；设备报得更粗时两者都可能命中，由挑选方的核心长度 / 段数 / 目录名定序。"""
    if not core:
        return ""
    # 没报的字段不进比较：`filter(None, ...)` 同时跳过缺键与空串，不用给每个字段垫一个 `or ""`。
    versions = filter(None, ((device_info or {}).get("build"), (device_info or {}).get("os")))
    for raw in versions:
        got = version_core(raw, fam)
        if got and (_is_version_prefix(got, core) or _is_version_prefix(core, got)):
            return raw
    return ""


def version_match(device_info: Mapping[str, str] | None, recorded: str, fam: str) -> str:
    """返回和录制版本对得上的那段设备版本；对不上返回空串。按分量前缀比较（沿用 #319 的前缀比，分量边界见 #1428）。

    与 build_ok 不同：这里没标录制版本就算对不上、不参与挑选；build_ok 把没标的当成不告警。
    """
    return matching_device_version(device_info, version_core(recorded, fam), fam)


def _dir_family(path: str) -> str:
    """脚本所属家族：路径是 `recipes/<家族>/<型号>/recipe*.py`，家族是型号目录的上一级目录名。"""
    family = os.path.basename(os.path.dirname(os.path.dirname(path)))
    return FAMILY.get(family.lower(), "")


def same_version_family_recipe(allr: list[str], fam: str, preferred: str,
                               device_info: Mapping[str, str] | None) -> str | None:
    """同族里挑一份比固定参考更贴这台、且不比它窄的专用脚本；挑不到返回 None。

    固定参考与候选同池比版本核心的具体程度：候选要严格更长才换。等长意味着两者对这台机
    同样贴，保固定参考——否则目录名字母序就成了决定因素（#969）。固定参考对不上这台时它
    不设门槛，任何对得上的同版本候选都比它贴（#319）。段数门槛是硬条件：版本对得上但更窄
    的脚本会让一次运行少关一类广告（#319）。
    """
    ref_meta = recipe_meta(preferred)
    ref_core = version_core(ref_meta["build"], fam)
    ref_matches = bool(matching_device_version(device_info, ref_core, fam))
    ref_steps = len(ref_meta["steps"])
    ranked: list[tuple[int, int, str, str]] = []
    for r in allr:
        if _dir_family(r) != fam:
            continue
        meta = recipe_meta(r)
        core = version_core(meta["build"], fam)
        if not matching_device_version(device_info, core, fam):
            continue
        if ref_matches and len(core) <= len(ref_core):
            continue
        if len(meta["steps"]) < ref_steps:
            continue
        # 录制得越具体越贴这台；同长度按段数、再按目录名，不随遍历顺序变。
        ranked.append((-len(core), -len(meta["steps"]), os.path.basename(os.path.dirname(r)), r))
    return sorted(ranked)[0][3] if ranked else None


def _main_script(directory: str) -> str | None:
    """型号目录的主脚本：优先 `recipe.py`，否则已转 catalog 的 `<型号>.toml`；都没有返回 None。

    正本是 `<型号>.toml`（目录名即型号，见 #1261）；其余 `*.toml`（`<型号>-<变体>.toml`）是版本
    变体，由 `recipe_for` 按 build 单独挑（#1263）。按字母序排的话 `-` 排在 `.` 前面，变体会顶掉
    正本，所以主本 / 变体只能按名字判，不能取 `sorted(...)[0]`。"""
    base = os.path.join(directory, "recipe.py")
    if os.path.exists(base):
        return base
    toml = sorted(glob.glob(os.path.join(directory, "*.toml")))
    if not toml:
        return None
    main = os.path.join(directory, os.path.basename(directory) + ".toml")
    return main if os.path.exists(main) else toml[0]


def _recipe_files(root: str | os.PathLike[str]) -> list[str]:
    """`root` 下每个型号目录的「主脚本」：`_main_script()`。

    变体 `recipe_*.py` 不算主脚本：它们是同一型号的不同版本，由 `recipe_for` 按 build 单独挑
    （与旧 `glob(recipe.py)` 的口径一致，否则变体会被当成另一台机的正本）。没有 `recipe.py`
    也没有 `.toml` 的异常目录（真实仓库没有）退回变体，免得整台机消失。"""
    out = []
    for d in sorted(glob.glob(os.path.join(root, "recipes", "*", "*"))):
        if not os.path.isdir(d):
            continue
        main = _main_script(d)
        if main is not None:
            out.append(main)
            continue
        out += sorted(glob.glob(os.path.join(d, "recipe*.py")))
    return out


def recipe_for(model: str, brand: str = "", device_info: Mapping[str, str] | None = None, *,   # pragma: no mutate 语义等价：省略 brand 时的占位串 "XXXX" 在 FAMILY 里没有条目，fam 仍是空串。
               root: str | os.PathLike[str] | None = None) -> tuple[str | None, bool]:
    """返回 (路径, 是否参考)。先找本型号（目录名或脚本里的 MODELS）；没有就找同家族别的机型，作参考。

    `root` 是仓库根（含 `recipes/` 的那一层），不给时用 `REPO_ROOT`。它是 keyword-only：
    放开成位置参数的话，品牌写错到第三位就会让型号被静默当成树根。
    """
    where = REPO_ROOT if root is None else root
    allr = _recipe_files(where)
    for r in allr:
        d = os.path.basename(os.path.dirname(r))
        if d == model or model in recipe_meta(r)["models"]:
            # 一个型号可能有不同系统版本的实测路径。仅在版本明确匹配时选择变体。
            # 变体两种形态：`recipe_*.py` 与 `<型号>-*.toml`（转目录化之后的变体）。
            if device_info:
                here = os.path.dirname(r)
                variants = sorted(glob.glob(os.path.join(here, "recipe_*.py")))
                variants += [t for t in sorted(glob.glob(os.path.join(here, "*.toml"))) if t != r]
                for variant in variants:
                    recorded = recipe_meta(variant)["build"]
                    if recorded and build_ok(device_info, recorded):
                        return variant, False
            return r, False
    fam = FAMILY.get((brand or "").lower(), "")   # pragma: no mutate 语义等价：占位品牌串 "xxxx" 与占位族名 "XXXX" 都不在 FAMILY 的键 / 值里，查表与后面的比较给出的仍是空族。
    if fam in REFERENCE:
        # 参考脚本与 `_recipe_files()` 同一口径：主本优先于变体。vivo 的 `V2547DA-android17.toml`
        # 按字母序排在 `V2547DA.toml` 前面，取 `sorted(...)[0]` 会让参考变成 Android 17 变体，
        # `same_version_family_recipe()` 的 `ref_core` 跟着从 `16` 变 `17.1.10.2`。
        # `_main_script()` 只给两种答案：目录里确实存在的那份主本，或一份脚本都没有时的 None。
        preferred = _main_script(os.path.join(where, "recipes", fam, REFERENCE[fam]))
        if preferred is not None:
            # 固定参考的 BUILD 常写得粗（OS4.0、16），前缀一命中就到它为止，同族里录在同版本上的
            # 脚本永远进不了候选。两条路径同池排（#969）；固定参考的 BUILD 写粗只是让它自己不够贴。
            if device_info:
                picked = same_version_family_recipe(allr, fam, preferred, device_info)
                if picked:
                    return picked, True
            return preferred, True
    for r in allr:
        if fam and _dir_family(r) == fam:
            return r, True
    return None, False


def build_ok(i: Mapping[str, str], rb: str) -> bool:
    """录制版本 rb 和这台对不对得上：比 ro.build.display.id，小米再比 HyperOS 版本号。"""
    if not rb:
        return True
    # 没报的字段不进比较：`filter(None, ...)` 同时跳过缺键与空串，不用给 HyperOS 版本号垫一个 `or ""`。
    versions = filter(None, (i["build"], i.get("os")))
    return any(version.startswith(rb) for version in versions)
