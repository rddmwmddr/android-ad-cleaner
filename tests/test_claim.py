"""开工认领（tool/claim.py）：一条命令写认领评论 + 摘待办标签，仲裁只看票下的评论（#932）。"""
import copy
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import claim  # noqa: E402
import fixtures  # noqa: E402

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

    def __init__(self, issue=None, prs=(), comment_rc=0, edit_rc=0):
        self.issue = issue
        self.overlay = None
        self.prs = list(prs)
        self.comment_rc, self.edit_rc = comment_rc, edit_rc
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
            return json.dumps(self.prs), "", 0
        if args[:3] == ("api", "--method", "DELETE"):
            return self._delete(args[3])
        raise AssertionError(f"没预料到的 gh 调用：{args}")

    def _view(self):
        if self.issue is None:
            return "", "no issues found", 1
        self.views += 1
        payload = copy.deepcopy(self.issue)
        if self.overlay is not None and self.views > 1:
            payload["comments"] += copy.deepcopy(self.overlay)
        return json.dumps(payload), "", 0

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
        self.assertEqual(code, 0)
        self.assertIn("已认领", message)
        self.assertEqual(len(gh.comments), 1, "空票上要留一条认领评论")
        self.assertIn("**认领中**", gh.comments[0])
        self.assertIn(f"session `{ME}`", gh.comments[0])
        self.assertNotIn(HOST, gh.comments[0], "评论里不该出现主机名（#970）")
        self.assertNotIn(WORKTREE, gh.comments[0], "评论里不该出现 worktree 绝对路径（#970）")
        self.assertIn(f"{claim.LABEL_KEY}`ready-for-agent`", gh.comments[0])
        self.assertEqual(gh.edits, [["issue", "edit", "932",
                                     "--add-label", "in-progress",
                                     "--remove-label", "ready-for-agent"]])

    def test_claiming_again_from_the_same_session_adds_no_comment(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, message = self.go(gh)
        self.assertEqual(code, 0)
        self.assertIn("已由本会话持有", message)
        self.assertEqual(gh.comments, [], "同一 session 重复认领是幂等的 reaffirm")
        self.assertEqual(gh.edits, [["issue", "edit", "932", "--add-label", "in-progress"]])

    def test_an_earlier_open_claim_by_another_session_wins(self):
        gh = FakeGh(ticket([claim_comment(OTHER, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, message = self.go(gh)
        self.assertEqual(code, 2)
        self.assertIn(OTHER, message)
        self.assertIn("feat/x", message)
        self.assertIn("天前", message)
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
        self.assertEqual(code, 0)
        self.assertIn("已收尾", message)
        self.assertEqual(len(gh.comments), 1)
        self.assertIn(f"**{claim.RELEASED}**", gh.comments[0])
        self.assertEqual(gh.edits, [["issue", "edit", "932", "--remove-label", "in-progress"]])

    def test_abandon_restores_the_labels_recorded_at_claim_time(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                           labels=("in-progress",)))
        code, message = self.go(gh, action="abandon")
        self.assertEqual(code, 0)
        self.assertIn("ready-for-agent", message)
        self.assertEqual(gh.edits, [["issue", "edit", "932",
                                     "--add-label", "ready-for-agent",
                                     "--remove-label", "in-progress"]])

    def test_abandon_restore_flag_overrides_the_recorded_labels(self):
        gh = FakeGh(ticket([claim_comment(ME, created="2026-11-10T03:00:00Z")],
                            labels=("in-progress",)))
        code, _ = self.go(gh, action="abandon", restore=["ready-for-human"])
        self.assertEqual(code, 0)
        self.assertEqual(gh.edits, [["issue", "edit", "932",
                                     "--add-label", "ready-for-human",
                                     "--remove-label", "in-progress"]])

    def test_release_without_a_claim_from_this_session_is_refused(self):
        gh = FakeGh(ticket([], labels=("in-progress",)))
        code, message = self.go(gh, action="release")
        self.assertEqual(code, 1)
        self.assertIn("没有本会话", message)
        self.assertEqual(gh.comments + gh.edits, [])

    def test_unknown_ticket_is_a_gh_failure(self):
        gh = FakeGh(None)
        code, message = self.go(gh)
        self.assertEqual(code, 3)
        self.assertIn("读不到", message)
        self.assertEqual(gh.comments + gh.edits, [])

    def test_closed_ticket_is_refused(self):
        gh = FakeGh(ticket(state="CLOSED"))
        code, message = self.go(gh)
        self.assertEqual(code, 1)
        self.assertIn("CLOSED", message)
        self.assertEqual(gh.comments + gh.edits, [])

    def test_an_unreadable_claim_comment_stops_instead_of_guessing(self):
        broken = {"body": "**认领中**：我占了", "createdAt": "2026-11-10T03:00:00Z",
                  "url": "https://example/broken", "author": {"login": "someone"}}
        gh = FakeGh(ticket([broken]))
        code, message = self.go(gh)
        self.assertEqual(code, 1)
        self.assertIn("读不出确定结局", message)
        self.assertEqual(gh.comments + gh.edits, [])

    def test_a_failed_comment_leaves_the_labels_alone(self):
        gh = FakeGh(ticket(), comment_rc=1)
        code, message = self.go(gh)
        self.assertEqual(code, 3)
        self.assertIn("写认领评论失败", message)
        self.assertEqual(gh.edits, [])

    def test_a_failed_label_write_is_advisory(self):
        gh = FakeGh(ticket(), edit_rc=1)
        code, message = self.go(gh)
        self.assertEqual(code, 0, "认领记录以评论为准，标签只是可见信号")
        self.assertIn("标签没写成功", message)

    def test_two_concurrent_claims_from_one_session_keep_the_earlier_comment(self):
        gh = FakeGh(ticket())
        gh.overlay = [claim_comment(ME, created="2026-11-10T04:29:00Z")]
        code, message = self.go(gh)
        self.assertEqual(code, 0, "同一会话不算争抢，认领仍然成立")
        self.assertEqual(len(gh.deletes), 1, "同一会话的两条认领记录，撤回晚的那条")
        self.assertIn("已认领", message)

    def test_a_comment_written_after_an_earlier_claim_is_withdrawn(self):
        gh = FakeGh(ticket())
        gh.overlay = [claim_comment(OTHER, created="2026-11-10T04:29:00Z")]
        code, message = self.go(gh)
        self.assertEqual(code, 2, "重读时发现别人更早，后写的那路要让出")
        self.assertEqual(len(gh.comments), 1, "自己那条写过")
        self.assertEqual(len(gh.deletes), 1, "响应地撤回它")
        self.assertIn("撤回", message)
        self.assertEqual(gh.edits, [], "让出时不摘待办标签")


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
        self.assertEqual((record.kind, record.session, record.branch),
                         (claim.CLAIMED, ME, "feat/claim-command-932"))
        self.assertEqual(record.labels, ("ready-for-agent",))

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
        body = "**认领中**：session `old` · host `box` · branch `feat/x` · 2026-11-10 12:03"
        with self.assertRaises(claim.Unreadable):
            claim.parse_comment({"body": body, "createdAt": POSTED, "url": COMMENT_URL})

    def test_an_ordinary_comment_is_not_a_claim(self):
        self.assertIsNone(claim.parse_comment({"body": "看起来不错", "createdAt": POSTED}))

    def test_claiming_on_an_empty_ticket_records_no_original_labels(self):
        body = claim.claim_body(WHO, NOW, ())
        record = claim.parse_comment({"body": body, "createdAt": POSTED})
        self.assertEqual(record.labels, ())

    def test_a_claim_comment_without_created_at_is_unreadable(self):
        body = claim.claim_body(WHO, NOW, ())
        with self.assertRaises(claim.Unreadable):
            claim.parse_comment({"body": body, "url": COMMENT_URL})


class PinnedContractTests(unittest.TestCase):
    """守卫：命令名与退出码是文档与实现之间的契约，改一处就会红。"""

    def test_the_command_and_its_exit_codes_are_pinned(self):
        self.assertEqual(
            (claim.EXIT_OK, claim.EXIT_REFUSED, claim.EXIT_TAKEN, claim.EXIT_GH), (0, 1, 2, 3))
        self.assertEqual(claim.COMMAND, "python3 tool/claim.py")
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn(claim.COMMAND, text)


if __name__ == "__main__":
    unittest.main()
