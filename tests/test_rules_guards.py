"""文档内容类四条规则的守卫（#1000）：CHANGELOG 条目一行一个票号、文档里的代码位置用符号名、
指到的 `.py` 路径要存在、上报服务地址与凭据不写进仓库。

四条都只读文件、比字符串：不联网、不执行被测代码、不引入 Markdown 解析依赖。
三条守的是「文档现在长什么样」，旧树也绿，守的是不回退（`dev.tests.behaviour-change-needs-red-test`
允许守卫用例如此，但要求写明）。`doc.refs.symbols-not-lines` 不是：落地时顺手清了
`docs/09` 那处裸行号，它在旧树上是红的。
"""
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 「## 未发布」段到下一个二级标题为止。刚发完版时这一段是空的，空段不算问题：
# 条目数、超长与缺票号都由这一段自己的内容决定，不该在发版后被当成漏收口。
UNRELEASED = "## 未发布"
ENTRY = re.compile(r"^-\s+(.*)$")
ENTRY_MAX = 80
TICKET = re.compile(r"（#\d+")
FENCE = "```"

# 扫哪些文档：根目录的五份加 docs/ 下的全部 Markdown。跳过三类——
# `docs/清单/` 是脚本生成的；`docs/adr/` 与 `docs/归档/` 记的是当时的位置，
# 基线写在文首或紧随其后，按今天的树去核只会把它们改写掉。
DOC_FILES = ("AGENTS.md", "CLAUDE.md", "README.md", "CONTEXT.md", "CODING_STANDARDS.md")
DOC_SKIP = ("docs/清单/", "docs/adr/", "docs/归档/")

# 反引号外的普通写法也会被扫：`xxx.py:12` 就是裸行号；同一行带 6–40 位十六进制串时
# 视为已注明基线（`行号按改前的 f46cd97`），不再报。
LINE_REF = re.compile(r"[\w./-]*?\.py:\d+")
BASELINE = re.compile(r"\b[0-9a-f]{6,40}\b")
# 左边界：`mytool/run.py` 不能按 `tool/run.py` 核对，那会把坏引用报成好路径。
PATH_REF = re.compile(r"(?<![\w/])(?:tool|gui|tests|recipes)/[\w./-]*?\.py")

