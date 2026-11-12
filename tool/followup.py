"""复测队列核对（#988）：报出 `waiting-for-verify` 标签与复测主表的差异，可选写回（#989）。

用法：

    python3 tool/followup.py            # 只读：打印差异，一个字节都不写
    python3 tool/followup.py --write    # 把表补到与标签一致，写完再核对一遍

两类差异：**缺行**（标签里有、主表里没有）与**过期行**（主表里有、标签里没有，已关闭或已摘标）。

带 `blocked-on-device` 的票不进队列：它们在等一台维护者没有的机器，催不动。它们既不补缺行，
也不催；已有行原样留着不删——删掉会连机型、修复版本与要观察的输出一起丢掉，与「一半过期的
合列行不删」同一条取舍（#989）。
`--write` 只补缺行（追加到 `## 当前队列` 的第一张表末尾，其余几列留 `—` 等发版时现场填）、
只删过期行（从它实际所在的那张表删），既有行与其他小节逐字不动。两次 `--write` 的结果相同。

只解析 `## 当前队列` 小节里的表（含它 `###` 子小节里的批次表），靠表头含 `Issue` 列判定；
别的 `##` 小节（尤其「待真机反馈」）与日期记录段一律不看。结构认不出时报错退出，
不退回全文扫描。

一行可以登记多张票（`#193 / #581`），两边的号都算已登记。

退出码：0 一致；1 有差异（清单已打印）；2 给不出结论——`gh` 读失败或超时、表格结构不可识别、
命令行给了不认识的参数。读不到标签或结构认不出时不写任何文件。
"""
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from gh import GhError, json_of, runner_for

from stdio import use_utf8_console

use_utf8_console()

LABEL = "waiting-for-verify"
BLOCKED = "blocked-on-device"
HEADING = "当前队列"
ISSUE_COLUMN = "Issue"
LIMIT = 1000
TIMEOUT = 120
PLACEHOLDER = "—"
USAGE = "用法：python3 tool/followup.py [--write]"
DOC = Path(__file__).resolve().parents[1] / "docs" / "agents" / "release-followup.md"

EXIT_OK, EXIT_DIFF, EXIT_UNREADABLE = 0, 1, 2

ISSUE_CELL = re.compile(r"^#\d+(\s*/\s*#\d+)*$")
TOKEN = re.compile(r"#(\d+)")
RULE = re.compile(r"^[|\s:-]+$")
SPLIT = re.compile(r"(?<!\\)\|")


class Unreadable(RuntimeError):
    """表格结构认不出：不猜，整条命令给不出结论。"""


@dataclass(frozen=True)
class Table:
    columns: tuple
    issues: tuple


@dataclass(frozen=True)
class Result:
    """一轮核对：两类差异按票号升序，`missing` 带作者（催复测时要 @ 的人）。

    `labeled` 与两类差异都只算进队列的票；`blocked` 是被 `blocked-on-device` 排除的张数，
    其中 `parked` 张在队列里已有行、原样留着不催。
    """
    rows: int
    labeled: int
    missing: tuple
    expired: tuple
    blocked: int = 0
    parked: int = 0

    @property
    def same(self):
        return not self.missing and not self.expired


def cells(line):
    """一行表格 -> 单元格；`\\|` 是单元格里的竖线，不当分隔符。"""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return [item.strip().replace("\\|", "|") for item in SPLIT.split(text)]


def is_rule(line):
    text = line.strip()
    return "-" in text and bool(RULE.match(text))


def section_bounds(lines):
    """`## <HEADING>` 之后到下个一 / 二级标题之前的行索引区间 `[起, 止)`；找不到返回 None。

    `###` 子小节留在这个范围内，所以小节里的每一张表都是队列的一部分：
    主表之外还有分批登记的表，它们的票号同样算已登记。
    """
    title = re.compile(r"^##\s+" + re.escape(HEADING) + r"\s*$")
    start = None
    for index, line in enumerate(lines):
        if start is None:
            if title.match(line):
                start = index + 1
            continue
        if re.match(r"^#{1,2}\s", line):
            return start, index
    return None if start is None else (start, len(lines))


def table_ranges(lines, start, end):
    """`[start, end)` 里每张 Markdown 表的行索引区间 `[起, 止)`。

    连续以 `|` 开头的行为一张表；表之间隔着的记录段、`###` 标题都不算。
    """
    found, open_at = [], None
    for index in range(start, end):
        if lines[index].strip().startswith("|"):
            if open_at is None:
                open_at = index
                found.append([index, index + 1])
            else:
                found[-1][1] = index + 1
        else:
            open_at = None
    return [tuple(item) for item in found]


