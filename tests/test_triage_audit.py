"""triage 四条集合判据（devtools/triage_audit.py，#1019）。

判据正文在 docs/agents/triage-labels.md，脚本是它的机械镜像。这里的对拍用例把文档里
`## 标签登记` 那张表与脚本的 `KNOWN` 常量逐项比，两边不等即红；真实 `gh` 调用只在
`ci:triage-audit` 里跑，本地用 `--input` 注入，用例不联网。
"""
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

from devtools import triage_audit  # noqa: E402
from fixtures import FakeRunner  # noqa: E402

LABEL_FILE = ROOT / "docs/agents/triage-labels.md"
REGISTRY_SECTION = "## 标签登记"
LABEL = re.compile(r"`([^`]+)`")


def ticket(number, *names):
    return {"number": number, "labels": [{"name": name} for name in names]}


def rules_hit(lines):
    """audit() 输出里的判据 id 集合，用来断言命中的是哪一条。"""
    return {line.split()[1] for line in lines}


def registered_labels(text):
    """`## 标签登记` 一节表格首列的标签名；这一节是登记集的单一来源。"""
    found, inside = set(), False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == REGISTRY_SECTION
            continue
        if not inside or not line.lstrip().startswith("|"):
            continue
        cell = line.strip().strip("|").split("|")[0]
        match = LABEL.search(cell)
        if match:
            found.add(match.group(1))
    return found


class AuditTests(unittest.TestCase):
    def test_clean_tickets_report_nothing(self):
        self.assertEqual(triage_audit.audit([ticket(1, "bug", "needs-triage")]), [])

    def test_empty_list_reports_nothing(self):
        self.assertEqual(triage_audit.audit([]), [])

    def test_missing_category_is_reported(self):
        lines = triage_audit.audit([ticket(11, "needs-triage")])
        self.assertEqual(rules_hit(lines), {"doc.triage.one-category-label"})
        self.assertTrue(lines[0].startswith(f"#{11} "))

    def test_two_categories_are_reported(self):
        lines = triage_audit.audit([ticket(12, "bug", "enhancement")])
        self.assertEqual(rules_hit(lines), {"doc.triage.one-category-label"})

    def test_waiting_for_verify_outranks_each_role(self):
        for role in ("needs-info", "ready-for-agent", "ready-for-human"):
            with self.subTest(role=role):
                lines = triage_audit.audit([ticket(13, "bug", "waiting-for-verify", role)])
                self.assertEqual(rules_hit(lines), {"doc.triage.waiting-for-verify-outranks"})

    def test_several_outranked_roles_are_reported(self):
        lines = triage_audit.audit(
            [ticket(18, "bug", "waiting-for-verify", "needs-info", "ready-for-agent")])
        self.assertEqual(rules_hit(lines), {"doc.triage.waiting-for-verify-outranks"})

    def test_in_progress_never_rides_with_waiting_for_verify(self):
        lines = triage_audit.audit([ticket(14, "bug", "in-progress", "waiting-for-verify")])
        self.assertEqual(rules_hit(lines), {"doc.triage.in-progress-is-a-claim"})

    def test_blocked_on_device_rides_with_waiting_for_verify(self):
        lines = triage_audit.audit([ticket(17, "bug", "waiting-for-verify", "blocked-on-device")])
        self.assertEqual(lines, [], "blocked-on-device 是修饰标签，不压过也不冲突")

    def test_unregistered_label_is_reported(self):
        lines = triage_audit.audit([ticket(15, "bug", "wont-do")])
        self.assertEqual(rules_hit(lines), {"doc.triage.five-roles-map"})
        self.assertIn("wont-do", lines[0])

    def test_a_ticket_without_labels_shows_the_placeholder(self):
        lines = triage_audit.audit([ticket(19)])
        self.assertEqual(rules_hit(lines), {"doc.triage.one-category-label"})
        self.assertTrue(lines[0].endswith("  (无标签)"), "占位符在行尾，不是被包起来")

    def test_line_carries_rule_and_labelled_set(self):
        lines = triage_audit.audit([ticket(9, "needs-triage", "bug", "enhancement")])
        self.assertIn(f"#{9}  doc.triage.one-category-label  bug,enhancement,needs-triage", lines)

    def test_findings_stay_sorted_by_ticket(self):
        lines = triage_audit.audit([ticket(30), ticket(2), ticket(11)])
        self.assertEqual([line.split()[0] for line in lines], [f"#{2}", f"#{11}", f"#{30}"])

    def test_second_category_clears_once_removed(self):
        self.assertTrue(triage_audit.audit([ticket(16, "bug", "enhancement")]))
        self.assertEqual(triage_audit.audit([ticket(16, "enhancement")]), [])


