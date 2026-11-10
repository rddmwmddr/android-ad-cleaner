"""规则守卫：文档内容类四条（`DocGuards`）、引擎结构类两条（`EngineGuards`）与流程 / CI 类三条（`CiGuards`），
沿用 #1000、#1002 的做法。

`DocGuards`：CHANGELOG 条目一行一个票号、文档里的代码位置用符号名、指到的 `.py` 路径要存在、
上报服务地址与凭据不写进仓库。`CiGuards`：回归命令与 CI 同一条、`.python-version` 与 Linux job 同版、
两个平台各跑一版解释器。

都只读文件、比字符串：不联网、不执行被测代码、不引入 Markdown 或 YAML 解析依赖。
守的是「仓库现在长什么样」，旧树也绿，守的是不回退（`dev.tests.behaviour-change-needs-red-test`
允许守卫用例如此，但要求写明）。`doc.refs.symbols-not-lines` 不是：落地时顺手清了
`docs/09` 那处裸行号，它在旧树上是红的。

引擎那两条：替换层只读 AST（不 import 手机版的模块，它们依赖只在手机上装得下的库），
结果页喂 `tests/summary_cases.json` 的同一批样例给手机版的 `summarize()`；网页版那条在
`tests/js/client.test.js`，跑的是真实的 `gui/web/index.html`（ADR-0017）。不需要 Android 设备或 JDK。
"""
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "main" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aac_android import view  # noqa: E402
from test_rules_registry import top_level_names  # noqa: E402  同一份「模块层名字」判据，别再抄一份
from tool import events  # noqa: E402

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


TEST_YML = ROOT / ".github/workflows/test.yml"
CLAUDE_MD = ROOT / "CLAUDE.md"
# 回归口径的一条字符串：CLAUDE.md 与本机、CI 都是这一条，只差外面包的 coverage 收集。
REGRESSION = "-m unittest discover -s tests"
# Windows job 的版本只能钉在这里：Linux 侧跟着 `.python-version` 走，Windows 侧与发版打包同版，
# 没有第二份文件写着它。升版本时 workflow 与这一行一起改，正是这条守卫要的显式动作。
WINDOWS_PYTHON = "3.12"


def workflow_jobs(path):
    """`jobs:` 下每个一级键与它的整段文本：[(名字, 段)]。缩进扫描，不引入 YAML 依赖。

    job 的判据是缩进等于 `jobs:` 下一级第一列的键；`runs-on` / `steps` / `with:` 这些子键
    比它深，不会误当成 job。注释行不进段文本，免得说明里的版本号与命令算数。
    """
    jobs, inside, indent, current, lines = [], False, None, None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not inside:
            if line.rstrip() == "jobs:":
                inside = True
            continue
        if stripped and not stripped.startswith("#") and not line.startswith(" "):
            break                                       # 回到顶层键，jobs 段结束
        key = re.match(r"^(\s+)([A-Za-z0-9_-]+):\s*$", line)
        if key and indent is None:
            indent = len(key.group(1))
        if key and len(key.group(1)) == indent:
            if current is not None:
                jobs.append((current, "\n".join(lines)))
            current, lines = key.group(2), []
            continue
        if current is not None and not stripped.startswith("#"):
            lines.append(line)
    if current is not None:
        jobs.append((current, "\n".join(lines)))
    return jobs


def job_field(block, key):
    """job 段里 `key: value` 的值，去掉引号；没有这个键返回 None。"""
    match = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", block, re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else None


