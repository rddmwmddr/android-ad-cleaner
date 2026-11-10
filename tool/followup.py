"""复测队列核对（#988）：只读报出 `waiting-for-verify` 标签与复测主表的差异。

用法：

    python3 tool/followup.py

两类差异：**缺行**（标签里有、主表里没有）与**过期行**（主表里有、标签里没有，已关闭或已摘标）。
只读——不写回文件，也不改任何 issue。

只解析 `## 当前队列` 小节里的表（含它 `###` 子小节里的批次表），靠表头含 `Issue` 列判定；
别的 `##` 小节（尤其「待真机反馈」）与日期记录段一律不看。结构认不出时报错退出，
不退回全文扫描。

一行可以登记多张票（`#193 / #581`），两边的号都算已登记。

退出码：0 一致；1 有差异（清单已打印）；2 给不出结论——`gh` 读失败或超时、表格结构不可识别、
命令行给了参数。前两种情形都不写任何文件。
"""
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass

LABEL = "waiting-for-verify"
HEADING = "当前队列"
ISSUE_COLUMN = "Issue"
LIMIT = 1000
TIMEOUT = 120
DOC = Path(__file__).resolve().parents[1] / "docs" / "agents" / "release-followup.md"

EXIT_OK, EXIT_DIFF, EXIT_UNREADABLE = 0, 1, 2

ISSUE_CELL = re.compile(r"^#\d+(\s*/\s*#\d+)*$")
TOKEN = re.compile(r"#(\d+)")
RULE = re.compile(r"^[|\s:-]+$")
SPLIT = re.compile(r"(?<!\\)\|")


class Unreadable(RuntimeError):
    """表格结构认不出：不猜，整条命令给不出结论。"""


class GhError(RuntimeError):
    """`gh` 调用失败：读不到标签时整条命令给不出结论。"""


@dataclass(frozen=True)
class Table:
    columns: tuple
    issues: tuple


@dataclass(frozen=True)
class Result:
    """一轮核对：两类差异按票号升序，`missing` 带作者（催复测时要 @ 的人）。"""
    rows: int
    labeled: int
    missing: tuple
    expired: tuple

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


def section(lines):
    """`## <HEADING>` 到下一个一 / 二级标题之间的行；找不到返回 None。

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
            return lines[start:index]
    return None if start is None else lines[start:]


def blocks(lines):
    """小节里所有 Markdown 表的行组（连续以 `|` 开头的行为一张表）。"""
    found, current = [], None
    for line in lines:
        if line.strip().startswith("|"):
            if current is None:
                current = []
                found.append(current)
            current.append(line)
        else:
            current = None
    return found


def table_of(text):
    """Markdown 文本 -> 复测队列表；小节或表头认不出时抛 Unreadable。"""
    body = section(text.splitlines())
    if body is None:
        raise Unreadable(f"找不到「## {HEADING}」小节")
    found = blocks(body)
    if not found:
        raise Unreadable(f"「## {HEADING}」小节里没有可识别的 Markdown 表")
    columns, numbers = None, []
    for block in found:
        if len(block) < 2 or not is_rule(block[1]):
            raise Unreadable(f"「## {HEADING}」小节里有一张表没有表头：{block[0].strip()}")
        header = cells(block[0])
        if ISSUE_COLUMN not in header:
            raise Unreadable(f"「## {HEADING}」小节有一张表没有 `{ISSUE_COLUMN}` 列："
                             f"{' | '.join(header)}")
        columns = columns or tuple(header)
        at = header.index(ISSUE_COLUMN)
        for line in block[2:]:
            row = cells(line)
            if len(row) != len(header) or not ISSUE_CELL.match(row[at]):
                raise Unreadable(f"有一行的 `{ISSUE_COLUMN}` 读不成票号：{line.strip()}")
            numbers += [int(number) for number in TOKEN.findall(row[at])]
    return Table(columns=columns, issues=tuple(dict.fromkeys(numbers)))


def login(author):
    return str((author or {}).get("login") or "").strip()


def scan(text, issues):
    """一份 Markdown 文本 + 一份 issue 列表 -> Result。纯函数：不碰文件系统与网络。"""
    table = table_of(text)
    labeled = {int(issue["number"]): login(issue.get("author")) for issue in issues}
    known = set(table.issues)
    return Result(
        rows=len(table.issues),
        labeled=len(labeled),
        missing=tuple((number, who) for number, who in sorted(labeled.items())
                      if number not in known),
        expired=tuple(sorted(known - set(labeled))),
    )


def read_open(runner):
    """读 open 的 `waiting-for-verify` 票 -> gh 的 JSON 列表。

    `--limit` 不能省：`gh issue list` 默认只给 30 条，128 张票会有一大片被当成「过期行」。
    """
    out, err, rc = runner("gh", "issue", "list", "--label", LABEL, "--state", "open",
                          "--limit", str(LIMIT), "--json", "number,author")
    if rc != 0:
        raise GhError(f"读不到 open 的 {LABEL} 票：{(err or out).strip() or 'gh 返回非零'}")
    try:
        issues = json.loads(out)
    except ValueError as error:
        raise GhError(f"`gh issue list` 的输出不是 JSON：{error}") from error
    if not isinstance(issues, list):
        raise GhError("`gh issue list` 的输出不是票的列表")
    return issues


def runner_for(cwd=None):
    """默认的 `gh` 执行器：签名 `(script, *args) -> (标准输出, 错误输出, 返回码)`。

    带超时：`gh` 卡在网络请求上时进程不能一直挂着，发版前这一步是有时限的。
    """
    def run(script, *args):
        done = subprocess.run([script, *args], cwd=cwd, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
        return done.stdout, done.stderr, done.returncode
    return run


def render(result):
    lines = [f"{LABEL} {result.labeled} 张，队列里登记 {result.rows} 张"]
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


def main(argv, runner=None, doc=None):
    if argv:
        print(f"不接受参数：{LABEL} 队列核对只有一个固定形状\n用法：python3 tool/followup.py",
              file=sys.stderr)
        return EXIT_UNREADABLE
    runner = runner or runner_for()
    try:
        issues = read_open(runner)
    except GhError as error:
        print(error, file=sys.stderr)
        return EXIT_UNREADABLE
    except subprocess.TimeoutExpired:
        print(f"`gh issue list` 超过 {TIMEOUT} 秒没有返回，这一次给不出结论", file=sys.stderr)
        return EXIT_UNREADABLE
    except OSError as error:      # 没装 gh 或不在 PATH 上
        print(f"跑不了 gh：{error}", file=sys.stderr)
        return EXIT_UNREADABLE
    try:
        text = Path(doc or DOC).read_text(encoding="utf-8")
    except OSError as error:
        print(f"读不到复测队列文档：{error}", file=sys.stderr)
        return EXIT_UNREADABLE
    try:
        result = scan(text, issues)
    except Unreadable as error:
        print(f"复测队列文档的结构认不出：{error}", file=sys.stderr)
        return EXIT_UNREADABLE
    print(render(result))
    return EXIT_OK if result.same else EXIT_DIFF


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