def rows_of(lines, start, end):
    """一张表（行索引区间）-> (表头单元格, [(行索引, 这张票据号元组), ...])。

    表头、分隔行与票号列读不出来时抛 Unreadable；`table_of` 与 `apply` 都走这一份判据。
    """
    if end - start < 2 or not is_rule(lines[start + 1]):
        raise Unreadable(f"「## {HEADING}」小节里有一张表没有表头：{lines[start].strip()}")
    header = cells(lines[start])
    if ISSUE_COLUMN not in header:
        raise Unreadable(f"「## {HEADING}」小节有一张表没有 `{ISSUE_COLUMN}` 列："
                         f"{' | '.join(header)}")
    at = header.index(ISSUE_COLUMN)
    found = []
    for index in range(start + 2, end):
        row = cells(lines[index])
        if len(row) != len(header) or not ISSUE_CELL.match(row[at]):
            raise Unreadable(f"有一行的 `{ISSUE_COLUMN}` 读不成票号：{lines[index].strip()}")
        found.append((index, tuple(int(number) for number in TOKEN.findall(row[at]))))
    return header, found


def queue_tables(lines):
    """`## <HEADING>` 小节里的每张表 -> [(行索引区间, 表头, [(行索引, 票号元组)])]。"""
    bounds = section_bounds(lines)
    if bounds is None:
        raise Unreadable(f"找不到「## {HEADING}」小节")
    found = table_ranges(lines, *bounds)
    if not found:
        raise Unreadable(f"「## {HEADING}」小节里没有可识别的 Markdown 表")
    parsed = []
    for start, end in found:
        header, rows = rows_of(lines, start, end)
        parsed.append(((start, end), header, rows))
    return parsed


def table_of(text):
    """Markdown 文本 -> 复测队列表；小节或表头认不出时抛 Unreadable。"""
    tables = queue_tables(text.splitlines())          # 一张表都没有时已经 raise，列表非空
    numbers = []
    for _, _, rows in tables:
        for _, tickets in rows:
            numbers += list(tickets)
    return Table(columns=tuple(tables[0][1]), issues=tuple(dict.fromkeys(numbers)))


def login(author):
    return str((author or {}).get("login") or "").strip()


def names(issue):
    """一张票的标签名集合；`labels` 缺省时是空集。"""
    return {item.get("name") for item in issue.get("labels") or []}


def scan(text, issues):
    """一份 Markdown 文本 + 一份 issue 列表 -> Result。纯函数：不碰文件系统与网络。

    带 `blocked-on-device` 的票整张排除：不补缺行、不催；已有行不算过期，原样留着。
    """
    table = table_of(text)
    waiting, blocked = {}, set()
    for issue in issues:
        number = int(issue["number"])
        if BLOCKED in names(issue):
            blocked.add(number)
            continue
        waiting[number] = login(issue.get("author"))
    known = set(table.issues)
    return Result(
        rows=len(table.issues),
        labeled=len(waiting),
        missing=tuple((number, who) for number, who in sorted(waiting.items())
                      if number not in known),
        expired=tuple(sorted(known - set(waiting) - blocked)),
        blocked=len(blocked),
        parked=len(blocked & known),
    )


def read_open(runner):
    """读 open 的 `waiting-for-verify` 票 -> gh 的 JSON 列表。

    `--limit` 不能省：`gh issue list` 默认只给 30 条，128 张票会有一大片被当成「过期行」。
    标签一起读回来，`scan` 才能把 `blocked-on-device` 的票排除出去。
    """
    issues = json_of(runner, "issue", "list", "--label", LABEL, "--state", "open",
                     "--limit", str(LIMIT), "--json", "number,author,labels",
                     source="`gh issue list`")
    if not isinstance(issues, list):
        raise GhError("`gh issue list` 的输出不是票的列表")
    for issue in issues:
        labels = issue.get("labels")
        if labels is not None and (not isinstance(labels, list)
                                   or any(not isinstance(item, dict) for item in labels)):
            raise GhError(f"#{issue.get('number')} 的 labels 不是对象数组，判不了它带哪些标签")
    return issues


