"""引擎机器人行（ADR-0004 / ADR-0009）：事件报客户端自己看不到的状态，载荷进上报日志。

只有客户端设了 AAC_EVENTS 才发；直接跑脚本的人看不到这两类行。客户端认固定前缀：
事件行剥掉后只改状态，不进界面、不进上报；载荷行剥掉后进日志与上报，不进步骤摘要。
"""
import json
import os

PREFIX = "#aac:event "
PAYLOAD_PREFIX = "#aac:payload "

KINDS = ("paused", "resumed", "locked", "ui_busy", "link_lost", "failed_steps")


def emit(kind, **data):
    """发一条事件。kind 拼错是编程错误，直接抛；没设 AAC_EVENTS 时什么都不做。

    `data` 是这条事件的载荷（`failed_steps` 的段名列表），跟 kind 进同一行 JSON。
    没有载荷时那一行与只有 kind 时逐字相同（ADR-0004 的增补段）。
    """
    if kind not in KINDS:
        raise ValueError(f"未定义的事件：{kind}")
    if not os.environ.get("AAC_EVENTS"):
        return
    print(PREFIX + json.dumps({"kind": kind, **data}, ensure_ascii=False), flush=True)


def payload(text):
    """发一段上报载荷（比如页面骨架），一行一个前缀。没设 AAC_EVENTS 时什么都不做。"""
    if not os.environ.get("AAC_EVENTS"):
        return
    for line in str(text).splitlines():
        if line.strip():
            print(PAYLOAD_PREFIX + line, flush=True)


def is_event(line):
    return line.startswith(PREFIX)


def is_payload(line):
    return line.startswith(PAYLOAD_PREFIX)


def strip_payload(line):
    return line[len(PAYLOAD_PREFIX):] if is_payload(line) else line


def parse_data(line):
    """事件行 → 整个 dict（kind 与载荷）；不是事件行、kind 不在词表里、解析不出来，一律 None。"""
    if not is_event(line):
        return None
    try:
        data = json.loads(line[len(PREFIX):])
    except (ValueError, AttributeError):
        return None
    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        return None
    return data


def parse(line):
    """事件行 → kind；不是事件行、或解析不出来，一律返回 None。"""
    data = parse_data(line)
    return data["kind"] if data else None
