"""开工认领（devtools/claim.py）：一条命令写认领评论 + 摘待办标签，仲裁只看票下的评论（#932）。"""
import copy
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import fixtures  # noqa: E402
from devtools import claim  # noqa: E402

HOST = "box"
WORKTREE = "/Volumes/wt/932"
ME = claim.session_id(HOST, WORKTREE)
OTHER = claim.session_id(HOST, "/Volumes/wt/999")
WHO = claim.Session(ME, "feat/claim-command-932")
NOW = datetime(2026, 11, 10, 12, 30)
POSTED = "2026-11-10T04:30:00Z"
COMMENT_URL = "https://github.com/owner/repo/issues/932#issuecomment-777"


def ticket(comments=(), labels=("ready-for-agent",), state="OPEN"):
    return {
        "number": 932,
        "state": state,
        "url": "https://github.com/owner/repo/issues/932",
        "labels": [{"name": name} for name in labels],
        "comments": list(comments),
    }


def claim_comment(session, created="2026-11-10T04:03:00Z", labels=("ready-for-agent",),
                  branch="feat/x", stamp="2026-11-10 12:03"):
    kept = ", ".join(f"`{name}`" for name in labels) if labels else claim.EMPTY_LABELS
    body = f"**认领中**：session `{session}` · branch `{branch}` · {stamp}\n{claim.LABEL_KEY}{kept}"
    return {"body": body, "createdAt": created, "url": f"https://example/{session}",
            "author": {"login": "rikki"}}


def legacy_claim_comment(host, worktree, session="old-style-key",
                         created="2026-11-10T04:03:00Z", branch="feat/x",
                         stamp="2026-11-10 12:03"):
    """#970 之前的格式：评论里写着 host 与 worktree，键要靠它们重算。"""
    body = (f"**认领中**：session `{session}` · host `{host}` · branch `{branch}` · "
            f"worktree `{worktree}` · {stamp}\n{claim.LABEL_KEY}`ready-for-agent`")
    return {"body": body, "createdAt": created, "url": f"https://example/{session}",
            "author": {"login": "rikki"}}


def end_comment(kind, session, created):
    body = f"**{kind}**：session `{session}` · branch `feat/x` · 2026-11-10 13:00"
    return {"body": body, "createdAt": created, "url": "https://example/end",
            "author": {"login": "rikki"}}


class FakeGh:
    """假 `gh`：票面按注释写回（`issue comment` 之后重读能看见），并可给「重读时才发现」的评论。

    overlay 模拟并发交错：两路都读到空票，后写的那路重读时才发现有人更早。
    """

    def __init__(self, issue=None, prs=(), comment_rc=0, edit_rc=0, pr_rc=0, pr_text=None):
        self.issue = issue
        self.overlay = None
        self.reread = None
        self.prs = list(prs)
        self.comment_rc, self.edit_rc = comment_rc, edit_rc
        self.pr_rc, self.pr_text = pr_rc, pr_text
        self.views, self.comments, self.edits, self.deletes = 0, [], [], []
        self.runner = fixtures.FakeRunner(runs=self.route)

    def route(self, script, *args):
        assert script == "gh", f"只该调 gh，收到 {script}"
        if args[:2] == ("issue", "view"):
            return self._view()
        if args[:2] == ("issue", "comment"):
            return self._comment(args)
        if args[:2] == ("issue", "edit"):
            return self._edit(args)
        if args[:2] == ("pr", "list"):
            return self._pr()
        if args[:3] == ("api", "--method", "DELETE"):
            return self._delete(args[3])
        raise AssertionError(f"没预料到的 gh 调用：{args}")

    def _view(self):
        if self.issue is None:
            return "", "no issues found", 1
        self.views += 1
        if self.reread is not None and self.views > 1:
            return json.dumps(copy.deepcopy(self.reread)), "", 0
        payload = copy.deepcopy(self.issue)
        if self.overlay is not None and self.views > 1:
            payload["comments"] += copy.deepcopy(self.overlay)
        return json.dumps(payload), "", 0

    def _pr(self):
        if self.pr_rc:
            return "", "boom", self.pr_rc
        return self.pr_text if self.pr_text is not None else json.dumps(self.prs), "", 0

    def _comment(self, args):
        body = args[args.index("--body") + 1]
        if self.comment_rc:
            return "", "boom", self.comment_rc
        self.comments.append(body)
        self.issue["comments"].append({"body": body, "createdAt": POSTED,
                                       "url": COMMENT_URL, "author": {"login": "rikki"}})
        return COMMENT_URL, "", 0

    def _edit(self, args):
        self.edits.append(list(args))
        return ("", "boom", self.edit_rc) if self.edit_rc else ("", "", 0)

    def _delete(self, path):
        self.deletes.append(path)
        ident = path.rsplit("/", 1)[-1]
        self.issue["comments"] = [item for item in self.issue["comments"]
                                  if not (item.get("url") or "").endswith(f"-{ident}")]
        return "", "", 0


