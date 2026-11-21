"""分支名与 PR 正文指到同一张票（devtools/check_ticket_ref.py，#1001）。"""
import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import fixtures  # noqa: E402
from devtools import check_ticket_ref  # noqa: E402

# 起子进程跑的脚本就是被 import 的这份模块：变异副本里它是 `src/devtools/` 下的变异后副本，子进程
# 继承 `MUTANT_UNDER_TEST` 会执行到同一批 mutant（#1515）。按 `ROOT/devtools` 写死只会跑到未变异原件。
SCRIPT = Path(check_ticket_ref.__file__).resolve()
# 脚本按 `__file__` 的两级 dirname 找 `tool/`，副本里那是 `src/tool`（不存在）；它的 `import stdio`
# 要能在同一个 `src` 视角里找到。正常运行时这就是仓库根（`stdio` 仍在 `tool/` 下，无害）。
SRC_ROOT = SCRIPT.parents[1]
# 子进程只跑 CLI 端到端，不参与 mutmut 的进程内归属（归属由 `MainTest` / `ProblemsTest` 给）。
# 把继承来的 `MUTANT_UNDER_TEST` 清空：统计阶段它是 `"stats"`，trampoline 会在子进程里去找 mutmut
# 配置，而子进程 cwd 是临时 git 目录、找不到，收集阶段直接崩。
RUN_ENV = {"PYTHONPATH": str(SRC_ROOT), "MUTANT_UNDER_TEST": ""}
WORKFLOW = ROOT / ".github" / "workflows" / "ticket-checks.yml"

# 用例里构造的票号是数据、不是引用：写成字面量会被本 PR 的 comment-tickets job 自己抓到，
# 与 test_source_text.py 处理零宽字符同一做法。
OTHER = "#" + "903"
HISTORIC = "#" + "840"


class ProblemsTest(unittest.TestCase):
    """三种结局各有各的说法：分支名没票号、正文没引用、两边不是同一张；合规的不报。"""

    def test_branch_without_a_ticket_is_reported(self):
        bad = check_ticket_ref.problems("feat/browser-entry", "Refs #1001")
        self.assertEqual(len(bad), 1)
        self.assertIn("没有以", bad[0])

    def test_body_without_a_reference_is_reported(self):
        bad = check_ticket_ref.problems("feat/x-1001", "改了浏览器入口")
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0].startswith("PR 正文没有"), bad[0])
        self.assertIn("Refs", bad[0])

    def test_mismatched_ticket_names_both_sides(self):
        bad = check_ticket_ref.problems("feat/x-1001", f"Refs {OTHER}")
        self.assertEqual(len(bad), 1)
        self.assertIn("#1001", bad[0])
        self.assertIn(OTHER, bad[0])

    def test_matching_reference_passes(self):
        self.assertEqual(check_ticket_ref.problems("feat/x-1001", "Refs #1001"), [])

    def test_closes_counts_as_a_reference(self):
        self.assertEqual(check_ticket_ref.problems("fix/x-1001", "Closes #1001"), [])

    def test_reference_is_case_insensitive(self):
        self.assertEqual(check_ticket_ref.problems("fix/x-1001", "refs #1001"), [])

    def test_one_matching_reference_among_several_is_enough(self):
        # 正文常写历史票说明由来、`Closes #1001` 才算本票，多引一张不该红。
        self.assertEqual(check_ticket_ref.problems("fix/x-1001", f"Refs {HISTORIC}、Closes #1001"), [])

    def test_ticket_must_be_at_the_end_of_the_branch_name(self):
        # `feat/1001-fix` 不是约定形态：票号在末尾才能从分支名直接读出来。
        self.assertEqual(len(check_ticket_ref.problems("feat/1001-fix", "Refs #1001")), 1)


