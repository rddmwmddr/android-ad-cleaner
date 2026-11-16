"""从 `docs/adr/` 渲染 ADR 索引到 `docs/adr/README.md`（#1299）。

用法：python devtools/gen_adr_index.py
新增、改名或换掉一级标题的 ADR 写完就跑一次；漏跑或漏收录由
`tests/test_doc_consistency.py` 的 `AdrIndexTests` 抓。README 整份由本脚本生成，不要手改。
"""
import re
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))   # stdio 留在引擎目录

from stdio import use_utf8_console

use_utf8_console()

ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs/adr"
TARGET = ADR_DIR / "README.md"
NAME = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
HEADING = re.compile(r"^# +(.*\S) *$")
FENCE = "```"
HEADER = "<!-- 由 devtools/gen_adr_index.py 生成：加 ADR 时写文件再跑一次，不要手改这张表。 -->"
LEAD = ("`docs/adr/` 下每一份决定的编号与标题，按编号排序。模块边界的决定写进这里；"
        "机制与取舍在各自文件里，目录里放什么、编号怎么取见 "
        "[docs/agents/domain.md](../agents/domain.md)。")


class Entry(NamedTuple):
    number: str
    title: str
    filename: str


def first_heading(path):
    """一级标题；围栏代码块里的 `# …` 是注释，不算标题。"""
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(FENCE):
            fenced = not fenced
            continue
        match = None if fenced else HEADING.match(line)
        if match:
            return match.group(1)
    return None


def entries():
    """[(编号, 标题, 文件名)]，按编号升序；目录里的非 ADR 文件（README.md 自己）跳过。"""
    found = []
    for path in sorted(ADR_DIR.glob("*.md")):
        match = NAME.match(path.name)
        if not match:
            continue
        title = first_heading(path)
        if title is None:
            sys.exit(f"{path.name} 没有一级标题：索引要有标题可列")
        found.append(Entry(match.group(1), title, path.name))
    return found


def render(items):
    lines = [HEADER, "", "# ADR 索引", "", LEAD, ""]
    lines += [f"- [{e.number}]({e.filename}) — {e.title}" for e in items]
    return "\n".join(lines) + "\n"


def main():
    items = entries()
    if not items:
        sys.exit("docs/adr/ 里没有任何 ADR：索引会是空表")
    TARGET.write_text(render(items), encoding="utf-8", newline="\n")
    print(f"updated {TARGET.relative_to(ROOT)}（{len(items)} 份）")


if __name__ == "__main__":
    main()
