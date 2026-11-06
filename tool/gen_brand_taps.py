"""从 docs/手机版教程/brand-taps.json 渲染三处「连点 7 下」品牌表（#654）。

用法：python tool/gen_brand_taps.py
只改 JSON 一处，跑本脚本，三处同时生效；漏跑则 tests/test_doc_consistency.py 红。

渲染范围是三个文件里 `brand-taps:start` / `brand-taps:end` 标记之间的内容，
其余内容一字不动。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/手机版教程/brand-taps.json"
TARGETS = {
    "html": ROOT / "android-tutorial.html",
    "readme": ROOT / "docs/手机版教程/README.md",
    "dev_doc": ROOT / "docs/00-打开开发者模式.md",
}
START = "<!-- brand-taps:start -->"
END = "<!-- brand-taps:end -->"


def rows():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    out = [(r["brand"], r["path"], r["tap"]) for r in data["rows"]]
    if not out:
        sys.exit("brand-taps.json 没有任何行")
    return out


def render_html(table):
    lines = ['    <table class="table">', "      <thead><tr><th>品牌</th><th>在哪儿连点 7 下</th></tr></thead>", "      <tbody>"]
    lines += [f"        <tr><td>{b}</td><td>{t}</td></tr>" for b, _, t in table]
    lines += ["      </tbody>", "    </table>"]
    return "\n".join(lines)


def render_readme(table):
    lines = ["| 品牌 | 在哪儿连点 7 下 |", "|---|---|"]
    lines += [f"| {b} | {t} |" for b, _, t in table]
    return "\n".join(lines)


def render_dev_doc(table):
    first = ["| 品牌 | 路径 |", "|---|---|"]
    first += [f"| {b} | {p} |" for b, p, _ in table]
    second = ["| 品牌 | 在哪儿连点 7 下 |", "|---|---|"]
    second += [f"| {b} | {t} |" for b, _, t in table]
    return "\n".join(first), "\n".join(second)


def replace_regions(text, rendered_list):
    """按出现顺序替换每对 brand-taps 标记区（00 文档有两对）。"""
    out = []
    rest = text
    for rendered in rendered_list:
        head, rest = rest.split(START, 1)
        _, tail = rest.split(END, 1)
        out.append(head + START + "\n" + rendered + "\n" + END)
        rest = tail  # 消费掉本对标记之间的旧内容，只把后面的留给下一轮
    return "".join(out) + rest


def render_all():
    table = rows()
    path_table, tap_table = render_dev_doc(table)
    return {
        "html": [render_html(table)],
        "readme": [render_readme(table)],
        "dev_doc": [path_table, tap_table],
    }


def main():
    rendered = render_all()
    texts = {k: p.read_text(encoding="utf-8") for k, p in TARGETS.items()}
    for key, path in TARGETS.items():
        if texts[key].count(START) != len(rendered[key]) or texts[key].count(END) != len(rendered[key]):
            sys.exit(f"{path.name} 的 brand-taps 标记区数量不符（需 {len(rendered[key])} 对）")
    for key, path in TARGETS.items():
        updated = replace_regions(texts[key], rendered[key])
        path.write_text(updated, encoding="utf-8", newline="\n")
        print(f"updated {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
