"""DCO 校验（devtools/check_dco.py）：`base..head` 里每个非 merge 提交都要带与作者邮箱一致的 Signed-off-by（#848）。"""
import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import fixtures  # noqa: E402
from devtools import check_dco, commits  # noqa: E402

# 起子进程跑的脚本就是被 import 的这份模块：变异副本里它是 `src/devtools/` 下的变异后副本，与进程内
# 用例落在同一份文件上；按 `ROOT/devtools` 写死只会跑到未变异原件（#1517，照 #1515）。
SCRIPT = Path(check_dco.__file__).resolve()
# 脚本按 `__file__` 的两级 dirname 找 `tool/`，副本里那是 `src/tool`（不存在）；它的 `import stdio`
# 要能在同一个 `src` 视角里找到。正常运行时这就是仓库根（`stdio` 仍在 `tool/` 下，无害）。
SRC_ROOT = SCRIPT.parents[1]
# 子进程只跑 CLI 端到端，不参与 mutmut 的进程内归属（归属由 `CommitsTest` / `MainTest` 给）。
# 把继承来的 `MUTANT_UNDER_TEST` 清空：统计阶段它是 `"stats"`，trampoline 会在子进程里去找 mutmut
# 配置，而子进程 cwd 是临时 git 目录、找不到，收集阶段直接崩。
RUN_ENV = {"PYTHONPATH": str(SRC_ROOT), "MUTANT_UNDER_TEST": ""}
WORKFLOW = ROOT / ".github" / "workflows" / "commit-checks.yml"
SIGNED = "Signed-off-by: Rikki <rikki@example.com>"


def commit(body="", email="rikki@example.com", subject="fix: 整理", merge=False):
    return check_dco.Commit(sha="a" * 40, author_email=email, subject=subject, body=body, merge=merge)


class ViolationsTest(unittest.TestCase):
    """判定的三种结局：缺 signoff、邮箱不符、合规；merge 提交不参与。"""

    def test_missing_signoff_is_reported(self):
        bad = check_dco.violations([commit(body="")])
        self.assertEqual([v.kind for v in bad], ["missing"])

    def test_signoff_with_the_author_email_passes(self):
        self.assertEqual(check_dco.violations([commit(body=SIGNED + "\n")]), [])

    def test_email_comparison_ignores_case(self):
        self.assertEqual(check_dco.violations([commit(body=SIGNED + "\n", email="Rikki@Example.COM")]), [])

    def test_signoff_for_another_email_is_reported(self):
        body = "Signed-off-by: Someone <someone@example.com>\n"
        bad = check_dco.violations([commit(body=body)])
        self.assertEqual([v.kind for v in bad], ["mismatch"])

    def test_one_matching_signoff_among_several_is_enough(self):
        body = "Signed-off-by: Someone <someone@example.com>\n" + SIGNED + "\n"
        self.assertEqual(check_dco.violations([commit(body=body)]), [])

    def test_merge_commits_are_skipped(self):
        self.assertEqual(check_dco.violations([commit(body="", merge=True)]), [])

    def test_a_merge_commit_does_not_stop_the_scan(self):
        # `continue` 跳过 merge 后还要往后看：后面的违规提交不能被漏掉（`break` 会漏）。
        commits = [commit(body="", merge=True), commit(body="")]
        self.assertEqual([v.kind for v in check_dco.violations(commits)], ["missing"])

    def test_mismatch_lists_every_signoff(self):
        # 多个签署邮箱用「, 」连接：分隔符被改掉时这句会露馅（`', '.join` 的变异体只差这一处）。
        body = "Signed-off-by: A <a@example.com>\nSigned-off-by: B <b@example.com>\n"
        bad = check_dco.violations([commit(body=body)])
        self.assertEqual([v.kind for v in bad], ["mismatch"])
        self.assertIn("签署 a@example.com, b@example.com", bad[0].reason)


