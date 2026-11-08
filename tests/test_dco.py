"""DCO 校验（tool/check_dco.py）：`base..head` 里每个非 merge 提交都要带与作者邮箱一致的 Signed-off-by（#848）。"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import check_dco  # noqa: E402

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
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        config = self.dir / "gitconfig"
        config.write_text("", encoding="utf-8")
        # 本机全局配置里有 commit-msg 钩子，测试仓必须绕开它，否则写不出未签署的提交。
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1", HOME=str(self.dir))
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Rikki")
        self.git("config", "user.email", "rikki@example.com")

    def git(self, *args, author_email=None):
        env = dict(self.env) if author_email is None else dict(self.env, GIT_AUTHOR_EMAIL=author_email)
        done = subprocess.run(["git", *args], cwd=self.dir, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", check=True)
        return done.stdout.strip()

    def write(self, name):
        (self.dir / name).write_text(name, encoding="utf-8")
        self.git("add", name)

    def commit(self, subject, body=None, author_email=None):
        self.count = getattr(self, "count", 0) + 1
        self.write(f"{self.count}.txt")                    # 每个提交都要有内容，否则 git 拒绝提交
        args = ["commit", "-q", "-m", subject]
        if body:
            args += ["-m", body]
        self.git(*args, author_email=author_email)
        return self.git("rev-parse", "HEAD")

    def run_check(self, base, head="HEAD"):
        done = subprocess.run([sys.executable, str(SCRIPT), f"{base}..{head}"], cwd=self.dir,
                              env=self.env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        return done.returncode, done.stdout + done.stderr

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
        self.git("checkout", "-q", "-b", "side")
        self.commit("fix: 侧支", body=SIGNED)
        self.git("checkout", "-q", "main")
        self.commit("fix: 主干", body=SIGNED)
        self.git("merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'")
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


class WorkflowTest(unittest.TestCase):
    """CI 跑的就是这条命令：workflow 与脚本、PR 范围三者必须对得上。"""

    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_dco_job_runs_the_script(self):
        self.assertIn("tool/check_dco.py", self.text)

    def test_job_checks_the_pull_request_range(self):
        self.assertIn("github.event.pull_request.base.sha", self.text)
        self.assertIn("github.event.pull_request.head.sha", self.text)

    def test_checkout_keeps_enough_history(self):
        # 浅克隆里 base 不是本地的祖先，`base..head` 取不到 PR 的提交。
        self.assertIn("fetch-depth: 0", self.text)


if __name__ == "__main__":
    unittest.main()
