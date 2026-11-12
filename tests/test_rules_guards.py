"""规则守卫：文档内容类四条（`DocGuards`）、注册表类一条（`RegistryGuards`）、引擎结构类两条（`EngineGuards`）、
手机版界面一条（`AndroidGuards`）、流程 / CI 类三条（`CiGuards`）、夹具装配类两条（`FixtureGuards`）、
桩与断言两条（`StubGuards`）、发版产物一条（`ReleaseGuards`）、标准流一条（`StdioGuards`）与
`gh` 会话一条（`GhGuards`），沿用 #1000、#1002 的做法。

`DocGuards`：CHANGELOG 条目一行一个票号、文档里的代码位置用符号名、指到的 `.py` 路径要存在、
上报服务地址与凭据不写进仓库。`RegistryGuards`：无锚点的顶层列表项按文档冻结上限。
`AndroidGuards`：手机版页面状态只由 `AppModel.show()` 改写。`CiGuards`：回归命令与 CI 同一条、
`.python-version` 与 Linux job 同版、两个平台各跑一版解释器。`FixtureGuards`：`tests/` 里绕过
`fixtures.phone_stub()` 手搓假 `Phone` 的文件按清单冻结。`StubGuards`：`with patch(...) as X`
之后函数体里没再用过 `X` 的哑桩。

都只读文件、比字符串或解析 AST：不联网、不执行被测代码、不引入 Markdown 或 YAML 解析依赖。
守的是「仓库现在长什么样」，旧树也绿，守的是不回退（`dev.tests.behaviour-change-needs-red-test`
允许守卫用例如此，但要求写明）。三条不是：`doc.refs.symbols-not-lines` 落地时顺手清了
`docs/09` 那处裸行号，`dev.android.screen-state` 随之修了 `AppModel.start()` 那处直写，
`FixtureGuards` 落地时把那两个机型用例的本地假类换成了 `phone_stub()`，三条在旧树上是红的。

引擎那两条：替换层只读 AST（不 import 手机版的模块，它们依赖只在手机上装得下的库），
结果页喂 `tests/summary_cases.json` 的同一批样例给 `tool/summary.py` 的 `summarize()`——两个宿主
调的就是这一份（#1189）。网页版只剩「按后端字段渲染」的断言，跑真实的 `gui/web/index.html`
（ADR-0017）。不需要 Android 设备或 JDK。

发版产物那一条读 `index.html` 的源码：解析只走 `tool/release_assets.py`（定时 job 用同一份），
不联网、不需要 GitHub 凭据；与真实 Release 的名字、大小、sha 比对在 `.github/workflows/release-assets.yml`。
"""
import ast
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "main" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aac_android import view  # noqa: E402
from test_rules_registry import ANCHOR as RULE_ANCHOR  # noqa: E402  同一份锚点口径，别再抄一份
from test_rules_registry import read_rows, top_level_names  # noqa: E402
from tool import events, release_assets, summary  # noqa: E402

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
        """跑回归的 job。

        按 `unittest discover` 认，不按完整的回归命令认：按后者筛出来的 job 再断言它含那句话
        是恒真的，把 `-s tests` 改成 `-s test` 反而筛不到任何 job、三种结局都报成「空转」。
        """
        return [(name, block) for name, block in self.jobs if "unittest discover" in block]

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


class ReleaseWorkflowGuards(unittest.TestCase):
    """发版动作只认显式的 tag（#1115）：推 tag 不触发构建，main 与已打的 tag 之间没有关系。"""

    def text(self):
        path = ROOT / ".github/workflows/build-windows.yml"
        self.assertTrue(path.is_file(), f"{path} 不在，这条守卫会空转")
        return path.read_text(encoding="utf-8")

    def test_build_windows_only_by_dispatch_with_tag(self):
        """不再由 `push: tags` 触发：tag 一推就自动出包，等于又回到「发版绑 main 尖端」的老路。

        只留 `workflow_dispatch`，owner 发版时显式填要打的那个 tag。
        """
        text = self.text()
        self.assertNotRegex(text, r"(?m)^\s{2}push:", "build-windows 不该再由 push 触发")
        self.assertIn("workflow_dispatch:", text, "build-windows 要保留手动触发入口")
        self.assertIn("tag:", text, "workflow_dispatch 要收一个 tag 输入")

    def test_build_windows_checks_out_the_tag(self):
        """手动触发时 checkout 必须钉到 `refs/tags/<输入>`。

        不写 `ref` 时它取默认分支，也就是 main 尖端——打包出来的产物与 tag 无关。
        """
        self.assertIn("ref: refs/tags/${{ inputs.tag }}", self.text(),
                      "build-windows 的 checkout 必须显式 fetch 输入的 tag")

    def test_missing_release_does_not_fail_the_build(self):
        """Release 草稿还不存在时只跳过上传：owner 可能先跑构建、后建草稿。"""
        self.assertNotIn("请先创建对应的 Release 草稿", self.text(),
                         "Release 不存在不该让构建失败，产物留在 artifact 里即可")


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