class RangeTest(unittest.TestCase):
    """端到端：在真 git 仓上跑脚本，退出码与输出就是 CI 看到的结论。"""

    def setUp(self):
        self.repo = fixtures.GitRepo()
        self.addCleanup(self.repo.cleanup)

    def commit(self, subject, body=None, author_email=None):
        return self.repo.commit(subject, body=body, author_email=author_email)

    def run_check(self, base, head="HEAD", env_extra=None):
        return self.repo.run(SCRIPT, f"{base}..{head}",
                             env_extra={**RUN_ENV, **(env_extra or {})})

    def test_unsigned_commit_fails_and_names_it(self):
        base = self.commit("chore: 起点")
        sha = self.commit("fix: 没签的改动")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn(sha, out)
        self.assertIn("fix: 没签的改动", out)
        self.assertIn("缺 Signed-off-by", out)

    def test_signed_commit_passes(self):
        base = self.commit("chore: 起点")
        self.commit("fix: 签了", body=SIGNED)
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)

    def test_email_mismatch_fails(self):
        base = self.commit("chore: 起点")
        sha = self.commit("fix: 签错邮箱", body=SIGNED, author_email="other@example.com")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn(sha, out)
        self.assertIn("Signed-off-by 邮箱与作者不符", out)

    def test_merge_commit_does_not_participate(self):
        base = self.commit("chore: 起点")
        self.repo.git("checkout", "-q", "-b", "side")
        self.commit("fix: 侧支", body=SIGNED)
        self.repo.git("checkout", "-q", "main")
        self.commit("fix: 主干", body=SIGNED)
        self.repo.git("merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'")
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)

    def test_every_violation_is_listed(self):
        base = self.commit("chore: 起点")
        first = self.commit("fix: 第一处")
        second = self.commit("fix: 第二处")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        for sha in (first, second):
            self.assertIn(sha, out)

    def test_git_error_is_not_reported_as_a_pass(self):
        # 读不出提交时必须红：吞掉错误返回空范围，会被当成「全都合规」。
        code, out = self.run_check("no-such-ref", head="HEAD")
        self.assertEqual(code, 2, out)
        self.assertIn("git", out)

    def test_output_survives_a_non_utf8_console(self):
        # Windows 控制台与管道默认 cp1252：打印中文不能把校验本身打崩（#848 的 Windows CI 抓到过）。
        base = self.commit("chore: 起点")
        sha = self.commit("fix: 没签的改动")
        code, out = self.run_check(base, env_extra={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(code, 1, out)
        self.assertIn(sha, out)


class CommitsTest(unittest.TestCase):
    """`commits` 的读取在进程内跑一遍：只经子进程走到时 mutmut 记不到归属（#1517）。

    `read_commits` / `git` 没有独立测试文件，三份 `check_*` 的子进程端到端也拿不到进程内归属，
    这里直接在真 git 仓上读——这是 `devtools/commits.py` 唯一的进程内调用点。
    """

    def setUp(self):
        self.repo = fixtures.GitRepo()
        self.addCleanup(self.repo.cleanup)

    def read(self, rev_range):
        with contextlib.chdir(self.repo.dir):
            return list(commits.read_commits(rev_range))

    def test_reads_every_field_of_a_commit(self):
        base = self.repo.commit("chore: 起点")
        sha = self.repo.commit("fix: 整理", body=SIGNED)
        (item,) = self.read(f"{base}..HEAD")
        self.assertEqual(item.sha, sha)
        self.assertEqual(item.author_email, "rikki@example.com")
        self.assertEqual(item.subject, "fix: 整理")
        self.assertEqual(item.body.strip(), SIGNED)
        self.assertFalse(item.merge)

    def test_a_merge_commit_is_flagged_and_a_normal_one_is_not(self):
        # `merge=len(parents.split()) > 1` 的边界：单亲提交是 1，合并提交是 2。
        base = self.repo.commit("chore: 起点")
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.commit("fix: 侧支")
        self.repo.git("checkout", "-q", "main")
        self.repo.commit("fix: 主干")
        self.repo.git("merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'")
        flags = {item.subject: item.merge for item in self.read(f"{base}..HEAD")}
        self.assertTrue(flags["Merge branch 'side'"])
        self.assertFalse(flags["fix: 主干"])

    def test_a_bad_revision_range_raises(self):
        with contextlib.chdir(self.repo.dir):
            with self.assertRaises(RuntimeError):
                commits.git("rev-list", "no-such-ref")


class GitFunctionTest(unittest.TestCase):
    """`git` 的子进程参数与失败信息：进程内用假 subprocess 钉住编码、错误策略与命令（#1517）。

    真实 `git` 在本机默认就是 UTF-8，编码参数的退化要跨平台才看得见；这里直接从调用参数上把它钉住。
    """

    def fake_run(self, **result):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv, result.get("returncode", 0),
                result.get("stdout", ""), result.get("stderr", ""))

        return run, calls

    def test_passes_utf8_text_mode_and_replace_errors(self):
        run, calls = self.fake_run(stdout="abc")
        with mock.patch("subprocess.run", run):
            self.assertEqual(commits.git("rev-list", "x"), "abc")
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["git", "rev-list", "x"])
        self.assertTrue(kwargs.get("capture_output"))
        self.assertTrue(kwargs.get("text"))
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")

    def test_a_failing_git_names_the_command(self):
        run, _ = self.fake_run(returncode=1, stderr="boom\n")
        with mock.patch("subprocess.run", run):
            with self.assertRaises(RuntimeError) as caught:
                commits.git("rev-list", "no-such-ref")
        self.assertEqual(str(caught.exception), "git rev-list no-such-ref 失败：boom")


