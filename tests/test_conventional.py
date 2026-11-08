"""Conventional Commits 校验（tool/check_conventional.py）：`base..head` 里每个非 merge 提交的主题都要带合规前缀（#849）。"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import check_conventional  # noqa: E402
import fixtures  # noqa: E402

SCRIPT = ROOT / "tool" / "check_conventional.py"
WORKFLOW = ROOT / ".github" / "workflows" / "commit-checks.yml"
CLAUDE_MD = ROOT / "CLAUDE.md"
ANCHOR = "rule:dev.git.conventional-commits"


def commit(subject, merge=False):
    return check_conventional.Commit(
        sha="a" * 40, author_email="rikki@example.com", subject=subject, body="", merge=merge)


class ViolationsTest(unittest.TestCase):
    """主题前缀的三种结局：没有前缀、前缀里 type 不认识、scope 不合规；合规的（含中文主题）不报。"""

    def test_subject_without_prefix_is_reported(self):
        bad = check_conventional.violations([commit("Update README.md")])
        self.assertEqual(len(bad), 1)
        self.assertIn("前缀", bad[0].reason)

    def test_chinese_subject_with_a_valid_prefix_passes(self):
        self.assertEqual(check_conventional.violations([commit("fix(chan): 插电常亮原值已是 15 等更宽的值时不改写")]), [])

    def test_every_documented_type_is_accepted(self):
        # 清单是显式常量：少写一个类型，那一族提交就会全红。
        for kind in check_conventional.TYPES:
            with self.subTest(kind=kind):
                self.assertEqual(check_conventional.violations([commit(f"{kind}: 收尾")]), [])

    def test_unknown_type_is_reported(self):
        bad = check_conventional.violations([commit("feature: 加了东西")])
        self.assertEqual(len(bad), 1)
        self.assertIn("type", bad[0].reason)

    def test_scope_must_be_lowercase_slug(self):
        for scope in ("GUI", "a b", "带中文"):
            with self.subTest(scope=scope):
                bad = check_conventional.violations([commit(f"feat({scope}): 收尾")])
                self.assertEqual(len(bad), 1)
                self.assertIn("scope", bad[0].reason)

    def test_breaking_change_marker_passes(self):
        self.assertEqual(check_conventional.violations([commit("feat(row)!: 改掉 switch_rows 的返回形状")]), [])

    def test_prefix_needs_the_trailing_space(self):
        # `fix:整理` 是打字漏了空格，不是合规前缀。
        self.assertEqual(len(check_conventional.violations([commit("fix:整理")])), 1)

    def test_merge_commits_are_skipped(self):
        self.assertEqual(check_conventional.violations([commit("Merge branch 'main'", merge=True)]), [])


class RangeTest(unittest.TestCase):
    """端到端：在真 git 仓上跑脚本，退出码与输出就是 CI 看到的结论。"""

    def setUp(self):
        self.repo = fixtures.GitRepo()
        self.addCleanup(self.repo.cleanup)

    def commit(self, subject):
        return self.repo.commit(subject)

    def run_check(self, base, head="HEAD"):
        return self.repo.run(SCRIPT, f"{base}..{head}")

    def test_subject_without_prefix_fails_and_names_it(self):
        base = self.commit("fix: 起点")
        sha = self.commit("初版：引擎、总入口、三份机型脚本")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn(sha, out)
        self.assertIn("初版：引擎、总入口、三份机型脚本", out)

    def test_conventional_subject_passes(self):
        base = self.commit("chore: 起点")
        self.commit("fix(chan): 插电常亮原值已是 15 等更宽的值时不改写")
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)

    def test_every_violation_is_listed(self):
        base = self.commit("chore: 起点")
        first = self.commit("Update README.md")
        second = self.commit("初版：引擎")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        for sha in (first, second):
            self.assertIn(sha, out)

    def test_merge_commit_does_not_participate(self):
        base = self.commit("chore: 起点")
        self.repo.git("checkout", "-q", "-b", "side")
        self.commit("fix: 侧支")
        self.repo.git("checkout", "-q", "main")
        self.commit("fix: 主干")
        self.repo.git("merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'")
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)

    def test_git_error_is_not_reported_as_a_pass(self):
        # 读不出提交时必须红：吞掉错误返回空范围，会被当成「全都合规」。
        code, out = self.run_check("no-such-ref")
        self.assertEqual(code, 2, out)
        self.assertIn("git", out)

    def test_output_survives_a_non_utf8_console(self):
        # Windows 控制台与管道默认 cp1252：打印中文不能把校验本身打崩。
        base = self.commit("chore: 起点")
        sha = self.commit("初版：引擎")
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

    def job(self, name):
        """`  <name>:` 到下一个同级 job 之间那一段，只在这一段里断言。"""
        lines = self.text.splitlines()
        start = next((i for i, line in enumerate(lines) if line == f"  {name}:"), None)
        self.assertIsNotNone(start, f"workflow 里没有 job「{name}」")
        rest = lines[start + 1:]
        end = next((i for i, line in enumerate(rest) if re.match(r"^  \S", line)), len(rest))
        return "\n".join(rest[:end])

    def test_job_is_named_conventional(self):
        # PR 检查列表显示的就是 job id；改名等于验收条件里的 `conventional` 不成立。
        self.assertIn("\n  conventional:\n", self.text)

    def test_job_runs_the_script(self):
        self.assertIn("python3 tool/check_conventional.py", self.job("conventional"))

    def test_job_checks_the_pull_request_range(self):
        # 只判 PR 范围：main 上的历史提交不在这一步里，也不许为此重写历史。
        job = self.job("conventional")
        self.assertIn("pull_request.base.sha", job)
        self.assertIn("pull_request.head.sha", job)

    def test_checkout_keeps_enough_history(self):
        # 浅克隆里 base 不是本地的祖先，`base..head` 取不到 PR 的提交。
        self.assertIn("fetch-depth: 0", self.job("conventional"))


class DocumentedTypesTest(unittest.TestCase):
    """类型清单只钉一处（脚本里的 TYPES），CLAUDE.md 列出同一份，改一边不改另一边就红。"""

    def documented_types(self):
        lines = [line for line in CLAUDE_MD.read_text(encoding="utf-8").splitlines() if ANCHOR in line]
        self.assertEqual(len(lines), 1, f"CLAUDE.md 里要有且只有一行带 `<!-- {ANCHOR} -->` 的锚点")
        match = re.search(r"`type` 只取 (.+?) 之一", lines[0])
        self.assertIsNotNone(match, "锚点行要写「`type` 只取 `a`、`b`… 之一」，守卫从这一句读清单")
        return [item.strip().strip("`") for item in match.group(1).split("、")]

    def test_documented_types_match_the_constant(self):
        self.assertEqual(set(self.documented_types()), set(check_conventional.TYPES))

    def test_every_documented_type_is_accepted_by_the_pattern(self):
        for kind in self.documented_types():
            with self.subTest(kind=kind):
                self.assertEqual(check_conventional.violations([commit(f"{kind}(scope): 收尾")]), [])


if __name__ == "__main__":
    unittest.main()