class RangeTest(unittest.TestCase):
    """端到端：脚本的退出码与输出就是 CI 看到的结论。"""

    def setUp(self):
        self.repo = fixtures.GitRepo()
        self.addCleanup(self.repo.cleanup)

    def run_script(self, *args, env_extra=None):
        return self.repo.run(SCRIPT, *args, env_extra={**RUN_ENV, **(env_extra or {})})

    def run_check(self, branch, body, env_extra=None):
        path = self.repo.dir / "pr.txt"
        path.write_text(body, encoding="utf-8")
        return self.run_script(branch, str(path), env_extra=env_extra)

    def test_mismatch_fails(self):
        code, out = self.run_check("feat/x-1001", f"Refs {OTHER}")
        self.assertEqual(code, 1, out)
        self.assertIn("#1001", out)
        self.assertIn(OTHER, out)

    def test_match_passes(self):
        code, out = self.run_check("feat/x-1001", "Refs #1001")
        self.assertEqual(code, 0, out)

    def test_unreadable_body_is_not_reported_as_a_pass(self):
        # 读不出正文时必须红：吞掉错误当成空正文，会报成「没有引用」，也可能被当成通过。
        code, out = self.run_script("feat/x-1001", str(self.repo.dir / "nope.txt"))
        self.assertEqual(code, 2, out)

    def test_wrong_argument_count_is_an_error(self):
        code, out = self.run_script("feat/x-1001")
        self.assertEqual(code, 2, out)
        self.assertIn("用法", out)

    def test_output_survives_a_non_utf8_console(self):
        # Windows 控制台与管道默认不是 UTF-8：打印中文不能把校验本身打崩。
        code, out = self.run_check("feat/x-1001", f"Refs {OTHER}", {"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(code, 1, out)
        self.assertIn("#1001", out)


class MainTest(unittest.TestCase):
    """`main()` 的退出码与输出——同一个解释器里直接调，让 mutmut 记到 `main` 的归属（#1515）。

    归属按进程内 trampoline 命中算：只经子进程跑到的入口在统计阶段记不到测试，mutmut 会在跑之前把它
    记成「无测试」（exit 33），一条测试都不跑。端到端之外必须有进程内调用点。
    """

    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_ticket_ref.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def body(self, text):
        path = self.dir / "pr.txt"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_matching_reference_passes(self):
        code, out, err = self.call("feat/x-1001", self.body("Refs #1001"))
        self.assertEqual(code, 0, err)
        self.assertIn("#1001", out)

    def test_mismatch_lists_both_tickets(self):
        code, out, err = self.call("feat/x-1001", self.body(f"Refs {OTHER}"))
        self.assertEqual(code, 1, err)
        self.assertIn("对不上（1 处）", out)
        self.assertIn("#1001", out)
        self.assertIn(OTHER, out)

    def test_mismatch_sorts_tickets_numerically(self):
        # 两张对不上的票按数值排序：改走字符串排序会把「#10」排在「#9」前面。
        code, out, _ = self.call("feat/x-1001", self.body("Refs #" + "10、Closes #" + "9"))
        self.assertEqual(code, 1)
        self.assertIn("#9、#10", out)

    def test_wrong_argument_count_is_an_error(self):
        code, out, err = self.call("feat/x-1001")
        self.assertEqual(code, 2, out + err)
        self.assertTrue(err.startswith("用法：python3 devtools/check_ticket_ref.py"), err)
        self.assertIn("<PR 文本文件>", err)

    def test_unreadable_body_is_an_error(self):
        code, out, err = self.call("feat/x-1001", str(self.dir / "nope.txt"))
        self.assertEqual(code, 2, out + err)
        self.assertIn("nope.txt", err)

    def test_reads_the_pull_request_text_as_utf8(self):
        # 正文按 UTF-8 读，不受进程默认编码影响。`UTF-8` 与 `utf-8` 是同一个 codec、行为不可区分，
        # 只能从调用参数上把它钉住，否则这条契约在非 UTF-8 的系统上会悄悄退化。
        real_open = open
        seen = {}

        def spy(file, *args, **kwargs):
            seen.update(kwargs)
            return real_open(file, *args, **kwargs)

        path = self.body("Refs #1001")
        with mock.patch("builtins.open", spy):
            code, _, err = self.call("feat/x-1001", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(seen.get("encoding"), "utf-8")

    def test_invalid_bytes_are_replaced_not_fatal(self):
        # `errors="replace"`：PR 正文里混进一个非 UTF-8 字节时不该整份校验崩掉。
        path = self.dir / "pr.txt"
        path.write_bytes(b"Refs #1001 \xff")
        code, out, err = self.call("feat/x-1001", str(path))
        self.assertEqual(code, 0, err)


def uncommented(text):
    """去掉整行注释：workflow 的说明里也写着脚本路径，全文子串匹配会被注释满足。"""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class WorkflowTest(unittest.TestCase):
    """CI 跑的就是这条命令：workflow 与脚本、PR 上下文三者必须对得上。"""

    def setUp(self):
        self.text = uncommented(WORKFLOW.read_text(encoding="utf-8"))

    def job(self, name):
        """`  <name>:` 到下一个同级 job 之间那一段，只在这一段里断言。"""
        lines = self.text.splitlines()
        start = next((i for i, line in enumerate(lines) if line == f"  {name}:"), None)
        self.assertIsNotNone(start, f"workflow 里没有 job「{name}」")
        rest = lines[start + 1:]
        end = next((i for i, line in enumerate(rest) if re.match(r"^  \S", line)), len(rest))
        return "\n".join(rest[:end])

    def test_job_is_named_ticket_ref(self):
        # PR 检查列表显示的就是 job id；注册表 `ci:ticket-ref` 指的就是它。
        self.assertIn("\n  ticket-ref:\n", self.text)

    def test_job_runs_the_script(self):
        self.assertIn("python3 devtools/check_ticket_ref.py", self.job("ticket-ref"))

    def test_job_reads_the_branch_and_the_pull_request_text(self):
        job = self.job("ticket-ref")
        self.assertIn("github.head_ref", job)
        self.assertIn("github.event.pull_request.title", job)
        self.assertIn("github.event.pull_request.body", job)

    def test_editing_the_pull_request_reruns_the_checks(self):
        # 正文就是判据：补一行 `Refs #N` 之后要能重跑，不必为它空推一个提交。
        self.assertIn("edited", self.text)


if __name__ == "__main__":
    unittest.main()