class ClaimTests(unittest.TestCase):
    def go(self, gh, **kwargs):
        with patch.object(claim, "session_context", return_value=WHO) as context:
            result = claim.command(932, now=NOW, runner=gh.runner.run, **kwargs)
        context.assert_called_once_with(cwd=None, host=None)
        return result

    def test_empty_ticket_is_claimed_with_a_comment_and_a_label_swap(self):
        gh = FakeGh(ticket())
        code, message = self.go(gh)
        self.assertEqual((code, message), (0, f"#932 已认领（{ME}）"))
        expected_body = (f"**{claim.CLAIMED}**：session `{ME}` · branch `feat/claim-command-932` · "
                         f"2026-11-10 12:30\n{claim.LABEL_KEY}`ready-for-agent`")
        self.assertEqual(gh.comments, [expected_body],
                         "空票上要留一条认领评论，时间用注入的时刻")
        self.assertNotIn(HOST, gh.comments[0], "评论里不该出现主机名（#970）")
        self.assertNotIn(WORKTREE, gh.comments[0], "评论里不该出现 worktree 绝对路径（#970）")
        self.assertEqual(gh.edits, [["issue", "edit", "932",
                                     "--add-label", "in-progress",
                                     "--remove-label", "ready-for-agent"]])
        self.assertEqual(gh.deletes, [], "没有争抢时不该撤回自己那条")
        calls = [(call.script, *call.args) for call in gh.runner.run_calls]
        self.assertEqual(calls, [
            ("gh", "issue", "view", "932", "--json", "number,state,labels,comments,url"),
            ("gh", "issue", "comment", "932", "--body", expected_body),
            ("gh", "issue", "view", "932", "--json", "number,state,labels,comments,url"),
            ("gh", "issue", "edit", "932", "--add-label", "in-progress",
             "--remove-label", "ready-for-agent"),
        ])

    def test_claiming_again_from_the_same_session_adds_no_comment(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, message = self.go(gh)
        self.assertEqual((code, message), (0, f"#932 已由本会话持有（{ME}），不重复认领"))
        self.assertEqual(gh.comments, [], "同一 session 重复认领是幂等的 reaffirm")
        self.assertEqual(gh.edits, [["issue", "edit", "932", "--add-label", "in-progress"]])

    def test_an_earlier_open_claim_by_another_session_wins(self):
        gh = FakeGh(ticket([claim_comment(OTHER, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, message = self.go(gh)
        self.assertEqual(code, 2)
        self.assertTrue(message.startswith(f"#932 已被 session `{OTHER}` 认领（"), message)
        self.assertIn("feat/x", message)
        self.assertIn("0 天前", message)
        self.assertIn("该分支没有开着的 PR", message)
        self.assertIn(f"认领记录：https://example/{OTHER}", message)
        self.assertNotIn(WORKTREE, message, "被别人占时也不该把对方的绝对路径打出来（#970）")
        # 展示的是服务器时间换算出来的那一刻，不是正文里手写的 stamp（那条写的是 12:03）
        self.assertNotIn("2026-11-10 12:03", message)
        self.assertEqual(gh.comments, [], "被别人占时不该再写认领评论")
        self.assertEqual(gh.edits, [], "被别人占时不该动标签")

    def test_a_closed_claim_no_longer_blocks(self):
        gh = FakeGh(ticket([claim_comment(OTHER, created="2026-11-10T03:00:00Z"),
                            end_comment(claim.RELEASED, OTHER, "2026-11-10T04:00:00Z")]))
        code, _ = self.go(gh)
        self.assertEqual(code, 0)
        self.assertEqual(len(gh.comments), 1)

    def test_the_earliest_session_keeps_its_claim_even_if_another_joins_later(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z"),
                            claim_comment(OTHER, created="2026-11-10T04:00:00Z")],
                           labels=("in-progress",)))
        code, _ = self.go(gh)
        self.assertEqual(code, 0)
        self.assertEqual(gh.comments, [], "我最早，成功且不追加评论")
        self.assertEqual(len(gh.issue["comments"]), 2, "对方那条认领记录原样留着")

    def test_claiming_a_stale_ticket_drops_the_stale_marker(self):
        gh = FakeGh(ticket(labels=("ready-for-agent", "needs-info", "stale")))
        code, _ = self.go(gh)
        self.assertEqual(code, 0)
        self.assertEqual(gh.edits, [["issue", "edit", "932",
                                     "--add-label", "in-progress",
                                     "--remove-label", "ready-for-agent",
                                     "--remove-label", "stale"]])

    def test_abandon_does_not_bring_the_stale_marker_back(self):
        """旧树也绿，守的是不回退：放弃要把票还给待办池，停摆标记交给下一次扫描重判。"""
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress", "needs-info")))
        code, _ = self.go(gh, action="abandon")
        self.assertEqual(code, 0)
        self.assertEqual(gh.edits, [["issue", "edit", "932",
                                     "--add-label", "ready-for-agent",
                                     "--remove-label", "in-progress"]])

    def test_release_only_drops_in_progress(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, message = self.go(gh, action="release")
        self.assertEqual((code, message), (0, f"#932 的认领已收尾（{ME}）"))
        self.assertEqual(gh.comments, [
            f"**{claim.RELEASED}**：session `{ME}` · branch `feat/claim-command-932` · 2026-11-10 12:30"])
        self.assertEqual(gh.edits, [["issue", "edit", "932", "--remove-label", "in-progress"]])

    def test_abandon_restores_the_labels_recorded_at_claim_time(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, message = self.go(gh, action="abandon")
        self.assertEqual((code, message), (0, f"#932 的认领已放弃（{ME}），已恢复 ready-for-agent"))
        self.assertEqual(gh.comments, [
            f"**{claim.ABANDONED}**：session `{ME}` · branch `feat/claim-command-932` · "
            f"2026-11-10 12:30\n{claim.RESTORE_KEY}`ready-for-agent`"])
        self.assertEqual(gh.edits, [["issue", "edit", "932",
                                     "--add-label", "ready-for-agent",
                                     "--remove-label", "in-progress"]])

    def test_abandon_without_recorded_labels_says_nothing_was_restored(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z", labels=())],
                           labels=("in-progress",)))
        code, message = self.go(gh, action="abandon")
        self.assertEqual((code, message), (0, f"#932 的认领已放弃（{ME}）"))
        self.assertEqual(gh.comments, [
            f"**{claim.ABANDONED}**：session `{ME}` · branch `feat/claim-command-932` · 2026-11-10 12:30"])
        self.assertEqual(gh.edits, [["issue", "edit", "932", "--remove-label", "in-progress"]])

    def test_abandon_restore_flag_overrides_the_recorded_labels(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                            labels=("in-progress",)))
        code, message = self.go(gh, action="abandon", restore=["ready-for-human"])
        self.assertEqual((code, message), (0, f"#932 的认领已放弃（{ME}），已恢复 ready-for-human"))
        self.assertEqual(gh.edits, [["issue", "edit", "932",
                                     "--add-label", "ready-for-human",
                                     "--remove-label", "in-progress"]])

    def test_abandon_with_several_restore_labels_joins_them_with_a_comma(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, message = self.go(gh, action="abandon", restore=["a", "b"])
        self.assertEqual((code, message), (0, f"#932 的认领已放弃（{ME}），已恢复 a, b"))
        self.assertEqual(gh.comments, [
            f"**{claim.ABANDONED}**：session `{ME}` · branch `feat/claim-command-932` · "
            f"2026-11-10 12:30\n{claim.RESTORE_KEY}`a`, `b`"])
        self.assertEqual(gh.edits, [["issue", "edit", "932", "--add-label", "a", "--add-label", "b",
                                     "--remove-label", "in-progress"]])

    def test_both_closing_verbs_post_on_the_ticket_itself(self):
        for verb in ("release", "abandon"):
            with self.subTest(verb=verb):
                gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                                   labels=("in-progress",)))
                self.go(gh, action=verb)
                posted = [call.args for call in gh.runner.run_calls
                          if call.args[:2] == ("issue", "comment")]
                self.assertEqual([args[2] for args in posted], ["932"])

    def test_release_without_a_claim_from_this_session_is_refused(self):
        gh = FakeGh(ticket([], labels=("in-progress",)))
        code, message = self.go(gh, action="release")
        self.assertEqual((code, message), (1, f"#932 上没有本会话（{ME}）的未收尾认领，不用收尾"))
        self.assertEqual(gh.comments + gh.edits, [])

    def test_unknown_ticket_is_a_gh_failure(self):
        gh = FakeGh(None)
        code, message = self.go(gh)
        self.assertEqual((code, message), (3, "`gh issue view 932` 退出码非零：no issues found"))
        self.assertEqual(gh.comments + gh.edits, [])

    def test_closed_ticket_is_refused(self):
        gh = FakeGh(ticket(state="CLOSED"))
        code, message = self.go(gh)
        self.assertEqual((code, message), (1, "#932 已经是 CLOSED，不再认领"))
        self.assertEqual(gh.comments + gh.edits, [])

    def test_an_unreadable_claim_comment_stops_instead_of_guessing(self):
        broken = {"body": "**认领中**：我占了", "createdAt": "2026-11-10T03:00:00Z",
                  "url": "https://example/broken", "author": {"login": "someone"}}
        gh = FakeGh(ticket([broken]))
        code, message = self.go(gh)
        self.assertEqual(code, 1)
        self.assertEqual(
            message,
            "#932 的认领记录读不出确定结局：https://example/broken 的认领评论读不全：缺 session、branch。"
            "先手工核对那条评论；票被卡住时可以 gh issue edit 932 --remove-label in-progress")
        self.assertEqual(gh.comments + gh.edits, [])

    def test_a_failed_comment_leaves_the_labels_alone(self):
        gh = FakeGh(ticket(), comment_rc=1)
        code, message = self.go(gh)
        self.assertEqual((code, message), (3, "写认领评论失败：boom"))
        self.assertEqual(gh.edits, [])

    def test_a_failed_label_write_is_advisory(self):
        gh = FakeGh(ticket(), edit_rc=1)
        code, message = self.go(gh)
        self.assertEqual(code, 0, "认领记录以评论为准，标签只是可见信号")
        self.assertEqual(message, f"#932 已认领（{ME}）；标签没写成功（boom），认领记录以评论为准")

    def test_two_concurrent_claims_from_one_session_keep_the_earlier_comment(self):
        gh = FakeGh(ticket())
        gh.overlay = [claim_comment(ME, created="2026-11-10T04:29:00Z")]
        code, message = self.go(gh)
        self.assertEqual(code, 0, "同一会话不算争抢，认领仍然成立")
        self.assertEqual(len(gh.deletes), 1, "同一会话的两条认领记录，撤回晚的那条")
        self.assertTrue(message.startswith(f"#932 已认领（{ME}）"), message)

    def test_a_comment_written_after_an_earlier_claim_is_withdrawn(self):
        gh = FakeGh(ticket())
        gh.overlay = [claim_comment(OTHER, created="2026-11-10T04:29:00Z")]
        code, message = self.go(gh)
        self.assertEqual(code, 2, "重读时发现别人更早，后写的那路要让出")
        self.assertEqual(len(gh.comments), 1, "自己那条写过")
        self.assertEqual(len(gh.deletes), 1, "响应地撤回它")
        self.assertTrue(message.startswith(f"并发认领：#932 已被 session `{OTHER}` 认领（"), message)
        self.assertIn("该分支没有开着的 PR", message)
        self.assertIn("已撤回本会话刚写的认领评论", message)
        self.assertEqual(gh.edits, [], "让出时不摘待办标签")

    def test_a_concurrent_reread_with_no_decidable_record_names_the_ticket(self):
        gh = FakeGh(ticket())
        gh.reread = ticket([end_comment(claim.RELEASED, OTHER, "2026-11-10T04:00:00Z")])
        code, message = self.go(gh)
        self.assertEqual(code, 2)
        self.assertIn("#932 上没有可判定的认领记录", message)
        self.assertEqual(len(gh.deletes), 1)

    def test_an_earlier_closed_record_is_not_mistaken_for_ours(self):
        # 重读里排在前面的是别人的收尾记录：`ours` 只看「开着且属于本会话」的，别把它当自己的早评论。
        gh = FakeGh(ticket([end_comment(claim.RELEASED, OTHER, "2026-11-10T04:00:00Z")]))
        code, message = self.go(gh)
        self.assertEqual((code, message), (0, f"#932 已认领（{ME}）"))
        self.assertEqual(gh.deletes, [], "本会话只有一条认领，没有可撤回的")

    def test_an_earlier_closed_record_of_ours_does_not_trigger_a_withdraw(self):
        gh = FakeGh(ticket([end_comment(claim.RELEASED, ME, "2026-11-10T04:00:00Z")]))
        code, message = self.go(gh)
        self.assertEqual((code, message), (0, f"#932 已认领（{ME}）"))
        self.assertEqual(gh.deletes, [])

    def test_the_default_runner_is_built_for_the_working_directory(self):
        gh = FakeGh(ticket())
        with patch.object(claim, "session_context", return_value=WHO), \
                patch.object(claim, "runner_for", return_value=gh.runner.run) as build:
            code, _ = claim.command(932, cwd="/here", now=NOW)
        build.assert_called_once_with("/here")
        self.assertEqual(code, 0)

    def test_command_forwards_cwd_and_host_to_the_session(self):
        gh = FakeGh(ticket())
        with patch.object(claim, "session_context", return_value=WHO) as context:
            code, _ = claim.command(932, runner=gh.runner.run, cwd="/here", host="box", now=NOW)
        context.assert_called_once_with(cwd="/here", host="box")
        self.assertEqual(code, 0)


class ParsingTests(unittest.TestCase):
    def test_the_host_is_shortened_to_its_first_label(self):
        with patch.object(claim.socket, "gethostname", return_value="box.example.com"), \
                patch.object(claim, "git_text", side_effect=["/wt/x", "feat/y"]):
            who = claim.session_context()
        self.assertEqual(who.branch, "feat/y")
        self.assertEqual(who.session, claim.session_id("box", "/wt/x"))

    def test_the_identity_key_depends_on_both_the_host_and_the_worktree(self):
        self.assertNotEqual(claim.session_id("a", "/w"), claim.session_id("b", "/w"),
                            "换主机名要换键，否则 #970 里主机名就成了白丢的信息")
        self.assertNotEqual(claim.session_id("a", "/w1"), claim.session_id("a", "/w2"))
        self.assertEqual(claim.session_id("a", "/w"), claim.session_id("a", "/w"))

    def test_a_written_claim_body_parses_back_into_itself(self):
        body = claim.claim_body(WHO, NOW, ("ready-for-agent",))
        record = claim.parse_comment({"body": body, "createdAt": POSTED, "url": COMMENT_URL})
        self.assertEqual((record.kind, record.session, record.branch, record.stamp, record.url),
                         (claim.CLAIMED, ME, "feat/claim-command-932", "2026-11-10 12:30", COMMENT_URL))
        self.assertEqual(record.labels, ("ready-for-agent",))

    def test_a_claim_body_without_labels_says_none_were_recorded(self):
        self.assertEqual(claim.claim_body(WHO, NOW, ()),
                         f"**{claim.CLAIMED}**：session `{ME}` · branch `feat/claim-command-932` · "
                         f"2026-11-10 12:30\n{claim.LABEL_KEY}{claim.EMPTY_LABELS}")

    def test_a_written_claim_body_does_not_name_the_host_or_worktree(self):
        body = claim.claim_body(WHO, NOW, ("ready-for-agent",))
        self.assertNotIn(HOST, body)
        self.assertNotIn(WORKTREE, body)
        self.assertNotIn("host `", body)
        self.assertNotIn("worktree `", body)
        self.assertIn(f"session `{ME}`", body)

    def test_a_legacy_comment_is_rekeyed_from_its_host_and_worktree(self):
        record = claim.parse_comment(legacy_claim_comment(HOST, WORKTREE))
        self.assertEqual(record.session, ME, "旧格式用 host 与 worktree 重算成同一个键")

    def test_a_legacy_claim_and_a_new_claim_resolve_to_the_same_session(self):
        legacy = claim.parse_comment(legacy_claim_comment(HOST, WORKTREE))
        fresh = claim.parse_comment({"body": claim.claim_body(WHO, NOW, ()), "createdAt": POSTED})
        self.assertEqual(legacy.session, fresh.session)

    def test_a_legacy_comment_rekeys_even_when_the_session_literal_disagrees(self):
        record = claim.parse_comment(
            legacy_claim_comment(HOST, WORKTREE, session="someone-typed-this"))
        self.assertEqual(record.session, ME, "有 host 与 worktree 时以重算值为准")

    def test_a_legacy_comment_with_only_one_of_host_and_worktree_is_unreadable(self):
        bodies = ("**认领中**：session `old` · host `box` · branch `feat/x` · 2026-11-10 12:03",
                  "**认领中**：session `old` · worktree `/wt` · branch `feat/x` · 2026-11-10 12:03")
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(claim.Unreadable) as caught:
                    claim.parse_comment({"body": body, "createdAt": POSTED, "url": COMMENT_URL})
                self.assertEqual(str(caught.exception),
                                 f"{COMMENT_URL} 的认领评论只写了 host 与 worktree 中的一个，判不了身份键")
        with self.assertRaises(claim.Unreadable) as caught:
            claim.parse_comment({"body": bodies[0], "createdAt": POSTED})
        self.assertEqual(str(caught.exception),
                         "无链接 的认领评论只写了 host 与 worktree 中的一个，判不了身份键")

    def test_an_ordinary_comment_is_not_a_claim(self):
        self.assertIsNone(claim.parse_comment({"body": "看起来不错", "createdAt": POSTED}))

    def test_an_empty_body_is_not_a_claim(self):
        self.assertIsNone(claim.parse_comment({"body": "", "createdAt": POSTED}))
        self.assertIsNone(claim.parse_comment({"createdAt": POSTED}))

    def test_a_claim_with_several_labels_parses_them_all(self):
        body = claim.claim_body(WHO, NOW, ("ready-for-agent", "needs-triage"))
        record = claim.parse_comment({"body": body, "createdAt": POSTED})
        self.assertEqual(record.labels, ("ready-for-agent", "needs-triage"))

    def test_records_on_the_same_second_keep_their_comment_order(self):
        first = claim_comment(OTHER, created="2026-11-10T04:03:00Z")
        second = end_comment(claim.RELEASED, OTHER, "2026-11-10T04:03:00Z")
        self.assertEqual([record.kind for record in claim.parse_records([first, second])],
                         [claim.CLAIMED, claim.RELEASED])

    def test_claiming_on_an_empty_ticket_records_no_original_labels(self):
        body = claim.claim_body(WHO, NOW, ())
        record = claim.parse_comment({"body": body, "createdAt": POSTED})
        self.assertEqual(record.labels, ())

    def test_a_claim_comment_without_created_at_is_unreadable(self):
        body = claim.claim_body(WHO, NOW, ())
        with self.assertRaises(claim.Unreadable) as caught:
            claim.parse_comment({"body": body, "url": COMMENT_URL})
        self.assertEqual(str(caught.exception),
                         f"{COMMENT_URL} 的认领评论没有 createdAt，判不了先后")

    def test_a_claim_comment_without_a_url_records_no_url(self):
        body = claim.claim_body(WHO, NOW, ())
        self.assertEqual(claim.parse_comment({"body": body, "createdAt": POSTED}).url, "")

    def test_a_claim_comment_without_a_url_still_names_the_gap(self):
        body = claim.claim_body(WHO, NOW, ())
        with self.assertRaises(claim.Unreadable) as caught:
            claim.parse_comment({"body": body})
        self.assertEqual(str(caught.exception), "无链接 的认领评论没有 createdAt，判不了先后")

    def test_a_claim_comment_with_a_missing_stamp_names_the_time_gap(self):
        body = "**认领中**：session `x` · branch `feat/y`"
        with self.assertRaises(claim.Unreadable) as caught:
            claim.parse_comment({"body": body, "createdAt": POSTED, "url": COMMENT_URL})
        self.assertEqual(str(caught.exception),
                         f"{COMMENT_URL} 的认领评论读不全：缺 时间")

    def test_a_claim_comment_without_a_url_and_fields_names_the_gap(self):
        with self.assertRaises(claim.Unreadable) as caught:
            claim.parse_comment({"body": "**认领中**：我占了", "createdAt": POSTED})
        self.assertEqual(str(caught.exception), "无链接 的认领评论读不全：缺 session、branch")


class GitTextTests(unittest.TestCase):
    """`session_context` 底下那一步：起 git、取标准输出、失败统一成 RuntimeError（#1520）。"""

    def run_git(self, stdout="", stderr="", rc=0, **kwargs):
        done = subprocess.CompletedProcess(["git"], rc, stdout=stdout, stderr=stderr)
        with patch.object(claim.subprocess, "run", return_value=done) as run:
            value = claim.git_text("rev-parse", "--show-toplevel", **kwargs)
        return run.call_args, value

    def test_the_command_and_decoding_are_pinned(self):
        (argv, kwargs), _ = self.run_git(cwd="/wt", stdout=" /wt/x \n")
        self.assertEqual(argv[0], ["git", "rev-parse", "--show-toplevel"])
        self.assertEqual(kwargs, {"cwd": "/wt", "capture_output": True, "text": True,
                                  "encoding": "utf-8", "errors": "replace"})

    def test_the_stdout_comes_back_stripped(self):
        _, value = self.run_git(stdout=" feat/x \n")
        self.assertEqual(value, "feat/x")

    def test_a_failure_reports_stderr(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_git(rc=128, stderr="fatal: not a git repository\n")
        self.assertEqual(str(caught.exception), "fatal: not a git repository")

    def test_a_failure_without_stderr_falls_back_to_stdout(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_git(rc=1, stdout="error: bad\n")
        self.assertEqual(str(caught.exception), "error: bad")

    def test_a_silent_failure_says_git_failed(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_git(rc=1)
        self.assertEqual(str(caught.exception), "git 调用失败")


class SessionContextTests(unittest.TestCase):
    def test_the_worktree_then_the_branch_are_read_with_the_same_cwd(self):
        calls = []

        def git(*args, cwd=None):
            calls.append((args, cwd))
            return "/wt/x" if args[-1] == "--show-toplevel" else "feat/y"

        with patch.object(claim, "git_text", git):
            who = claim.session_context(cwd="/here", host="box.example.com")
        self.assertEqual(calls, [(("rev-parse", "--show-toplevel"), "/here"),
                                 (("rev-parse", "--abbrev-ref", "HEAD"), "/here")])
        self.assertEqual(who, claim.Session(claim.session_id("box.example.com", "/wt/x"), "feat/y"))

    def test_an_explicit_host_wins_over_the_machine_name(self):
        with patch.object(claim, "git_text", side_effect=["/wt/x", "feat/y"]):
            who = claim.session_context(host="box")
        self.assertEqual(who.session, claim.session_id("box", "/wt/x"))


class ParseArgsTests(unittest.TestCase):
    """命令行解析的每个出口（#1520）。"""

    def test_a_plain_number_is_a_claim(self):
        self.assertEqual(claim.parse_args(["932"]), (932, "claim", []))

    def test_release_and_abandon_are_named_actions(self):
        self.assertEqual(claim.parse_args(["932", "--release"]), (932, "release", []))
        self.assertEqual(claim.parse_args(["932", "--abandon"]), (932, "abandon", []))

    def test_restore_labels_are_collected_in_order(self):
        self.assertEqual(claim.parse_args(["932", "--abandon", "--restore", "a", "--restore", "b"]),
                         (932, "abandon", ["a", "b"]))

    def check(self, argv, fragment):
        with self.assertRaises(ValueError) as caught:
            claim.parse_args(argv)
        self.assertIn(fragment, str(caught.exception))
        self.assertIn(claim.USAGE, str(caught.exception))

    def test_a_missing_ticket_is_a_usage_error(self):
        self.check([], claim.USAGE)

    def test_two_actions_are_rejected(self):
        self.check(["--release", "--abandon"], "只能给一个动作，收到 --release 与 --abandon")

    def test_restore_needs_a_label(self):
        self.check(["--restore"], "--restore 后面要跟标签名")

    def test_unknown_options_are_rejected(self):
        self.check(["-x"], "不认识的选项 -x")

    def test_two_ticket_numbers_are_rejected(self):
        self.check(["932", "933"], "一次只认领一张票，收到 932 与 933")

    def test_a_non_numeric_ticket_is_rejected(self):
        self.check(["abc"], "票号要是数字，收到 abc")

    def test_restore_only_works_with_abandon(self):
        self.check(["932", "--restore", "a"], "--restore 只和 --abandon 一起用")


class MainTests(unittest.TestCase):
    """进程内走 `main`：退出码、消息走哪个流、原文是什么（#1520）。"""

    def run_main(self, argv, gh, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(claim, "session_context", return_value=WHO), \
                redirect_stdout(out), redirect_stderr(err):
            code = claim.main(list(argv), runner=gh.runner.run, now=NOW, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def test_a_claim_prints_to_stdout_and_exits_zero(self):
        gh = FakeGh(ticket())
        code, out, err = self.run_main(["932"], gh)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, f"#932 已认领（{ME}）\n")
        self.assertEqual(gh.comments, [
            f"**{claim.CLAIMED}**：session `{ME}` · branch `feat/claim-command-932` · "
            f"2026-11-10 12:30\n{claim.LABEL_KEY}`ready-for-agent`"])

    def test_a_refusal_prints_to_stderr_and_exits_one(self):
        code, out, err = self.run_main(["932"], FakeGh(ticket(state="CLOSED")))
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "#932 已经是 CLOSED，不再认领\n")

    def test_a_gh_failure_exits_three(self):
        code, out, err = self.run_main(["932"], FakeGh(None))
        self.assertEqual((code, out), (3, ""))
        self.assertEqual(err, "`gh issue view 932` 退出码非零：no issues found\n")

    def test_bad_arguments_exit_one_with_the_usage(self):
        gh = FakeGh(ticket())
        code, out, err = self.run_main(["--nope"], gh)
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("不认识的选项 --nope"), err)
        self.assertIn(claim.USAGE, err)
        self.assertEqual(gh.runner.run_calls, [], "参数不合规时不该碰 gh")

    def test_the_action_and_restore_flags_reach_the_command(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, _, _ = self.run_main(["932", "--abandon", "--restore", "ready-for-human"], gh)
        self.assertEqual(code, 0)
        self.assertEqual(gh.edits, [["issue", "edit", "932", "--add-label", "ready-for-human",
                                     "--remove-label", "in-progress"]])

    def test_cwd_and_host_are_forwarded(self):
        gh = FakeGh(ticket())
        with patch.object(claim, "session_context", return_value=WHO) as context:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = claim.main(["932"], runner=gh.runner.run, cwd="/here", host="box", now=NOW)
        context.assert_called_once_with(cwd="/here", host="box")
        self.assertEqual(code, 0)


class GhCommandTests(unittest.TestCase):
    """四条 `gh` 子命令的实参与失败文案（#1520）。"""

    def calls(self, reply, fn, *args):
        recorded = []

        def run(script, *cmd):
            recorded.append((script, *cmd))
            return reply

        return recorded, fn(*args, run)

    def test_read_issue_asks_for_the_fields_the_arbiter_needs(self):
        recorded, issue = self.calls((json.dumps(ticket()), "", 0), claim.read_issue, 932)
        self.assertEqual(recorded, [("gh", "issue", "view", "932", "--json",
                                     "number,state,labels,comments,url")])
        self.assertEqual(issue["number"], 932)

    def test_read_issue_failure_names_the_command(self):
        with self.assertRaises(claim.GhError) as caught:
            self.calls(("", "no issues found", 1), claim.read_issue, 932)
        self.assertEqual(str(caught.exception), "`gh issue view 932` 退出码非零：no issues found")

    def test_open_pr_asks_for_this_branch(self):
        recorded, value = self.calls((json.dumps([{"number": 5}]), "", 0), claim.open_pr, "feat/x")
        self.assertTrue(value)
        self.assertEqual(recorded, [("gh", "pr", "list", "--head", "feat/x", "--state", "open",
                                     "--json", "number")])

    def test_open_pr_is_unknown_when_gh_fails(self):
        self.assertIsNone(self.calls(("", "boom", 1), claim.open_pr, "feat/x")[1])

    def test_open_pr_is_unknown_when_the_output_is_not_json(self):
        self.assertIsNone(self.calls(("not json", "", 0), claim.open_pr, "feat/x")[1])

    def test_post_comment_sends_the_body(self):
        recorded, result = self.calls((COMMENT_URL, "", 0), claim.post_comment, 932, "正文")
        self.assertEqual(result, (COMMENT_URL, None))
        self.assertEqual(recorded, [("gh", "issue", "comment", "932", "--body", "正文")])

    def test_post_comment_failure_returns_the_reason(self):
        _, result = self.calls(("", "boom", 1), claim.post_comment, 932, "正文")
        self.assertEqual(result, (None, "写认领评论失败：boom"))

    def set_labels(self, reply, add, remove):
        # `set_labels(number, runner, add, remove)`：runner 在第二位，和 `calls` 的末位约定不同。
        return self.calls(reply, lambda number, add, remove, run: claim.set_labels(number, run, add, remove),
                          932, add, remove)

    def test_set_labels_adds_then_removes_in_one_edit(self):
        recorded, note = self.set_labels(("", "", 0), ["in-progress"], ["ready-for-agent"])
        self.assertEqual(note, "")
        self.assertEqual(recorded, [("gh", "issue", "edit", "932", "--add-label", "in-progress",
                                     "--remove-label", "ready-for-agent")])

    def test_set_labels_dedupes_each_side(self):
        recorded, _ = self.set_labels(("", "", 0), ["a", "a"], ["b", "b"])
        self.assertEqual(recorded, [("gh", "issue", "edit", "932",
                                     "--add-label", "a", "--remove-label", "b")])

    def test_set_labels_with_nothing_to_do_makes_no_call(self):
        recorded, note = self.set_labels(("", "", 0), [], [])
        self.assertEqual((recorded, note), ([], ""))

    def test_set_labels_failure_is_advisory_text(self):
        _, note = self.set_labels(("", "", 1), ["a"], [])
        self.assertEqual(note, "；标签没写成功（gh 返回非零），认领记录以评论为准")


class WithdrawTests(unittest.TestCase):
    def run_withdraw(self, reply, url=COMMENT_URL, issue=None):
        recorded = []

        def run(script, *args):
            recorded.append((script, *args))
            return reply

        return recorded, claim.withdraw(url, issue or ticket(), run)

    def test_delete_hits_the_comment_api(self):
        recorded, note = self.run_withdraw(("", "", 0))
        self.assertEqual(note, "")
        self.assertEqual(recorded, [("gh", "api", "--method", "DELETE",
                                     "repos/owner/repo/issues/comments/777")])

    def test_a_url_without_an_identifier_asks_for_manual_cleanup(self):
        recorded, note = self.run_withdraw(("", "", 0), url="")
        self.assertEqual(recorded, [])
        self.assertEqual(note, "；请手工删除刚写的认领评论 （无链接）")

    def test_an_issue_url_without_a_repo_asks_for_manual_cleanup(self):
        recorded, note = self.run_withdraw(("", "", 0), issue={"url": ""})
        self.assertEqual(recorded, [])
        self.assertEqual(note, f"；请手工删除刚写的认领评论 {COMMENT_URL}")

    def test_a_failed_delete_keeps_the_url_for_a_human(self):
        _, note = self.run_withdraw(("", "boom", 1))
        self.assertEqual(note, f"；撤回失败（boom），请手工删除 {COMMENT_URL}")

    def test_a_failed_delete_without_text_says_gh_returned_nonzero(self):
        _, note = self.run_withdraw(("", "", 1))
        self.assertEqual(note, f"；撤回失败（gh 返回非零），请手工删除 {COMMENT_URL}")


class UrlTests(unittest.TestCase):
    def test_comment_id_accepts_both_github_url_shapes(self):
        self.assertEqual(claim.comment_id("https://github.com/o/r/issues/9#issuecomment-12"), "12")
        self.assertEqual(claim.comment_id("https://github.com/o/r/issues/comments/12"), "12")

    def test_comment_id_is_none_without_a_match(self):
        self.assertIsNone(claim.comment_id(""))
        self.assertIsNone(claim.comment_id(None))

    def test_repo_name_reads_owner_and_repo(self):
        self.assertEqual(claim.repo_name({"url": "https://github.com/o/r/issues/9"}), "o/r")

    def test_repo_name_is_none_without_a_match(self):
        self.assertIsNone(claim.repo_name({}))


class TakenMessageTests(unittest.TestCase):
    def owner(self, **kwargs):
        base = dict(kind=claim.CLAIMED, session=OTHER, branch="feat/x",
                    stamp="2026-11-10 12:03", labels=(), url="https://example/other",
                    created="2026-11-10T03:00:00Z")
        base.update(kwargs)
        return claim.Record(**base)

    def message(self, owner=None, **gh_kwargs):
        gh = FakeGh(ticket(), **gh_kwargs)
        return claim.taken_message(932, owner or self.owner(), gh.runner.run, NOW)

    def test_the_whole_message_is_pinned(self):
        owner = self.owner()
        self.assertEqual(self.message(owner), "\n".join([
            f"#932 已被 session `{OTHER}` 认领（{claim.local_stamp(owner.created)}，0 天前）",
            "  branch `feat/x`",
            "  该分支没有开着的 PR",
            "  认领记录：https://example/other",
            "  停下上报，不要另开 worktree 重做这张票。",
        ]))

    def test_the_pr_lookup_uses_the_owner_branch(self):
        gh = FakeGh(ticket())
        claim.taken_message(932, self.owner(), gh.runner.run, NOW)
        prs = [call.args for call in gh.runner.run_calls if call.args[:2] == ("pr", "list")]
        self.assertEqual(prs, [("pr", "list", "--head", "feat/x", "--state", "open", "--json", "number")])

    def test_an_open_pr_is_mentioned(self):
        self.assertEqual(self.message(prs=[{"number": 5}]).splitlines()[2], "  该分支有开着的 PR")

    def test_an_unknown_pr_state_is_named(self):
        self.assertEqual(self.message(pr_rc=1).splitlines()[2], "  该分支的 PR 状态未知")

    def test_an_unreadable_creation_time_falls_back_to_the_written_stamp(self):
        self.assertEqual(self.message(self.owner(created="garbage")).splitlines()[0],
                         f"#932 已被 session `{OTHER}` 认领（2026-11-10 12:03，时间未知）")

    def test_a_missing_record_url_says_none(self):
        self.assertEqual(self.message(self.owner(url="")).splitlines()[3], "  认领记录：无链接")


class TimeTests(unittest.TestCase):
    def test_instant_reads_z_as_utc(self):
        self.assertEqual(claim.instant("2026-11-10T04:30:00Z"),
                         datetime(2026, 11, 10, 4, 30, tzinfo=timezone.utc))

    def test_instant_keeps_an_explicit_offset(self):
        self.assertEqual(claim.instant("2026-11-10T12:30:00+08:00").utcoffset(),
                         timedelta(hours=8))

    def test_instant_reads_a_naive_stamp_as_utc(self):
        self.assertEqual(claim.instant("2026-11-10 12:30:00").tzinfo, timezone.utc)

    def test_instant_garbage_is_none(self):
        self.assertIsNone(claim.instant("not a time"))

    def test_local_stamp_of_none_is_none(self):
        self.assertIsNone(claim.local_stamp("not a time"))

    def test_a_future_creation_counts_as_zero_days(self):
        created = (NOW.replace(tzinfo=timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(claim.age_days(created, NOW), 0)

    def test_age_days_of_garbage_is_none(self):
        self.assertIsNone(claim.age_days("not a time", NOW))


class PinnedContractTests(unittest.TestCase):
    """守卫：命令名与退出码是文档与实现之间的契约，改一处就会红。"""

    def test_the_command_and_its_exit_codes_are_pinned(self):
        self.assertEqual(
            (claim.EXIT_OK, claim.EXIT_REFUSED, claim.EXIT_TAKEN, claim.EXIT_GH), (0, 1, 2, 3))
        self.assertEqual(claim.COMMAND, "python3 devtools/claim.py")

    def test_the_command_is_documented_in_claude_md(self):
        """拆开读根级文件的那半：变异副本里没有 `CLAUDE.md`，这一条按方法摘进 `UNUSABLE`（#1520）。"""
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn(claim.COMMAND, text)


if __name__ == "__main__":
    unittest.main()