# 顶层列表项：缩进 0–3 列的 `-` / `*` / `+` / `1.` / `1)` 加空白加非空正文。
# 缩进 ≥4 的是嵌套子项，不在候选集里——`CODING_STANDARDS.md` 里被合并成一条规则的 9 条子项就是这样排除的。
# 2–3 列的嵌套子项按 CommonMark 仍算文档级列表项，会一并计数（现有 5 处，已含在底数里）。
ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d+[.)])\s+\S")
# `- - -` / `* * *` 也落在 ITEM 的形状里，但它们是水平分隔线。
THEMATIC = re.compile(r"^[-*_](?:\s*[-*_]){2,}$")

# 每份文档「无锚点顶层列表项」的条数上限，是 #840 起的存量，只许降。上限 0 的也列出来，
# 让这份表就是注册表文档的全集。涨一个必须在这里改数字：那是一次公开的「我往正文里加了东西
# 却没登记规则」，评审要看见。注册表里新出现的文档默认 0（有列表项就红），要给余量才显式入表。
UNANCHORED_BOUND = {
    "CLAUDE.md": 4,
    "CODING_STANDARDS.md": 9,
    "CONTEXT.md": 0,
    "docs/04-给新机型写脚本.md": 11,
    "docs/agents/code-review.md": 3,
    "docs/agents/domain.md": 2,
    "docs/agents/issue-tracker.md": 20,
    "docs/agents/release-followup.md": 0,
    "docs/agents/release.md": 13,
    "docs/agents/triage-labels.md": 0,
    # ADR 是设计记录的落点：里面的条目是当时的决定，不是要追的规则，所以余量按落地时的实数
    # 冻结。#1219 起 ADR 第一次成为注册表 source（`dev.gh.single-session` 的出处），这一条
    # 就是那次落地时它有的 15 条；再往这份 ADR 里加决定时这一行要跟着改，评审才看得见。
    "docs/adr/0036-tool-gh-session.md": 15,
}


def unanchored_items(path, ids):
    """[(行号, 行)]：顶层列表项里行尾没有登记锚点的那些。

    锚点要落在条目行尾且 id 在注册表里（`RULE_ANCHOR` 与 `test_rules_registry` 同一份口径）：
    模板里引用锚点写法时后面还接着正文，那不是登记。
    """
    found = []
    for lineno, line in prose_lines(path):
        if THEMATIC.match(line.strip()):
            continue
        if not ITEM.match(line):
            continue
        match = RULE_ANCHOR.search(line)
        if match and match.group(1) in ids:
            continue
        found.append((lineno, line.strip()))
    return found


class RegistryGuards(unittest.TestCase):
    def test_unanchored_items_stay_within_the_frozen_bound(self):
        """每份文档里没挂锚点的顶层列表项不许超过冻结上限（#840、#1010）。

        `test_rules_registry` 的四条不变式只看「带锚点的」：一条规则写进正文、根本没人给它锚点，
        四条全绿。这里按文档冻结尾数，新增一条不带锚点的列表项就超线。旧树也绿，守的是不回退。

        报错列出该文档**全部**无锚点项的行号与首 80 字，不只列超出的尾部：新项可能插在中间，
        列尾部会指到别的行。

        已知漏口（不宣称已闭合）：删一条再加一条、或把一根已有的无锚点项原地改写成规则，总数不变，
        计数看不见——现存的无锚点项绝大多数落在已有锚点的小节里，是已登记规则的展开，评审能对照。
        缩进 ≥4 的嵌套子项不在候选集里；2–3 列的按 CommonMark 仍算文档级列表项，会一并计数
        （现有 5 处，已含在底数里），往这类子项里加一条也会红。
        """
        try:
            rows = read_rows()
        except (OSError, ValueError) as error:
            self.fail(f"读不出 docs/agents/rules.toml：{error}")
        self.assertTrue(rows, "注册表一条都没有，这条守卫会空转")
        ids = {row["id"] for row in rows}
        problems, scanned = [], 0
        for name in sorted({row["source"].split("#")[0] for row in rows}):
            path = ROOT / name
            if not path.is_file():
                continue                                # 由 test_rules_registry 的第一条不变式报
            scanned += 1
            bound = UNANCHORED_BOUND.get(name, 0)
            items = unanchored_items(path, ids)
            if len(items) <= bound:
                continue
            detail = "\n".join(f"  {name}:{lineno}: {text[:80]}" for lineno, text in items)
            problems.append(f"{name}: 上限 {bound}，实测 {len(items)}；无锚点的顶层列表项：\n{detail}")
        self.assertGreater(scanned, 0, "一份文档都没扫到，这条守卫会空转")
        self.assertEqual(problems, [], "正文里新增了没挂锚点的列表项；给它挂 `<!-- rule:<id> -->` "
                         "并登记进 docs/agents/rules.toml，或确认它是流程步骤后把上限显式调高：\n"
                         + "\n".join(problems))


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