# 上报服务的值形态：连接串、库地址、密钥。`service_role` 这个裸词不查——
# 它也是 Postgres 的角色名（`tests/test_error_report.py` 的 `revoke ... from service_role`），
# 真正要拦的是 JWT 形态的 key 本身，anon 与 service_role 入库同样是凭据泄露。
SECRETS = (
    re.compile(r"\bpostgres(?:ql)?://"),
    re.compile(r"\bmysql://"),
    re.compile(r"\bredis://"),
    re.compile(r"[A-Za-z0-9-]+\.supabase\.co"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
)
# 带端口的内网地址不一律报：教程用 `adb pair` / `adb connect` 教用户填自己手机上的地址，
# `recipes/` 记的是当时那台机器的实测（与 `test_source_text` 的「改它们等于改写历史」同口径），
# `tests/` 构造的是脱敏用例的输入。三处都可能出现用户自己的内网 IP，不是本仓库的服务。
PRIVATE_ADDRESS = re.compile(
    r"(?<![\d.])(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2,3}:\d{2,5}")
ADB_EXAMPLE = re.compile(r"\badb\s+(?:pair|connect)\b")
ADDRESS_EXEMPT = ("recipes/", "tests/")

# 前端、Kotlin 与资源文件都是随 App 发出去的，凭据落在那里同样是泄露。
TEXT_SUFFIXES = {".md", ".py", ".toml", ".json", ".yml", ".yaml", ".kts", ".kt", ".java",
                 ".html", ".js", ".css", ".xml", ".txt", ".sh", ".spec", ".cfg", ".ini"}
SKIP_DIRS = {".git", "node_modules", ".venv", "build", "dist", "__pycache__", ".private"}
SKIP_FILES = {"CLAUDE.local.md"}


def rel(path):
    return path.relative_to(ROOT).as_posix()


def doc_paths():
    """要扫的文档。README 与 docs/ 都可能整段被删，删光时调用方要报空转。"""
    paths = [ROOT / name for name in DOC_FILES]
    paths += sorted((ROOT / "docs").rglob("*.md"))
    return [path for path in paths if path.is_file() and not rel(path).startswith(DOC_SKIP)]


def repo_paths():
    """全仓的文本文件。跳过依赖目录与 `CLAUDE.local.md`：后者就是私密信息的落点。"""
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
        for name in sorted(files):
            path = Path(folder) / name
            if name not in SKIP_FILES and path.suffix in TEXT_SUFFIXES:
                yield path


def prose_lines(path):
    """文档里不在围栏代码块内的行。块里贴的是命令与日志输出，不是指代码位置。"""
    in_fence = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith(FENCE):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield lineno, line


def has_baseline(line):
    """同行带 6–40 位十六进制串即视为已注明基线。

    串里要同时有数字与 a–f：纯十进制（`100000`）与纯字母词（`decade`）都凑得出一串
    `[0-9a-f]`，认了会把真行号整行放过。
    """
    for match in BASELINE.finditer(line):
        token = match.group(0)
        if any(char in "abcdef" for char in token) and any(char.isdigit() for char in token):
            return True
    return False


def unreleased_entries(text):
    """`## 未发布` 段里的 [(行号, 条目全文)]；找不到这一段时返回 None。

    缩进续行并入上一条：`- 短行` 下面折一行长文字，Markdown 里仍是同一个列表项，
    只看首行等于放它过。
    """
    lines = text.splitlines()
    try:
        start = lines.index(UNRELEASED)
    except ValueError:
        return None
    entries = []
    for lineno, line in enumerate(lines[start + 1:], start + 2):
        if line.startswith("## "):
            break
        match = ENTRY.match(line)
        if match:
            entries.append((lineno, [match.group(1).rstrip()]))
        elif entries and line[:1] in (" ", "\t") and line.strip():
            entries[-1][1].append(line.strip())
    return [(lineno, " ".join(parts)) for lineno, parts in entries]


class DocGuards(unittest.TestCase):
    def test_doc_changelog_one_line_entry(self):
        """`## 未发布` 段每条挂一个编号、正文不超过 80 字（展开就成段落，把用户说明塞回 CHANGELOG）。

        `### 新增` / `### 修复` / `### 内部` 三个小标题本身不以 `- ` 开头，不参与计数；
        空段通过，刚发完版时它本来就是空的。
        """
        entries = unreleased_entries((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(
            entries, "CHANGELOG.md 里找不到 `## 未发布` 段：新增与修复都要落在这一段里")
        problems = []
        for lineno, entry in entries:
            if len(entry) > ENTRY_MAX:
                problems.append(f"CHANGELOG.md:{lineno}: {len(entry)} 字，超过 {ENTRY_MAX}：{entry}")
            if not TICKET.search(entry):
                problems.append(f"CHANGELOG.md:{lineno}: 没有编号（#123），结尾挂票号或 PR 号：{entry}")
        self.assertEqual(problems, [], "CHANGELOG 条目一行一个编号：\n" + "\n".join(problems))

    def test_doc_refs_symbols_not_lines(self):
        """文档指代码位置用符号名；写行号时同一行要有基线 SHA。

        跳过 `docs/adr/` 与 `docs/归档/`（记的是当时的位置）、`docs/清单/`（生成的），
        以及围栏代码块（贴的是命令与日志输出）；同一行出现 6–40 位十六进制串且含字母时
        即视为已注明基线。
        """
        paths = doc_paths()
        self.assertTrue(paths, "一份文档都没扫到，这条守卫会空转")
        hits = []
        for path in paths:
            for lineno, line in prose_lines(path):
                if has_baseline(line):
                    continue
                for match in LINE_REF.finditer(line):
                    hits.append(f"{rel(path)}:{lineno}: {match.group(0)}（同行没有基线 SHA）")
        self.assertEqual(hits, [], "文档里的行号要带基线，或改用符号名：\n" + "\n".join(hits))

    def test_doc_refs_cleanup_on_move(self):
        """文档里写的 `tool/` `gui/` `tests/` `recipes/` 下的 `.py` 路径必须真的存在。

        守的是「路径没了」这一半：符号搬进另一个仍然存在的文件（`VIVO_MARKETING` 那种）
        与测试注释里的旧路径都看不见，仍靠 grep 与评审。跳过范围与上一条相同：
        ADR 与归档记的旧路径属于历史，改它们等于改写历史。
        """
        paths = doc_paths()
        self.assertTrue(paths, "一份文档都没扫到，这条守卫会空转")
        missing = []
        for path in paths:
            for lineno, line in prose_lines(path):
                for match in PATH_REF.finditer(line):
                    name = match.group(0)
                    if not (ROOT / name).is_file():
                        missing.append(f"{rel(path)}:{lineno}: {name} 不存在")
        self.assertEqual(missing, [], "文档指到的文件不存在，符号可能搬走了：\n" + "\n".join(missing))

    def test_doc_reports_private_infra_stays_local(self):
        """上报服务的连接串、库地址与密钥不进仓库；带端口的内网地址按豁免范围放行。

        `CLAUDE.local.md` 与 `.private/` 目录是它们唯一的落点，两者都不在扫描范围——
        文档里提到这两个路径本身不算违规，说「签名证书放在 `.private/`」不会误报。
        内网地址豁免三类：`adb pair` / `adb connect` 示例行、`recipes/` 与 `tests/`。
        脱敏用例要喂连接串当输入时拼接构造（`"postgres" + "://…"`），与 `test_source_text.py`
        处理零宽字符同一做法：这个文件自己也在扫描范围里，字面量会被自己抓到。
        """
        hits = []
        scanned = 0
        for path in repo_paths():
            name = rel(path)
            scanned += 1
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for pattern in SECRETS:
                    for match in pattern.finditer(line):
                        hits.append(f"{name}:{lineno}: {match.group(0)}")
                if name.startswith(ADDRESS_EXEMPT) or ADB_EXAMPLE.search(line):
                    continue
                for match in PRIVATE_ADDRESS.finditer(line):
                    hits.append(f"{name}:{lineno}: {match.group(0)}")
        self.assertGreater(scanned, 0, "一个文件都没扫到，这条守卫会空转")
        self.assertEqual(hits, [], "内网服务地址与凭据只写在本机 CLAUDE.local.md 或 .private/：\n"
                         + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