class MainTest(unittest.TestCase):
    """`main()` 在同一解释器里直接调，让 mutmut 记到它的归属（#1517）。

    归属按进程内 trampoline 命中算：只经子进程跑到的入口在统计阶段记不到测试，mutmut 会在跑之前把它
    记成「无测试」（exit 33），一条测试都不跑。端到端之外必须有进程内调用点。
    """

    def setUp(self):
        self.repo = fixtures.GitRepo()
        self.addCleanup(self.repo.cleanup)

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_dco.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def run_in(self, *argv):
        with contextlib.chdir(self.repo.dir):
            return self.call(*argv)

    def test_clean_range_says_so(self):
        base = self.repo.commit("chore: 起点")
        self.repo.commit("fix: 签了", body=SIGNED)
        code, out, err = self.run_in(f"{base}..HEAD")
        self.assertEqual(code, 0, err)
        self.assertIn("都带与作者邮箱一致的 Signed-off-by", out)

    def test_violations_are_listed_with_sha_subject_and_reason(self):
        base = self.repo.commit("chore: 起点")
        sha = self.repo.commit("fix: 没签的改动")
        code, out, err = self.run_in(f"{base}..HEAD")
        self.assertEqual(code, 1, err)
        self.assertIn(f"{base}..HEAD 有 1 个提交不合规", out)
        self.assertIn(f"{sha} fix: 没签的改动 —— 缺 Signed-off-by", out)

    def test_mismatch_reason_is_reported(self):
        base = self.repo.commit("chore: 起点")
        self.repo.commit("fix: 签错邮箱", body=SIGNED, author_email="other@example.com")
        code, out, _ = self.run_in(f"{base}..HEAD")
        self.assertEqual(code, 1)
        self.assertIn("Signed-off-by 邮箱与作者不符", out)

    def test_wrong_argument_count_is_an_error(self):
        code, out, err = self.call()
        self.assertEqual(code, 2, out + err)
        self.assertTrue(err.startswith("用法：python3 devtools/check_dco.py"), err)
        self.assertIn("<base>..<head>", err)

    def test_extra_arguments_are_an_error(self):
        code, out, err = self.call("a..b", "extra")
        self.assertEqual(code, 2, out + err)
        self.assertIn("用法：python3 devtools/check_dco.py", err)

    def test_git_error_is_reported_not_a_pass(self):
        code, out, err = self.run_in("no-such-ref")
        self.assertEqual(code, 2, out + err)
        self.assertIn("git rev-list --parents no-such-ref 失败", err)


def uncommented(text):
    """去掉整行注释：workflow 的说明里也写着脚本路径与 sha 表达式，全文子串匹配会被注释满足。"""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class WorkflowTest(unittest.TestCase):
    """CI 跑的就是这条命令：workflow 与脚本、PR 范围三者必须对得上。"""

    def setUp(self):
        self.text = uncommented(WORKFLOW.read_text(encoding="utf-8"))

    def step(self, name):
        """`- name: <name>` 到下一个 step 之间那一段，只在这一段里断言。"""
        lines = self.text.splitlines()
        start = next((i for i, line in enumerate(lines) if line.strip() == f"- name: {name}"), None)
        self.assertIsNotNone(start, f"workflow 里没有 step「{name}」")
        rest = lines[start + 1:]
        end = next((i for i, line in enumerate(rest) if line.strip().startswith("- ")), len(rest))
        return "\n".join(rest[:end])

    def test_job_is_named_dco(self):
        # PR 检查列表显示的就是 job id；改名等于验收条件里的 `dco` 不成立。
        self.assertIn("\n  dco:\n", self.text)

    def test_dco_job_runs_the_script(self):
        self.assertIn("python3 devtools/check_dco.py", self.step("校验 DCO"))

    def test_job_checks_the_pull_request_range(self):
        step = self.step("校验 DCO")
        self.assertIn("pull_request.base.sha", step)
        self.assertIn("pull_request.head.sha", step)

    def test_checkout_keeps_enough_history(self):
        # 浅克隆里 base 不是本地的祖先，`base..head` 取不到 PR 的提交。
        self.assertIn("fetch-depth: 0", self.text)


if __name__ == "__main__":
    unittest.main()