def render(result):
    lines = [f"{LABEL} {result.labeled} 张进队列，队列里登记 {result.rows} 张"]
    if result.blocked:
        note = f"{BLOCKED} {result.blocked} 张不进队列"
        if result.parked:
            note += f"，已有行的 {result.parked} 张原样留着、不再催"
        lines.append(note + "。")
    if result.same:
        lines.append("一致：没有缺行，也没有过期行。")
        return "\n".join(lines)

    lines.append(f"缺行 {len(result.missing)}（标签里有、队列里没有）：")
    for number, who in result.missing:
        lines.append(f"  #{number}  @{who}" if who else f"  #{number}  （无作者）")
    lines.append(f"过期行 {len(result.expired)}（队列里有、标签里没有）：")
    for number in result.expired:
        lines.append(f"  #{number}")
    return "\n".join(lines)


def skeleton(number, who, columns):
    """补出来的一行：票号与报告者照实填，机型、版本、要观察的输出留 `—` 等发版时现场补。"""
    fields = [f"#{number}", f"@{who}" if who else PLACEHOLDER]
    fields += [PLACEHOLDER] * max(columns - len(fields), 0)
    return "| " + " | ".join(fields) + " |"


def apply(text, result):
    """把一轮核对的结果写进 `text`：缺行补到主表末尾，过期行从它所在的表里删掉。

    纯函数，输入输出都是字符串。既有的行、表的顺序与表外的内容逐字保留；
    没有差异时原样返回，所以同一份结果连写两次不会再变。
    """
    if result.same:
        return text
    lines = text.splitlines(keepends=True)
    tables = queue_tables(lines)

    expired = set(result.expired)
    drop = set()
    for _, _, rows in tables:
        for index, numbers in rows:
            # 一行可以登记多张票（`#193 / #581`）。只有这一行的票全过期才删：
            # 删掉仍开着的那张会连带丢掉它的机型与要观察的输出，宁可留着让核对继续报差异。
            if numbers and set(numbers) <= expired:
                drop.add(index)

    added = [skeleton(number, who, len(tables[0][1])) + "\n" for number, who in result.missing]
    anchor = tables[0][0][1] - 1      # 主表最后一行，补行落在它后面

    out, pending = [], list(added)
    for index, line in enumerate(lines):
        if index > anchor and pending:
            out.extend(pending)
            pending = []
        if index in drop:
            continue
        out.append(line)
    out.extend(pending)
    return "".join(out)


def main(argv, runner=None, doc=None):
    args = list(argv)
    write = args == ["--write"]
    if args and not write:
        print(f"不认识的参数：{' '.join(args)}\n{USAGE}", file=sys.stderr)
        return EXIT_UNREADABLE
    runner = runner or runner_for(timeout=TIMEOUT)
    try:
        issues = read_open(runner)
    except GhError as error:
        print(error, file=sys.stderr)
        return EXIT_UNREADABLE
    except subprocess.TimeoutExpired:
        print(f"`gh issue list` 超过 {TIMEOUT} 秒没有返回，这一次给不出结论", file=sys.stderr)
        return EXIT_UNREADABLE
    path = Path(doc or DOC)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"读不到复测队列文档：{error}", file=sys.stderr)
        return EXIT_UNREADABLE
    try:
        result = scan(text, issues)
    except Unreadable as error:
        print(f"复测队列文档的结构认不出：{error}", file=sys.stderr)
        return EXIT_UNREADABLE
    print(render(result))
    if not write or result.same:
        return EXIT_OK if result.same else EXIT_DIFF

    before = len(text.splitlines())
    try:
        # newline 钉死 LF：默认写法会把整份文档改写成 CRLF，Windows 上「逐字不动」就破了
        updated = apply(text, result)
        path.write_text(updated, encoding="utf-8", newline="\n")
        text = path.read_text(encoding="utf-8")
    except Unreadable as error:
        print(f"复测队列文档的结构认不出：{error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except OSError as error:
        print(f"写不回复测队列文档：{error}", file=sys.stderr)
        return EXIT_UNREADABLE

    removed = len(result.missing) - (len(updated.splitlines()) - before)
    print(f"写回 {path}：补 {len(result.missing)} 行，删 {removed} 行")
    try:
        result = scan(text, issues)
    except Unreadable as error:
        print(f"写回后的复测队列文档结构认不出：{error}", file=sys.stderr)
        return EXIT_UNREADABLE
    print(render(result))
    return EXIT_OK if result.same else EXIT_DIFF


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
