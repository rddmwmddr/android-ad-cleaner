"""新写的行里挂的票号要与这次 PR 有关（tool/check_comment_tickets.py，#1001）。"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import check_comment_tickets  # noqa: E402
import fixtures  # noqa: E402

SCRIPT = ROOT / "tool" / "check_comment_tickets.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ticket-checks.yml"

# 用例里构造的票号是数据、不是引用：写成字面量会被本 PR 的 comment-tickets job 自己抓到，
# 与 test_source_text.py 处理零宽字符同一做法。
FOREIGN = "#" + "903"
OTHER = "#" + "904"
ABSENT = "#" + "999"
BLACK = "#" + "000"
GREY = "#" + "333"
INK = "#" + "101820"


class DiffTest(unittest.TestCase):
    """在真 git 仓上造 diff：只判新增行，豁免两种明确引用。"""

    def setUp(self):
        self.repo = fixtures.GitRepo()
        self.addCleanup(self.repo.cleanup)
        self.base = self.repo.commit("chore: 起点")

    def commit_files(self, files, subject="docs: 加一行"):
        for rel, text in files.items():
            path = self.repo.dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            self.repo.git("add", rel)
        self.repo.git("commit", "-q", "-m", subject)
        return self.repo.git("rev-parse", "HEAD")

    def problems(self, files, pr_text="Refs #1001", base=None):
        """提交 `files` 后判 `base..HEAD`；base 默认是夹具的第一个提交。

        `added_lines` 默认在当前目录跑 git；这里把临时仓的 runner 传进去，测的是解析本身。
        """
        rev = f"{base or self.base}..{self.commit_files(files)}"
        return check_comment_tickets.problems(rev, pr_text, run=self.repo.git)

    def test_ticket_inside_the_pull_request_reference_passes(self):
        self.assertEqual(self.problems({"a.py": "# 修好落点（#1001）\n"}), [])

    def test_ticket_outside_the_reference_is_reported_with_file_and_line(self):
        bad = self.problems({"a.py": f"# 修好落点（{FOREIGN}）\n"})
        self.assertEqual(len(bad), 1)
        self.assertIn("a.py:1", bad[0])
        self.assertIn(FOREIGN, bad[0])

    def test_the_reference_set_comes_from_title_and_body_together(self):
        # CI 把标题与正文拼成一份交给脚本：标题里写了票号同样算数。
        self.assertEqual(self.problems({"a.py": f"# 见 {FOREIGN}\n"}, f"修落点\n\nRefs {FOREIGN}"), [])

    def test_line_saying_yan_yong_is_exempt(self):
        # 规则本身允许「沿用 #xxx 的做法」这类明确引用。
        self.assertEqual(self.problems({"a.py": f"# 沿用 {FOREIGN} 的做法\n"}), [])

    def test_adr_lines_are_exempt(self):
        # ADR 记的就是当时引用了哪张票，改它等于改写历史。
        self.assertEqual(self.problems({"docs/adr/0033-x.md": f"见 {FOREIGN} 的判据\n"}), [])

    def test_only_added_lines_are_checked(self):
        # base 里已有的票号不因这条检查翻旧账。
        old = self.commit_files({"a.py": f"# 老注释（{FOREIGN}）\n"}, subject="chore: 旧注释")
        self.assertEqual(self.problems({"b.py": "# 新注释（#1001）\n"}, base=old), [])

    def test_every_violation_is_listed(self):
        bad = self.problems({"a.py": f"# 见 {FOREIGN}\n# 见 {OTHER}\n"})
        self.assertEqual(len(bad), 2)
        self.assertIn("a.py:1", bad[0])
        self.assertIn("a.py:2", bad[1])

    def test_line_numbers_are_those_of_the_new_file(self):
        old = self.commit_files({"notes.md": "第一行\n第二行\n"}, subject="docs: 两行")
        bad = self.problems({"notes.md": f"第一行\n第二行\n见 {ABSENT}\n"}, base=old)
        self.assertEqual(len(bad), 1)
        self.assertIn("notes.md:3", bad[0])

    def test_url_fragment_and_html_entity_are_not_tickets(self):
        self.assertEqual(self.problems({"a.md": "见 https://example.com/x#42 与 &#1001;\n"}), [])

    def test_css_colours_are_not_tickets(self):
        # 调色行与票号同形：冒号开头的属性值与收在分号 / 右花括号前的一律当颜色。
        css = f"body {{ color: {BLACK}; border: 1px solid {GREY} }}\na {{ color:{INK} }}\n"
        self.assertEqual(self.problems({"site.css": css}), [])

    def test_ticket_right_after_a_cjk_word_still_counts(self):
        # 按「ASCII 词字符」排除会漏掉紧挨中文的写法：中文与 `#` 之间没有空格也是挂票号。
        self.assertEqual(len(self.problems({"a.py": f"见{FOREIGN} 的做法\n"})), 1)


class RangeTest(unittest.TestCase):
    """端到端：脚本的退出码与输出就是 CI 看到的结论。"""

    def setUp(self):
        self.repo = fixtures.GitRepo()
        self.addCleanup(self.repo.cleanup)
        self.base = self.repo.commit("chore: 起点")

    def stage(self, text):
        (self.repo.dir / "a.py").write_text(text, encoding="utf-8")
        self.repo.git("add", "a.py")
        self.repo.git("commit", "-q", "-m", "docs: 加注释")
        return f"{self.base}..HEAD"

    def run_check(self, rev_range, pr_text="Refs #1001", env_extra=None):
        path = self.repo.dir / "pr.txt"
        path.write_text(pr_text, encoding="utf-8")
        return self.repo.run(SCRIPT, rev_range, str(path), env_extra=env_extra)

    def test_foreign_ticket_fails_and_names_it(self):
        code, out = self.run_check(self.stage(f"# 见 {FOREIGN}\n"))
        self.assertEqual(code, 1, out)
        self.assertIn("a.py:1", out)
        self.assertIn(FOREIGN, out)

    def test_referenced_ticket_passes(self):
        code, out = self.run_check(self.stage("# 见 #1001\n"))
        self.assertEqual(code, 0, out)

    def test_git_error_is_not_reported_as_a_pass(self):
        # 读不出 diff 时必须红：吞掉错误当成空范围，会被当成「全都合规」。
        code, out = self.run_check("no-such-ref..HEAD")
        self.assertEqual(code, 2, out)
        self.assertIn("git", out)

    def test_wrong_argument_count_is_an_error(self):
        code, out = self.repo.run(SCRIPT, "origin/main..HEAD")
        self.assertEqual(code, 2, out)
        self.assertIn("用法", out)

    def test_output_survives_a_non_utf8_console(self):
        code, out = self.run_check(self.stage(f"# 见 {FOREIGN}\n"), env_extra={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(code, 1, out)
        self.assertIn(FOREIGN, out)


def uncommented(text):
    """去掉整行注释：workflow 的说明里也写着脚本路径，全文子串匹配会被注释满足。"""
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

    def test_job_is_named_comment_tickets(self):
        # PR 检查列表显示的就是 job id；注册表 `ci:comment-tickets` 指的就是它。
        self.assertIn("\n  comment-tickets:\n", self.text)

    def test_job_runs_the_script(self):
        self.assertIn("python3 tool/check_comment_tickets.py", self.job("comment-tickets"))

    def test_job_checks_the_pull_request_range(self):
        job = self.job("comment-tickets")
        self.assertIn("pull_request.base.sha", job)
        self.assertIn("pull_request.head.sha", job)

    def test_checkout_keeps_enough_history(self):
        # 浅克隆里 base 不是本地的祖先，`base..head` 取不到 PR 的改动。
        self.assertIn("fetch-depth: 0", self.job("comment-tickets"))


if __name__ == "__main__":
    unittest.main()
