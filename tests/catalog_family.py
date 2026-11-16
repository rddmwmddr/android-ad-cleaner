"""catalog 族的用例表（#1398）：装载期拒绝非法形状的 23 条，一行一条。

每行是 `data`（`catalog.validate` 必须拒绝的一份数据）加 `needle`（报错里必须出现的子串）。
这些行原先一条一个 `def`，owner 是票号；现在 owner 是它们依赖的结构项，结构项退场，行跟着退场。

句柄（`handles`）全部从行自己的 `data` 现算，不写字符串字面量句柄——手写句柄等于给 `OPS`
造第二个 owner。四类：哪个 kind、哪个必填键缺了、顶层字段、段字段。

拒绝「结构里根本没有的东西」的行（`kind = "explode"`、顶层 `surprise`）句柄为空：它们测的就是
那个名字不在结构里，给任何句柄都会说成「这条行依赖某个结构项」，与它要断言的事相反。

`produce` 跑一次校验器并留下报错原文；不再被拒时留下 `<accepted>`，这样「丢掉一条拒绝」也会在
快照 diff 里显形。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import catalog  # noqa: E402
from catalog.schema import OPS, SEGMENT_KEYS, TOP_KEYS  # noqa: E402

from family import Family, cli  # noqa: E402

CASES = [
    {
        "id": "unknown-top-key",
        "data": {"segment": [{"name": "a", "ops": []}], "surprise": 1},
        "needle": "名单外的键",
    },
    {
        "id": "unknown-op-kind",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "explode"}]}]},
        "needle": "不在白名单",
    },
    {
        "id": "off-without-naming",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "off", "page": "p"}]}]},
        "needle": "没点名",
    },
    {
        "id": "off-only-keep-overlap",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "off", "only": ["x", "y"], "keep": ["y"], "page": "p"},
        ]}]},
        "needle": "重叠",
    },
    {
        "id": "duplicate-segment-names",
        "data": {"segment": [{"name": "a", "ops": []}, {"name": "a", "ops": []}]},
        "needle": "段名重复",
    },
    {
        "id": "focus-match-unknown",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "if_focus", "text": "p", "match": "fnmatch"},
        ]}]},
        "needle": "match='fnmatch' 认不出",
    },
    {
        "id": "return-value-not-boolean",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "return", "value": "false"}]}]},
        "needle": "只能是 true / false",
    },
    {
        "id": "page-missing-args",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "page", "kwargs": {"activity": "X"}},
        ]}]},
        "needle": "缺 args",
    },
    {
        "id": "page-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "page", "args": ["X"], "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "skip-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "skip"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "skip-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "skip", "text": "x", "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "fail-missing-text",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "fail"}]}]},
        "needle": "缺 text",
    },
    {
        "id": "fail-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "fail", "text": "x", "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "require-tap-missing-miss-print",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_tap", "text": "设置"},
        ]}]},
        "needle": "缺 miss_print",
    },
    {
        "id": "require-tap-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "require_tap", "text": "x", "miss_print": "y", "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "close-listed-missing-names",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "close_listed", "page": "p", "miss_print": "y"},
        ]}]},
        "needle": "缺 names",
    },
    {
        "id": "close-listed-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "close_listed", "names": ["a"], "page": "p", "miss_print": "y",
             "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "tap-id-without-selector",
        "data": {"segment": [{"name": "a", "ops": [{"kind": "tap_id"}]}]},
        "needle": "resource_id 或 text",
    },
    {
        "id": "tap-id-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "tap_id", "text": "x", "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
    {
        "id": "gesture-missing-ms",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 0.3], "end": [0.5, 0.7]},
        ]}]},
        "needle": "缺 ms",
    },
    {
        "id": "gesture-point-out-of-range",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 1.2], "end": [0.5, 0.7], "ms": 300},
        ]}]},
        "needle": "0–1 的比例",
    },
    {
        "id": "gesture-ms-not-positive",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 0.3], "end": [0.5, 0.7], "ms": 0},
        ]}]},
        "needle": "正的整数毫秒",
    },
    {
        "id": "gesture-extra-key",
        "data": {"segment": [{"name": "a", "ops": [
            {"kind": "gesture", "start": [0.5, 0.3], "end": [0.5, 0.7], "ms": 300,
             "surprise": 1},
        ]}]},
        "needle": "名单外的键",
    },
]


def _walk_ops(ops):
    """一条 op 列表连同 `OPS` 声明的子 op 列表里的全部 op。"""
    for op in ops:
        if not isinstance(op, dict):
            continue
        yield op
        spec = OPS.get(op.get("kind"))
        if spec is not None:
            for key in spec.nested:
                nested = op.get(key)
                if isinstance(nested, list):
                    yield from _walk_ops(nested)


def _case_ops(data):
    for segment in data.get("segment", []):
        if isinstance(segment, dict):
            nested = segment.get("ops")
            if isinstance(nested, list):
                yield from _walk_ops(nested)


def _names_something_absent(data):
    """这条行拒绝的是结构里没有的名字（顶层字段、段字段或 kind）。

    这样的行句柄为空：它的内容是「这个名字不在结构里」，句柄会说反。
    """
    if not isinstance(data, dict) or set(data) - TOP_KEYS:
        return True
    segments = data.get("segment")
    if not isinstance(segments, list):
        return True
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) - SEGMENT_KEYS:
            return True
    return any(op.get("kind") not in OPS for op in _case_ops(data))


def handles(case):
    """这条行依赖的结构项，全部从它自己的数据现算。"""
    data = case["data"]
    if _names_something_absent(data):
        return ()
    found = set()
    for key in data:
        if key in TOP_KEYS:
            found.add(("top-key", key))
    for segment in data.get("segment", []):
        if not isinstance(segment, dict):
            continue
        for key in segment:
            if key in SEGMENT_KEYS:
                found.add(("segment-key", key))
    for op in _case_ops(data):
        kind = op["kind"]
        found.add(("kind", kind))
        for key in OPS[kind].required:
            if key not in op:
                found.add(("required", kind, key))
    return tuple(sorted(found))


def structure():
    """当前存在的全部结构项：四类句柄各自从 `OPS` / 顶层 / 段键现算。"""
    found = {("top-key", key) for key in TOP_KEYS}
    found |= {("segment-key", key) for key in SEGMENT_KEYS}
    for kind, spec in OPS.items():
        found.add(("kind", kind))
        found |= {("required", kind, key) for key in spec.required}
    return found


def produce(case):
    """校验器给出的报错原文；不再被拒时留下 `<accepted>`。"""
    try:
        catalog.validate(case["data"])
    except catalog.SchemaError as exc:
        return str(exc)
    return "<accepted>"


FAMILY = Family("catalog-rejections", CASES, handles=handles, structure=structure,
                produce=produce)

if __name__ == "__main__":
    sys.exit(cli())