class CiGuards(unittest.TestCase):
    """流程与 CI 类三条：回归命令只写一处口径、解释器版本三处一致、两个平台各跑一版。"""

    def setUp(self):
        self.jobs = workflow_jobs(TEST_YML)

    def unittest_jobs(self):
        """跑回归的 job：`run:` 里出现同一条 discover 的那些。"""
        return [(name, block) for name, block in self.jobs if REGRESSION in block]

    def pinned(self):
        return (ROOT / ".python-version").read_text(encoding="utf-8").strip()

    def test_dev_tests_regression_command(self):
        """CLAUDE.md 的「回归：」那一行与 CI 的 unittest job 是同一条发现口径。

        改一边不改另一边时，agent 照正文跑出的是一串 `ModuleNotFoundError` 或者跑错目录。
        """
        lines = [line for line in CLAUDE_MD.read_text(encoding="utf-8").splitlines()
                 if "<!-- rule:dev.tests.regression-command -->" in line]
        self.assertEqual(len(lines), 1,
                         "CLAUDE.md 里要有且只有一行挂 `<!-- rule:dev.tests.regression-command -->`")
        self.assertIn(REGRESSION, lines[0], "CLAUDE.md 的回归命令与 CI 不再是同一条")
        runs = self.unittest_jobs()
        self.assertTrue(runs, f"test.yml 里没有跑 `{REGRESSION}` 的 job，这条守卫会空转")
        for name, block in runs:
            self.assertIn(REGRESSION, block, f"job {name} 的 run 不是 `{REGRESSION}`")

    def test_dev_tests_interpreter_version(self):
        """`.python-version` 与 CI 里跑 unittest 的 Linux job 是同一版。

        两版混跑会让 CLI 逐字节对拍本地绿、CI 红（3.13 起编译器剥掉文档字符串的公共缩进）。
        """
        pinned = self.pinned()
        self.assertRegex(pinned, r"^\d+\.\d+$", ".python-version 要写成 `3.13` 这种形态")
        linux = [(name, block) for name, block in self.unittest_jobs()
                 if job_field(block, "runs-on") == "ubuntu-latest"]
        self.assertTrue(linux, "test.yml 里没有跑 unittest 的 ubuntu job，这条守卫会空转")
        for name, block in linux:
            self.assertEqual(job_field(block, "python-version"), pinned,
                             f"job {name} 的解释器与 .python-version 不一致")

    def test_dev_ci_two_interpreters(self):
        """两个平台各跑一版解释器：ubuntu 跟 `.python-version`，windows 钉 `WINDOWS_PYTHON`。

        把 Windows job 删掉或换成同一个解释器时立刻红——「两版其实一样」这件事要显式改守卫。
        """
        runs = {(job_field(block, "runs-on"), job_field(block, "python-version"))
                for _, block in self.unittest_jobs()}
        self.assertIn(("ubuntu-latest", self.pinned()), runs,
                      f"没有 ubuntu × {self.pinned()} 的回归 job，读到的是 {sorted(runs)}")
        self.assertIn(("windows-latest", WINDOWS_PYTHON), runs,
                      f"没有 windows × {WINDOWS_PYTHON} 的回归 job，读到的是 {sorted(runs)}")


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


# 手机版的替换层（ADR-0019）：这四个文件把引擎接到手机上，少一个或导出名改了，桌面版测试全绿
# 而手机版起不来。清单是模块层不带下划线的名字——加新名字不红，删或改名会红；改它等于改
# ADR-0019 的边界。main.py / screen.py / updates.py / view.py 是手机版自己的东西，不在这层。
ANDROID = ROOT / "android" / "app" / "src" / "main" / "python" / "aac_android"
REPLACEMENT_LAYER = {
    "adb.py": ("ADB_PATH", "NOT_READY", "SERIAL", "VERSION_TEXT", "answer", "install"),
    "bridge.py": ("AdbBridge", "MONKEY", "Result", "SLOW", "ShizukuBridge", "get", "launcher",
                  "prepare", "slow"),
    "inproc.py": ("EXECUTABLE", "Proc", "Runner", "TOOL", "after_run", "call", "interrupt", "setup",
                  "top"),
    "u2.py": ("ATTR", "AccessibilityServiceAlreadyRegisteredError", "AdbError", "AdbShellError",
              "BaseError", "ConnectError", "Device", "DeviceBusyError", "DeviceError", "EMPTY_XML",
              "FLAGS", "HTTPError", "HTTPTimeoutError", "HierarchyEmptyError", "KEYS",
              "LaunchUiAutomationError", "NormalError", "RPCError", "RPCInvalidError",
              "RPCUnknownError", "Selector", "ShellResponse", "UiAutomationError",
              "UiAutomationNotConnectedError", "UiObject", "UiObjectNotFoundError", "bounds_of",
              "connect", "display", "install", "matches", "read_failed", "select_all", "text_of"),
}

