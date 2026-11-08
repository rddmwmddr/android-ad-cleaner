"""DCO 校验（tool/check_dco.py）：`base..head` 里每个非 merge 提交都要带与作者邮箱一致的 Signed-off-by（#848）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import check_dco  # noqa: E402
import fixtures  # noqa: E402

SCRIPT = ROOT / "tool" / "check_dco.py"
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


class RangeTest(unittest.TestCase):
    """端到端：在真 git 仓上跑脚本，退出码与输出就是 CI 看到的结论。"""

    def setUp(self):
        self.repo = fixtures.GitRepo()
        self.addCleanup(self.repo.cleanup)

    def commit(self, subject, body=None, author_email=None):
        return self.repo.commit(subject, body=body, author_email=author_email)

    def run_check(self, base, head="HEAD"):
        return self.repo.run(SCRIPT, f"{base}..{head}")

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
        code, out = self.repo.run(SCRIPT, f"{base}..HEAD", env_extra={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(code, 1, out)
        self.assertIn(sha, out)


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
        self.assertIn("python3 tool/check_dco.py", self.step("校验 DCO"))

    def test_job_checks_the_pull_request_range(self):
        step = self.step("校验 DCO")
        self.assertIn("pull_request.base.sha", step)
        self.assertIn("pull_request.head.sha", step)

    def test_checkout_keeps_enough_history(self):
        # 浅克隆里 base 不是本地的祖先，`base..head` 取不到 PR 的提交。
        self.assertIn("fetch-depth: 0", self.text)


if __name__ == "__main__":
    unittest.main()
