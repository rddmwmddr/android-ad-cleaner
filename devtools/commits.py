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
    """按 `%x00` 分字段读提交：NUL 不可能出现在提交信息或邮箱里，正文换行不会切错。

    父提交从 `rev-list --parents` 取（每行 `sha 父…`），与元数据分开读：`%P` 的缩写变体只影响
    哈希长度、不影响父提交个数，混在 `--format` 里就是一条杀不掉的等价变异。
    """
    for line in git("rev-list", "--parents", rev_range).splitlines():
        sha, *parents = line.split()  # pragma: no mutate（语义等价：每行以空格分隔，split/rsplit 结果相同）
        record = git("log", "-1", "--format=%ae%x00%s%x00%b", sha)
        email, subject, body = record.split("\x00", 2)  # pragma: no mutate（语义等价：提交信息与邮箱里不可能有 NUL，恰 2 个分隔符时 split/rsplit 与 maxsplit≥2 结果相同）
        yield Commit(sha, email, subject, body, merge=len(parents) > 1)