class MessageTests(unittest.TestCase):
    """`hits()` 给出的逐句现场：`audit()` 只留判据 id，这些文案只有这里能守住。"""

    def message(self, names, rule):
        found = dict(triage_audit.hits(names))
        self.assertIn(rule, found)
        return found[rule]

    def test_missing_category_says_none_was_found(self):
        self.assertEqual(self.message(["needs-triage"], triage_audit.ONE_CATEGORY),
                         "分类要恰好一个：一个都没有")

    def test_two_categories_are_named(self):
        self.assertEqual(self.message(["bug", "enhancement"], triage_audit.ONE_CATEGORY),
                         "分类要恰好一个：bug、enhancement")

    def test_outranked_roles_are_joined(self):
        message = self.message(["bug", "waiting-for-verify", "needs-info", "ready-for-agent"],
                               triage_audit.VERIFY_OUTRANKS)
        self.assertIn("不能再带 needs-info、ready-for-agent", message)

    def test_unregistered_label_is_named(self):
        self.assertEqual(self.message(["bug", "wont-do"], triage_audit.MAPPED),
                         "标签没在 triage-labels.md 登记：wont-do")

    def test_several_unregistered_labels_are_joined_and_sorted(self):
        self.assertEqual(self.message(["bug", "wont-do", "mystery"], triage_audit.MAPPED),
                         "标签没在 triage-labels.md 登记：mystery、wont-do")


