"""从 docs/手机版教程/brand-taps.json 渲染三处「连点 7 下」品牌表（#654）。

用法：python tool/gen_brand_taps.py
只改 JSON 一处，跑本脚本，三处同时生效；漏跑则 tests/test_doc_consistency.py 红。

渲染范围是三个文件里 `brand-taps:start` / `brand-taps:end` 标记之间的内容，
其余内容一字不动。
"""
import json
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/手机版教程/brand-taps.json"
TARGETS = {
    "html": ROOT / "android-tutorial.html",
    "readme": ROOT / "docs/手机版教程/README.md",
    "dev_doc": ROOT / "docs/00-打开开发者模式.md",
}
START = "<!-- brand-taps:start -->"
END = "<!-- brand-taps:end -->"


class Row(NamedTuple):
    brand: str
    path: str
    tap: str


def load_rows():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    out = [Row(r["brand"], r["path"], r["tap"]) for r in data["rows"]]
    if not out:
        sys.exit("brand-taps.json 没有任何行")
    return out


def render_html(table):
    lines = ['    <table class="table">', "      <thead><tr><th>品牌</th><th>在哪儿连点 7 下</th></tr></thead>", "      <tbody>"]
    lines += [f"        <tr><td>{r.brand}</td><td>{r.tap}</td></tr>" for r in table]
    lines += ["      </tbody>", "    </table>"]
    return "\n".join(lines)


def render_tap_table(table):
    lines = ["| 品牌 | 在哪儿连点 7 下 |", "|---|---|"]
    lines += [f"| {r.brand} | {r.tap} |" for r in table]
    return "\n".join(lines)


def render_dev_doc(table):
    first = ["| 品牌 | 路径 |", "|---|---|"]
    first += [f"| {r.brand} | {r.path} |" for r in table]
    return "\n".join(first), render_tap_table(table)


def check_markers(text, count, name):
    """每处目标的标记区必须是 count 对，否则抛 ValueError。"""
    starts, ends = text.count(START), text.count(END)
    if (starts, ends) != (count, count):
        raise ValueError(f"{name} 的 brand-taps 标记区数量不符（需 {count} 对，"
                         f"实际 start={starts} end={ends}")


def replace_regions(text, rendered_list):
    """按出现顺序替换每对 brand-taps 标记区，结束标记保留原有缩进。"""
    out = []
    rest = text
    for rendered in rendered_list:
        head, rest = rest.split(START, 1)
        before_end, tail = rest.split(END, 1)
        last_line = before_end[before_end.rfind("\n") + 1:]
        indent = last_line if not last_line.strip() else ""
        out.append(head + START + "\n" + rendered + "\n" + indent + END)
        rest = tail  # 消费掉本对标记之间的旧内容，只把后面的留给下一轮
    return "".join(out) + rest


def render_all():
    table = load_rows()
    path_table, tap_table = render_dev_doc(table)
    return {
        "html": [render_html(table)],
        "readme": [render_tap_table(table)],
        "dev_doc": [path_table, tap_table],
    }


def main():
    rendered = render_all()
    texts = {k: p.read_text(encoding="utf-8") for k, p in TARGETS.items()}
    for key, path in TARGETS.items():
        try:
            check_markers(texts[key], len(rendered[key]), path.name)
        except ValueError as e:
            sys.exit(str(e))
    for key, path in TARGETS.items():
        updated = replace_regions(texts[key], rendered[key])
        path.write_text(updated, encoding="utf-8", newline="\n")
        print(f"updated {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