# 结果页要挡住的机器行记号：唯一来源是 tool/events.py 的两个前缀，它们的公共前缀就是两处
# summarize() 该剥掉的那一段。手机版与网页版都只能写死这个字面量（屏幕上没有 tool/ 可 import），
# 由本文件把它和 events.py 拴住：改前缀而不同步，这条与样例的漂移检查都会红。
MACHINE_TOKEN = os.path.commonprefix([events.PREFIX, events.PAYLOAD_PREFIX])


class EngineGuards(unittest.TestCase):
    def test_ui_result_line_routing(self):
        """结果页的摘要不许出现引擎的机器行（`tool/events.py` 的 PREFIX / PAYLOAD_PREFIX）。

        两条同口径用例：本条（`EngineGuards.test_ui_result_line_routing`）喂 `aac_android/view.py`
        的 `summarize()`，`tests/js/client.test.js` 的「完成页摘要把机器行挡在外面（#1002）」
        真跑 jsdom 里 `gui/web/index.html` 的同名函数；两端读同一份 `tests/summary_cases.json`。
        `gui/app.py` 的 `_log()` 今天已经把两类行挡在外面，但只要有一处漏进 `tail`，用户看到的
        就是 `#aac:payload {"…"}`——两处 summarize 各自再剥一次。期望串本身由
        `tests/test_android_view.py::SummarizeTest.test_shared_cases_with_web_client` 守，这里只管漏没漏。
        """
        cases = json.loads((ROOT / "tests" / "summary_cases.json").read_text(encoding="utf-8"))
        self.assertTrue(cases, "一份样例都没有，这条守卫会空转")
        fixtures = [line for case in cases for line in case.get("machine", [])]
        self.assertTrue(fixtures, "样例里一条机器行都没有，这条守卫吵不到任何人")
        self.assertEqual(view.MACHINE_PREFIX, MACHINE_TOKEN,
                         "手机版剥掉的记号要和 tool/events.py 的前缀对得上")
        stray = [line for line in fixtures if not line.startswith(MACHINE_TOKEN)]
        self.assertEqual(stray, [],
                         f"样例里的机器行要以 {MACHINE_TOKEN!r} 开头"
                         "（前缀的唯一来源是 tool/events.py）：\n" + "\n".join(stray))
        for case in cases:
            with self.subTest(case=case["name"]):
                got = view.summarize({"tail": list(case["tail"]) + list(case.get("machine", []))})
                leaked = [line for line in got.splitlines() if line.startswith(MACHINE_TOKEN)]
                self.assertEqual(leaked, [], "结果页不能显示引擎的机器行")
        for line in (events.PREFIX + '{"kind": "ui_busy"}',
                     events.PAYLOAD_PREFIX + '{"skeleton": "<node text=…>"}'):
            self.assertEqual(view.summarize({"tail": ["开始执行", line]}), "开始执行",
                             "按 events.py 的两个前缀现造的机器行也要挡住")

    def test_android_replacement_layer(self):
        """`aac_android/` 的替换层四个文件都在，模块层的公开名字一个都不能少（ADR-0019）。

        旧树也绿，守的是不回退：冻结清单是模块层不带下划线的名字，加新名字不红，删或改名会红。
        改它等于改 ADR-0019 的边界；正文那句「新增读屏能力要先加进 `u2.py` 与 `tool/reader.py`
        两边」这条守卫看不见。本仓库没有 JDK / Android SDK，它也证明不了 APK 跑得起来。
        """
        problems = []
        for name, frozen in sorted(REPLACEMENT_LAYER.items()):
            path = ANDROID / name
            if not path.is_file():
                problems.append(f"aac_android/{name} 不存在")
                continue
            absent = sorted(set(frozen) - top_level_names(path))
            if absent:
                problems.append(f"aac_android/{name} 少了 {'、'.join(absent)}")
        self.assertEqual(problems, [], "替换层少了文件或导出名，手机会在打包后才暴露：\n"
                         + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