class MainTests(unittest.TestCase):
    def runner_with(self, payload=None, error=None):
        """假执行器：联网路径交回这份 payload，给了 error 就抛出。"""
        reply = error if error is not None else (
            json.dumps(payload if payload is not None else []), "", 0)
        return FakeRunner(runs=reply)

    def run_main(self, argv, runner=None):
        runner = runner or self.runner_with()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = triage_audit.main(argv, runner=runner.run)
        return code, out.getvalue(), err.getvalue()

    def write_dump(self, payload):
        """把一份 JSON 落盘成 `--input` 要读的文件；目录随用例结束清掉。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "issues.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def test_input_flag_reads_a_dumped_issue_list(self):
        code, out, _ = self.run_main(["--input", self.write_dump([ticket(5, "bug")])])
        self.assertEqual(code, triage_audit.EXIT_OK)
        self.assertEqual(out.strip(), "1 张 open 票，四条标签判据全绿。")

    def test_the_dump_is_read_as_utf8(self):
        """编码在 ASCII 标签上没有可观察差异，只能从调用参数上钉住（#1522）。"""
        dump = self.write_dump([ticket(5, "bug")])
        reads = []
        real = Path.read_text

        def spy(target, *args, **kwargs):
            reads.append(kwargs)
            return real(target, *args, **kwargs)

        with mock.patch.object(Path, "read_text", spy):
            code, _, _ = self.run_main(["--input", dump])
        self.assertEqual(code, triage_audit.EXIT_OK)
        self.assertEqual(reads, [{"encoding": "utf-8"}])

    def test_findings_exit_one_and_print_each_line(self):
        payload = [ticket(5, "bug", "enhancement")]
        code, out, err = self.run_main(["--input", self.write_dump(payload)])
        self.assertEqual(code, triage_audit.EXIT_FINDINGS)
        self.assertIn(f"#{5}  doc.triage.one-category-label", out)
        self.assertIn("1 条违规，涉及 1 张票。", err)

    def test_several_findings_keep_their_own_lines(self):
        """两条违规各占一行：行间不能被换行连接符的改动粘在一起。"""
        payload = [ticket(5, "bug", "enhancement"), ticket(6, "needs-triage")]
        code, out, _ = self.run_main(["--input", self.write_dump(payload)])
        self.assertEqual(code, triage_audit.EXIT_FINDINGS)
        self.assertIn("#5  doc.triage.one-category-label  bug,enhancement\n"
                      "#6  doc.triage.one-category-label  needs-triage", out)

    def test_fetch_failure_is_not_a_finding(self):
        code, _, err = self.run_main([], runner=self.runner_with(error=OSError("gh 没装")))
        self.assertEqual(code, triage_audit.EXIT_UNREACHABLE)
        self.assertIn("跑不了 gh", err)

    def test_network_path_reaches_the_same_verdict(self):
        """联网路径真的走通了：同一份票，结论与 `--input` 那条一致。"""
        payload = [ticket(5, "bug", "enhancement")]
        code, out, _ = self.run_main([], runner=self.runner_with(payload))
        self.assertEqual(code, triage_audit.EXIT_FINDINGS)
        self.assertIn(f"#{5}  doc.triage.one-category-label", out)

    def test_network_path_asks_for_the_labels_of_open_tickets(self):
        runner = self.runner_with()
        self.run_main([], runner=runner)
        self.assertEqual([(call.script, call.args) for call in runner.run_calls],
                         [("gh", ("issue", "list", "--state", "open", "--limit",
                                  str(triage_audit.LIMIT), "--json", triage_audit.FIELDS))])

    def test_both_input_sources_share_one_shape_check(self):
        """同一份坏形状，两条来源报同一句判据，只是出处不同（#1218）。"""
        payload = [{"labels": []}]
        _, _, offline = self.run_main(["--input", self.write_dump(payload)])
        _, _, online = self.run_main([], runner=self.runner_with(payload))
        self.assertIn("`gh issue list` 里有条目缺 number", online)
        self.assertIn("issues.json", offline)
        self.assertIn("里有条目缺 number", offline)

    def test_a_non_json_failure_names_the_gh_command(self):
        """取数中途失败时，报错要带上是哪条 `gh` 命令出的问题。"""
        runner = FakeRunner(runs=("", "boom", 1))
        code, _, err = self.run_main([], runner=runner)
        self.assertEqual(code, triage_audit.EXIT_UNREACHABLE)
        self.assertIn("`gh issue list` 退出码非零", err)

    def test_an_input_value_may_contain_equals_signs(self):
        """`--input=<路径>` 只按第一个 `=` 切开，路径里再出现 `=` 也整段保留。"""
        self.assertEqual(triage_audit.parse_args(["--input=a=b"]), "a=b")

    def test_dump_that_is_not_the_expected_shape_is_unreachable(self):
        cases = {
            "顶层是对象": ({"message": "gh 报错"}, "顶层不是数组"),
            "标签被压平成字符串": ([{"number": 1, "labels": ["bug"]}], "labels 不是对象数组"),
            "条目缺 number": ([{"labels": []}], "缺 number"),
        }
        for name, (payload, reason) in cases.items():
            with self.subTest(name):
                code, _, err = self.run_main(["--input", self.write_dump(payload)])
                self.assertEqual(code, triage_audit.EXIT_UNREACHABLE)
                self.assertIn(reason, err)

    def test_unreadable_input_is_unreachable(self):
        code, _, err = self.run_main(["--input", "/nonexistent/issues.json"])
        self.assertEqual(code, triage_audit.EXIT_UNREACHABLE)
        self.assertIn("读不了", err)

    def test_empty_input_value_never_falls_back_to_the_network(self):
        for argv in (["--input="], ["--input", ""], ["--input"]):
            with self.subTest(argv=argv):
                code, _, err = self.run_main(argv)
                self.assertEqual(code, triage_audit.EXIT_UNREACHABLE)
                self.assertEqual(err.splitlines()[0], "--input 后面要给路径")

    def test_unknown_argument_is_unreachable(self):
        code, _, err = self.run_main(["--nope"])
        self.assertEqual(code, triage_audit.EXIT_UNREACHABLE)
        self.assertIn("--nope", err)


class RegistryTests(unittest.TestCase):
    def test_known_matches_the_document(self):
        registered = registered_labels(LABEL_FILE.read_text(encoding="utf-8"))
        self.assertTrue(registered, "登记表里一个标签都没解析出来，这条对拍会空转")
        self.assertEqual(sorted(registered), sorted(triage_audit.KNOWN))


if __name__ == "__main__":
    unittest.main()