# 结果页要挡住的机器行记号：唯一来源是 tool/events.py 的两个前缀，它们的公共前缀就是摘要函数
# （tool/summary.py）该剥掉的那一段。两个宿主调同一份实现，由本文件把它和 events.py 拴住：
# 改前缀而不同步，这条与样例的漂移检查都会红。
MACHINE_TOKEN = os.path.commonprefix([events.PREFIX, events.PAYLOAD_PREFIX])


class EngineGuards(unittest.TestCase):
    def test_ui_result_line_routing(self):
        """结果页的摘要不许出现引擎的机器行（`tool/events.py` 的 PREFIX / PAYLOAD_PREFIX）。

        喂 `tool/summary.py` 的 `summarize()`（两个宿主共用，ADR-0019 的增补段）。`gui/app.py` 的
        `_log()` 今天已经把两类行挡在外面，但只要有一处漏进 `tail`，用户看到的就是
        `#aac:payload {"…"}`——摘要函数自己再剥一次。期望串本身由 `tests/test_summary.py` 的
        共享样例集守，这里只管漏没漏。
        """
        cases = json.loads((ROOT / "tests" / "summary_cases.json").read_text(encoding="utf-8"))
        self.assertTrue(cases, "一份样例都没有，这条守卫会空转")
        fixtures = [line for case in cases for line in case.get("machine", [])]
        self.assertTrue(fixtures, "样例里一条机器行都没有，这条守卫吵不到任何人")
        self.assertEqual(summary.MACHINE_PREFIX, MACHINE_TOKEN,
                         "摘要函数剥掉的记号要和 tool/events.py 的前缀对得上")
        self.assertEqual(view.FALLBACK_MACHINE_PREFIX, MACHINE_TOKEN,
                         "工具目录不可用时手机版的兜底记号也要和事件前缀对得上")
        stray = [line for line in fixtures if not line.startswith(MACHINE_TOKEN)]
        self.assertEqual(stray, [],
                         f"样例里的机器行要以 {MACHINE_TOKEN!r} 开头"
                         "（前缀的唯一来源是 tool/events.py）：\n" + "\n".join(stray))
        for case in cases:
            with self.subTest(case=case["name"]):
                got = summary.summarize({"tail": list(case["tail"]) + list(case.get("machine", []))})
                leaked = [line for line in got.splitlines() if line.startswith(MACHINE_TOKEN)]
                self.assertEqual(leaked, [], "结果页不能显示引擎的机器行")
        for line in (events.PREFIX + '{"kind": "ui_busy"}',
                     events.PAYLOAD_PREFIX + '{"skeleton": "<node text=…>"}'):
            self.assertEqual(summary.summarize({"tail": ["开始执行", line]}), "开始执行",
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


TESTS = ROOT / "tests"
# `Phone` 的装配只此一处（CLAUDE.md 的 `dev.tests.fixtures-single-assembly`）：直接构造
# `Phone` / `FakePhone` 的文件集合冻结在这里，只许减不许增。豁免理由见对应用例的 docstring。
PHONE_CONSTRUCTED = ("Phone", "FakePhone")
PHONE_CONSTRUCTION_FROZEN = {
    "fixtures.py",              # 装配的唯一定义处：今天走 Phone.__new__，命中不到，留给改用构造器之后
    "test_engine_events.py",    # 刻意构造真 Phone 触发构造期失败（以下三份同）
    "test_lock_and_disconnect_regressions.py",
    "test_ui_session.py",
    "test_harmony_client.py",   # 鸿蒙引擎自己的 Phone 类（hdc 传输，ADR-0019）
    "test_harmony_engine.py",
    "test_phone_interface.py",  # 测的就是 Phone 本体
}
PHONE_CLASS_FROZEN = {
    "test_adb_link.py",         # OldShellPhone 是旧 Connection.shell 的回放副本，改前改后对拍用
    "test_harmony_client.py",   # 鸿蒙引擎自己的 Phone 类（ADR-0019）
    "test_harmony_engine.py",
}


def python_sources():
    """`tests/` 下的 Python 源文件，跳过 `__pycache__`。"""
    for path in sorted(TESTS.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


def called_name(node):
    """`f(...)` 的被调名：`Phone` 取裸名、`fast.Phone` 取属性名；其它形态返回 None。"""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def phone_constructors():
    """{相对 tests/ 的路径: [行号]}：名字逐字是 `Phone` / `FakePhone` 的调用。"""
    found = {}
    for path in python_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and called_name(node) in PHONE_CONSTRUCTED:
                found.setdefault(path.relative_to(TESTS).as_posix(), []).append(node.lineno)
    return found


def phone_classes():
    """{相对 tests/ 的路径: [(类名, 行号)]}：名字是 `Phone` 或以 `Phone` 结尾的类定义。"""
    found = {}
    for path in python_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Phone"):
                found.setdefault(path.relative_to(TESTS).as_posix(), []).append((node.name, node.lineno))
    return found


def hit_text(hit):
    """命中点的可读形态：构造点是行号，类定义是 `类名@行号`。"""
    return f"{hit[0]}@{hit[1]}" if isinstance(hit, tuple) else str(hit)


def freeze_report(found, frozen, summary):
    """冻结清单的报告：清单外的文件逐条列出命中点；全部在清单内时返回 None。"""
    extra = {name: hits for name, hits in found.items() if name not in frozen}
    if not extra:
        return None
    lines = [f"  tests/{name}: {', '.join(hit_text(hit) for hit in sorted(hits))}"
             for name, hits in sorted(extra.items())]
    return f"{summary}：\n" + "\n".join(lines)


class FixtureGuards(unittest.TestCase):
    """`tests/` 里的 Phone 装配：构造点与本地假类都按文件集合冻结，只许减不许增。"""

    def test_phone_is_assembled_only_in_fixtures(self):
        """直接构造 `Phone` / `FakePhone` 的文件集合 ⊆ `PHONE_CONSTRUCTION_FROZEN`。

        装配只此一处（CLAUDE.md 的 `dev.tests.fixtures-single-assembly`）：手搓的假 Phone 只实现
        被用到的那几个属性，`Phone.__init__` 新增一个构造期字段时那份拷贝不会跟着长，引擎与夹具
        会各自漂移，两者对拍出来的「一致」也就不证明任何事。新用例要用 `phone_stub()`。

        冻结的是文件集合而不是处数：清单内的文件都是已解释的豁免形态，继续多造几个点的风险
        低于多出一个绕开装配的文件。清单只许减——修好一处就从这里删掉文件名，不会因此在红。

        豁免四类：`fixtures.py` 是装配的唯一定义处；`test_phone_interface.py` 测的就是 `Phone` 本体；
        `test_engine_events.py` / `test_lock_and_disconnect_regressions.py` / `test_ui_session.py` 刻意构造真 `Phone`
        去触发 `connect` / `__init__` 的失败路径，`phone_stub()` 绕开构造期，用不了；
        `test_harmony_engine.py` / `test_harmony_client.py` 是鸿蒙引擎自己的 `Phone` 类（hdc 传输，
        ADR-0019），与 `fast.Phone` 的装配不是一件事。

        已知漏口：判据认类名，`getattr(fast, "Phone")("x")` 或别名 `P = fast.Phone; P("x")` 能绕过；
        `fast.Phone.__new__(fast.Phone)` 同样看不见，而 `fixtures.py` 的装配正是这么写的（它要绕开
        构造期），照抄它等于绕过这条守卫。
        守卫也不看 `phone_stub()` 本身（把它换成返回 Mock 照样绿）：它守的是调用点在哪。
        真要做等价改写时评审看得见 diff，不为它加数据流分析。
        """
        found = phone_constructors()
        self.assertTrue(found, "tests/ 里一个 Phone 构造点都没扫到，这条守卫会空转")
        problem = freeze_report(found, PHONE_CONSTRUCTION_FROZEN,
                                "这些文件直接构造了 Phone / FakePhone，绕过 fixtures.phone_stub()")
        self.assertIsNone(problem, problem)

    def test_no_new_local_phone_classes(self):
        """`tests/` 里名字以 `Phone` 结尾的类定义只许留在这三份文件（ADR-0019、#1021）。

        判据取「名字以 `Phone` 结尾」：`class TinyPhone:` 这种没有基类的假替身也照样拦得住
        （只认「继承了 Phone」会漏掉它）。`PhoneStubTests` / `PhoneBootTests` / `FakePhoneTests`
        是 unittest 的用例类，不以 `Phone` 结尾，不进候选集。

        三份豁免都不是 `fast.Phone` 的装配：`test_harmony_engine.py` 与 `test_harmony_client.py`
        造的是鸿蒙引擎自己的 `Phone`（hdc 传输，ADR-0019 的第二个执行宿主）；`test_adb_link.py`
        的 `OldShellPhone` 是旧 `Connection.shell` 的回放副本，改前改后对拍要用它。

        已知漏口与上一条相同：`class FakePhoneStub:` 这种不落在「以 Phone 结尾」的形状里，
        `Phone.__new__(Phone)` 手搓出来的对象也算不上一个类，两条都看不见——评审看得见 diff。
        """
        found = phone_classes()
        self.assertTrue(found, "tests/ 里一个 Phone 类都没扫到，这条守卫会空转")
        problem = freeze_report(found, PHONE_CLASS_FROZEN,
                                "这些文件定义了本地的 Phone 类，改用 fixtures.phone_stub()")
        self.assertIsNone(problem, problem)


# 桩住协作方就要用它（`dev.tests.stub-and-assert`、#1022）：`with patch(...) as X` 之后，
# 函数体里必须再提到 X——断言、`X.called`、`X.return_value`、交给调用方都算。绑了名却从头
# 到尾没再用，协作方的调用点被改成前向壳之后它照样绿，那才是哑桩。豁免按
# (文件, 函数, 名字) 冻结；今天为空——判据只认「从头到尾没再用」，没有需要放行的形态。
STUB_ALLOW = set()


def scope_nodes(roots):
    """从 `roots` 起的节点流，不进入嵌套的 def / lambda / class（它们有自己的局部名）。

    过滤放在出栈处而不是入栈处：`func.body` 顶层直接写的嵌套 `def` 也是根之一，
    只在入栈时过滤会让它连同里面绑的桩一起算到外层函数头上。
    """
    stack, out = list(roots), []
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def patches(node):
    """`patch(...)` 或 `patch.object(...)` 的调用；`patch.dict` 等其它形态不在判据内。"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "patch"
    return (isinstance(func, ast.Attribute) and func.attr == "object"
            and isinstance(func.value, ast.Name) and func.value.id == "patch")


def patch_bound_names(func):
    """[(名字, 行号)]：函数自身作用域里 `with patch(...) as NAME` 绑定的名字。"""
    found = []
    for node in scope_nodes(func.body):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            if isinstance(item.optional_vars, ast.Name) and patches(item.context_expr):
                found.append((item.optional_vars.id, node.lineno))
    return found


def uses_patch(func, name):
    """`as` 之后还有没有提到这个桩：任何位置以读的方式出现即算（断言、`.called`、`return_value`、交接）。

    `as NAME` 里的那次绑定是 `Store`，不算「用过」——正因为它是唯一一次出现才判哑桩。
    这一处刻意进入嵌套函数与 lambda：桩被闭包用掉也是用掉了，按作用域切开会把
    `callback = lambda: spy.assert_called_once()` 这类写法误判成哑桩。
    """
    return any(isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
               for node in ast.walk(func))


def unobserved_stubs(source, filename, allow=STUB_ALLOW):
    """([`文件:行号 函数 <- 名字`], 桩总数)：绑了名却从没再用过的桩。"""
    hits, bound = [], 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for name, lineno in patch_bound_names(node):
            bound += 1
            if (filename, node.name, name) in allow or uses_patch(node, name):
                continue
            hits.append(f"{filename}:{lineno} {node.name} <- {name}")
    return hits, bound


# 合成样例：`dumb_stub` 绑了名从头到尾没用（哑桩），其余各式都该绿——`assert_*`、
# `X.called`、把桩交给调用方、在闭包里用它。`outer` / `inner` 证明嵌套函数绑的桩记在
# 它自己名下，不算到外层。字符串字面量不是真代码，守卫扫不到它。
STUB_SAMPLE = """
def dumb_stub(self):
    with patch("m.other") as spy:
        run()

def loud_stub(self):
    with patch("m.other") as spy:
        run()
    spy.assert_called_once()

def negative_stub(self):
    with patch("m.other") as out:
        run()
    self.assertFalse(out.called)

def config_stub(self):
    with patch("m.other") as spy:
        run()
    self.spy = spy

def nested_use(self):
    with patch("m.other") as spy:
        callback = lambda: spy.assert_called_once()
    self.callback = callback

def outer(self):
    with patch("m.a") as a:
        run()
    def inner():
        with patch("m.b") as b:
            run()
    return a
"""


class StubGuards(unittest.TestCase):
    def test_patched_collaborators_are_used(self):
        """`with ... as X` 之后函数体里必须再提到 X，否则就是哑桩（`dev.tests.stub-and-assert`、#1022）。

        现场是 `via_app_page` 被改成一行前向壳之后：四处 `patch` 成了哑桩，其中三处继续绿，
        只有 `assert_called_once()` 把它们暴露出来。旧树也绿，守的是不回退。

        「用过」按机械可判的宽形态算：`X.assert_*`（含 `assert_not_called`）、`X.call_args*` /
        `call_count` / `mock_calls`、`X.called`、配置 `X.return_value`、`self.x = X` 交接、
        `for stub in (…, X, …)` 收集后统一断言——凡是以读的方式提到 X 都算。`patch("builtins.print")`
        这类静音器没有 `as`，`patch.object(x, y, return_value=…)` 不绑名，都不进判据。

        #1022 票面按一个只认四条断言形态的正则量到「2 处」；那个正则漏了多参数 `patch.object`、
        单引号与「收集后统一断言」的写法。按本条判据重算（每个函数自身作用域里的 `as NAME`
        绑定）：`tests/` 全库 14 处、13 个函数、6 份文件，全部有后续使用，没有真哑桩。
        票面设想的豁免（`test_adapt_cli.py` 的 `run_cmd <- factory`、`forward <- shell`）
        都是 `self.factory = factory` 形态，按本条判据本来就绿，所以 `STUB_ALLOW` 今天为空。

        已知漏口：只认裸名 `patch(...)` / `patch.object(...)`，`unittest.mock.patch(...)` 这类
        限定名、`patcher.start()`、`@patch(...)` 装饰器传参、`patch.multiple` 都不在判据内
        （仓库今天没有这几种形态，引入时扩判据并补用例）；`as` 的目标是属性（`as self.x`）
        时既不计数也不判；「用过」不区分「断言了调用」与「只配了返回值」——桩被配置成返回
        mock、协作方却已不调用它时仍会绿，那类要 `assert_called_once()`，本守卫看不到；
        名字被重新赋值（`spy = obj()`）后再读也算「用过」，同理漏报；它也不检查
        `assert_called_once_with` 的实参写对没有。
        """
        hits, bound = [], 0
        for path in python_sources():
            found, count = unobserved_stubs(path.read_text(encoding="utf-8"),
                                            path.relative_to(TESTS).as_posix())
            hits.extend(found)
            bound += count
        self.assertGreater(bound, 0, "tests/ 里一个 `patch(...) as name` 都没扫到，这条守卫会空转")
        self.assertEqual(hits, [], "桩住协作方就要用它；`as` 绑了名却从没再提到的桩，"
                         "协作方的调用点被改掉时它们照样绿：\n" + "\n".join(hits))

    def test_judgement_and_exemptions(self):
        """判据本身：只用绑定的名字才红；断言 / `.called` / 交接 / 闭包都算用过；豁免点名即跳过（#1022）。"""
        hits, bound = unobserved_stubs(STUB_SAMPLE, "sample.py")
        self.assertEqual(bound, 7, "合成样例的桩没扫全，这条用例就测不到判据")
        self.assertEqual(hits, ["sample.py:3 dumb_stub <- spy", "sample.py:30 inner <- b"],
                         "哑桩要红；断言 / `.called` / 交接 / 闭包四种形态不该被误伤")
        self.assertFalse(any(" outer <- " in line for line in hits),
                         "嵌套函数绑的桩要记在它自己名下，不能算到外层函数头上")
        one = 'def one():\n    with patch("m.x") as spy:\n        go()\n'
        self.assertEqual(unobserved_stubs(one, "sample.py")[0], ["sample.py:2 one <- spy"])
        self.assertEqual(unobserved_stubs(one, "sample.py",
                                          allow={("sample.py", "one", "spy")})[0], [],
                         "豁免清单点到的要跳过，否则清单是摆设")


ANDROID_SRC = ROOT / "android"
# 页面状态的写点：`screen =`（可带 `this.`），不要求落在行首——`if (c) screen = Screen.Home`
# 这种同行写法同样是换页。左边界排除标识符与 `.`：`myScreen =` 与 `foo.screen =` 不是这个字段。
# `(?!=)` 放过 `screen == Screen.X` 这类比较；声明 `var screen by mutableStateOf(...)` 里没有 `=`，本来就不匹配。
SCREEN_WRITE = re.compile(r"(?<![\w.])(?:this\.)?screen\s*=(?!=)")
# 唯一允许的写点：`show()` 体内。`private fun show(` 起点的后 3 行内，
# 与「换页都经过 AppModel 的方法」同一条不变量（ADR-0018）。
SHOW_DECL = re.compile(r"^\s*private fun show\((\w+: )?Screen\)\s*\{")
SHOW_SPAN = 3
SHOW_OWNER = "AppModel.kt"


def kt_files():
    """`android/` 下的 Kotlin 源文件，含 `debug/`、`test/` 源集。

    跳过构建产物与隐藏目录（与 `test_test_collection` 同一份 `SKIP_DIRS` 口径）：
    本机构建过的树里 `android/app/build` 可能有生成的 `.kt`，那不是要守的源。
    """
    for path in sorted(ANDROID_SRC.rglob("*.kt")):
        parts = path.relative_to(ANDROID_SRC).parts[:-1]
        if any(part in SKIP_DIRS or part.startswith(".") for part in parts):
            continue
        yield path


def screen_write_offenders():
    """[(相对路径, 行号, 行文本)]：落在 `show()` 之外的 `screen =` 赋值。

    换页写点不管写在哪个源集，都不该绕过 `AppModel.show()`；文件里一处
    `private fun show(` 都没有时，任何写点都算越界。
    """
    hits = []
    for path in kt_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        spans = [index for index, line in enumerate(lines, 1) if SHOW_DECL.match(line)]
        for lineno, line in enumerate(lines, 1):
            if not SCREEN_WRITE.search(line):
                continue
            inside = path.name == SHOW_OWNER and any(
                0 <= lineno - start <= SHOW_SPAN for start in spans)
            if not inside:
                hits.append((path.relative_to(ROOT).as_posix(), lineno, line.strip()))
    return hits


class AndroidGuards(unittest.TestCase):
    def test_screen_is_only_written_by_show(self):
        """手机版页面状态的写点只许在 `AppModel.show()` 里（CLAUDE.md、ADR-0018）。

        换页只走 `show()` 是沿用 #646 的做法——进 / 出首次设置页时顺手改通知栏；绕过它写
        `screen = ...` 今天未必有可见后果，但下一个照抄这句的人会把这层副作用丢掉（#1020）。

        判据认形态不认语义：Kotlin 字符串字面量里出现 `screen = ` 会误报，出现时改那段文字，
        不要放宽判据。只覆盖 `screen` 一个状态量，`setup`、`run` 等其他可变状态不在范围内。
        另半条规则——「带判断的逻辑放 `aac_android/view.py`」——静态扫描给不出结论，仍靠人工。
        `show()` 的签名一改（加修饰符或换行）这条会报假失败：方向是 fail-closed，改签名时
        一并改 `SHOW_DECL`，别去放宽判据。

        本机没有 JDK / Android SDK，这条只证明谁写 `screen`；改完的 Kotlin 能不能编译
        由 `android.yml` 的 `assemble` job 回答。
        """
        scanned = sorted(ANDROID_SRC.rglob("*.kt"))
        self.assertTrue(scanned, "android/ 下一个 .kt 都没扫到，这条守卫会空转")
        hits = screen_write_offenders()
        self.assertEqual(
            hits, [],
            "`screen` 只许由 AppModel.kt 的 `private fun show()` 改写，这些写点绕过了它：\n"
            + "\n".join(f"{name}:{lineno}  {text}" for name, lineno, text in hits))


# 下载页的卡片身份。`android` 那一条尤其不能改名：卡片角标、手机端高亮与 `baidu_rows.py`
# 生成的安装说明都按它匹配，换一个 id 线上就看不到手机版。改这份清单要同时改卡片、手机端
# 与 `baidu_rows.py`（`gui/baidu_rows.py` 的 SETUP / CHECK）。
DOWNLOAD_IDS = {"mac-arm64", "mac-intel", "win-setup", "win-zip", "android"}


class ReleaseGuards(unittest.TestCase):
    def test_doc_release_apk_id_android(self):
        """下载页 `REL.files` 的 id 集合冻结，且每个 `file` 的文件名里那段版本号等于 `REL.version`。

        旧树也绿，守的是不回退：id 改名、或升级 `REL.version` 时漏改某一条的 `file`，
        用户点下载就是 404，而页面脚本不报错。清单的增删要同时改卡片、手机端高亮与
        `gui/baidu_rows.py` 的 SETUP / CHECK。与真实 Release 附件名的比对不在这里——
        `tool/release_assets.py` 做那一半，由 `.github/workflows/release-assets.yml` 每周跑。
        """
        version, entries = release_assets.read_page((ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(version and entries, "index.html 里读不到 REL，这条守卫会空转")
        ids = [entry_id for entry_id, _ in entries]
        self.assertEqual(set(ids), DOWNLOAD_IDS,
                         "REL.files 的 id 清单变了：改它要同时改下载卡片、手机端高亮与 "
                         "gui/baidu_rows.py 的 SETUP / CHECK")
        self.assertIn("android", ids, "手机版卡片的 id 必须逐字是 android，线上靠它匹配")
        # 附件名固定是 `AndroidAdCleaner-<版本>-<平台>.<后缀>`，版本就是第二段。
        stray = [f"{entry_id}: {name}" for entry_id, name in entries
                 if name.split("-")[1:2] != [version]]
        self.assertEqual(stray, [],
                         f"这些附件的文件名第二段不是 REL.version（{version}）：升级版本时漏改了：\n"
                         + "\n".join(stray))


# 标准流的 UTF-8 重配置只许出现在 helper 模块里（#995）。针脚拼出来：写死的话这条守卫
# 会把自己的源码当成违规，永远红。
STDIO_NEEDLE = "reconfigure(" + "encoding="
STDIO_HOME = "tool/stdio.py"


class StdioGuards(unittest.TestCase):
    def test_stdio_utf8_single_exit(self):
        """除 `tool/stdio.py` 外，任何文件都不许自己 `reconfigure` 标准流。

        旧树不绿（落地前这段四行被抄了十几遍，本条就是那条改动的守卫），之后守的是不回退：
        把任意一处内联写法抄回去即红。语义上的「尽力而为、失败静默」由
        `tests/test_stdio.py` 守，这里只看调用点有没有绕过唯一出口。
        """
        self.assertTrue((ROOT / STDIO_HOME).is_file(), f"{STDIO_HOME} 不在，这条守卫会空转")
        hits, scanned = [], 0
        for path in repo_paths():
            scanned += 1
            if rel(path) == STDIO_HOME:
                continue
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if STDIO_NEEDLE in line:
                    hits.append(f"{rel(path)}:{lineno}")
        self.assertGreater(scanned, 0, "一个文件都没扫到，这条守卫会空转")
        self.assertEqual(hits, [], "标准流只经 tool/stdio.py 的 use_utf8_console() 重配，"
                         "别再各写一份：「改一处漏十二处」就是从那里来的：\n" + "\n".join(hits))


# 工具层起 `gh` 进程只许在会话模块里（#1219，ADR-0036）。守卫只扫 `tool/`，两种引号都认：
# 只认双引号的话，写 `subprocess.run(['gh', ...])` 就绕过去了。
GH_NEEDLES = ('"gh"', "'gh'")
GH_RUNNER_DEF = "def runner_for"
GH_HOME = "tool/gh.py"


class GhGuards(unittest.TestCase):
    def test_gh_process_spawned_in_one_place(self):
        """除 `tool/gh.py` 外，工具层不许自己起 `gh` 进程，也不许再定义一份默认执行器。

        守的是不回退：把任意一处已迁移的脚本改回自带执行器（`subprocess.run(["gh", …])`
        或一份本地 `runner_for`）即红。语义由 `tests/test_gh.py` 守，这里只看调用点有没有
        绕过那唯一一处会话。
        """
        self.assertTrue((ROOT / GH_HOME).is_file(), f"{GH_HOME} 不在，这条守卫会空转")
        hits, scanned = [], 0
        for path in sorted((ROOT / "tool").rglob("*.py")):
            scanned += 1
            if rel(path) == GH_HOME:
                continue
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if any(needle in line for needle in GH_NEEDLES) or GH_RUNNER_DEF in line:
                    hits.append(f"{rel(path)}:{lineno}")
        self.assertGreater(scanned, 0, "tool/ 下一个 .py 都没扫到，这条守卫会空转")
        self.assertEqual(hits, [], "`gh` 只经 tool/gh.py 起进程（runner_for / call / json_of），"
                         "别再各写一份执行器：\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
