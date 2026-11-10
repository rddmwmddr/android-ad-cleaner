"""`base..head` 的提交读取：DCO 与 Conventional Commits 两条校验共用（#848、#849）。

只读 git、不做判定：每条记录原样交出，判什么由各自的校验脚本决定。
"""
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Commit:
    sha: str
    author_email: str
    subject: str
    body: str
    merge: bool


def git(*args):
    done = subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)} 失败：{done.stderr.strip()}")
    return done.stdout


def read_commits(rev_range):
    """按 `%x00` 分字段读提交：NUL 不可能出现在提交信息或邮箱里，正文换行不会切错。"""
    for sha in git("rev-list", rev_range).split():
        parents, email, subject, body = git(
            "log", "-1", "--format=%P%x00%ae%x00%s%x00%b", sha).split("\x00", 3)
        yield Commit(sha, email, subject, body, merge=len(parents.split()) > 1)
