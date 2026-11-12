"""结果页的一句话（#1189）：给一步的结果算一句人话，两个宿主共用这一份。

只做纯判断：不碰设备、不碰界面、不依赖假对象。桌面版的调度器与手机版的界面判断层都调
`summarize()`，界面只显示它给出的 `summary` 字段，不再自己认日志模式。
"""
import os
import re
from collections.abc import Mapping
from typing import Any

import events

# 结果页要挡住的机器行记号。唯一来源是 tool/events.py 的两个前缀，公共段就从那里现算，
# 别在这里再写一份字面量：认不出模式时摘要取的是末行，漏掉它就会把机器行显示给用户。
MACHINE_PREFIX = os.path.commonprefix([events.PREFIX, events.PAYLOAD_PREFIX])


def _recipe_summary(text: str, turned_off: int) -> str:
    """「机型脚本跑完」那行只有关掉几个，另两类结局要从 tail 里数（沿用 #758 的做法）。

    不动的项只认 `tool/phone/toggler.py` 的 `off()` 末尾那句「核对 X 项，调整 Y 项」：回读确认 /
    调整 N 项 是各机型脚本自己写的、说法不统一，数不准。X−Y 要扣两档「没动但不是本来就
    关着」的：灰态、以及「✗ 关不掉 / 打不开」。带外没点的行仍在 X 里（CONTEXT.md 的
    「拨动计划」），归进「无需改动」。

    几份 vivo / OPPO 脚本自打「✗ 关不掉」却不用核对行（V2547A、V2545A、V1986A、PKH110），
    与 p.off() 的段混在一次运行里会被多扣；tail 只留最近 80 行（`gui/app.py` 的 `_log`），
    日志更长时前几页少算。两处都只让这个数偏小，好过把没拨成说成没事。
    """
    parts = [f"关了 {turned_off} 个开关"]
    same = sum(int(x) - int(y) for x, y in re.findall(r"核对 (\d+) 项，调整 (\d+) 项", text))
    same -= text.count("被上级开关禁用（开关是灰的），未改动")
    same -= len(re.findall(r"✗ (?:关不掉|打不开) ", text))
    if same > 0:
        parts.append(f"{same} 项核对过无需改动")
    m = re.search(r"未完成步骤：(.*)", text)
    if m:
        names = [n.strip() for n in m.group(1).split("、") if n.strip()]
        if names:
            parts.append(f"{len(names)} 段未完成（{names[0]}{' 等' if len(names) > 1 else ''}）")
    return "；".join(parts)


def summarize(result: Mapping[str, Any]) -> str:
    """一步的结果用一句话说；认不出模式就取日志末行（所以机器行不能进 tail）。

    分支顺序照桌面版原有实现（#1189）。插电常亮两条只有桌面版会产出——手机版不写它
    （ADR-0019 的「增补：手机版不碰插电常亮」）——但口径在这里只有一份，两块屏说同一句话。
    """
    tail = [line for line in result.get("tail") or [] if not line.startswith(MACHINE_PREFIX)]
    text = "\n".join(tail)
    m = re.search(r"机型脚本跑完：关了 (\d+) 个，(\d+) 秒", text)
    if m:
        return _recipe_summary(text, int(m.group(1)))
    m = re.search(r"拨了 (\d+) 个", text)
    if m:
        left = re.search(r"仍开着: (\d+) 个", text)
        return f"关了 {m.group(1)} 个渠道" + (f"，复查仍开着 {left.group(1)} 个" if left else "")
    if "快应用组件已关闭" in text:
        return f"{len(re.findall(r'已关闭$', text, re.M))} 个组件已关闭"
    if "快照已存" in text:
        return "已保存"
    m = re.search(r"插电常亮已改回 (\d+)", text)
    if m:
        return f"插电常亮已改回 {m.group(1)}"
    if "插电常亮未改动" in text:
        return "插电常亮未改动"
    lines = [line for line in tail if line]
    return lines[-1] if lines else ""
