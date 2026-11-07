#!/usr/bin/env python3
"""把已发布的安装包传到 Gitee 发行版，国内下载走这里，不用登录。

  python3 gui/upload_gitee.py <版本>

从公开的 GitHub Release 下载安装包，核对 SHA256，把代码和标签推到 Gitee，建发行版并上传附件，
再匿名下载回来核对一遍。重跑是安全的：已有的同名同大小附件不重传。

Windows 安装版不传：Gitee 拒收（malicious file detected and rejected）。它没有代码签名，这可能是原因，也可能是误判。
不要改名或打包成 zip 绕过平台的检测；下载页上这个文件标了 gitee: false，只给 GitHub 按钮。

令牌在 ~/.config/gitee/token，不进仓库和对话。Gitee 不可用时的退路：把 index.html 的 REL.gitee 留空，
再跑 gui/upload_baidu.sh，下载页就回到百度网盘。
"""
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

GH_REPO = os.environ.get("GH_REPO", "rddmwmddr/android-ad-cleaner")
GITEE_REPO = os.environ.get("GITEE_REPO", "rddmw/android-ad-cleaner")
API = f"https://gitee.com/api/v5/repos/{GITEE_REPO}"
TOKEN_FILE = Path.home() / ".config" / "gitee" / "token"
ASSET_GLOB = os.environ.get("ASSET_GLOB", "AndroidAdCleaner-{ver}-*")
UA = "roudai-release"
NOT_ON_GITEE = ("-windows-setup.exe",)


def token():
    if not TOKEN_FILE.exists():
        sys.exit(f"没有 {TOKEN_FILE}。在 Gitee 生成私人令牌（projects 权限）后存到这里")
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def call(method, path, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    head = {"Authorization": f"token {token()}", "User-Agent": UA}
    if body is not None:
        head["Content-Type"] = "application/json"
    head.update(headers or {})
    req = urllib.request.Request(API + path, data=data, method=method, headers=head)
    with urllib.request.urlopen(req, timeout=600) as r:
        text = r.read().decode("utf-8", "replace")
    return json.loads(text) if text else None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(*cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def fetch_release(ver, stage):
    """从公开的 GitHub Release 下载，保证 Gitee 上的文件和公开发布的是同一份。"""
    run("gh", "release", "download", f"v{ver}", "-R", GH_REPO, "-D", str(stage),
        "-p", ASSET_GLOB.format(ver=ver), "-p", "SHA256SUMS.txt")
    sums = {}
    for line in (stage / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            sums[name.strip().lstrip("*")] = digest
    files = sorted(p for p in stage.iterdir() if p.name != "SHA256SUMS.txt")
    for p in files:
        if sums.get(p.name) != sha256(p):
            sys.exit(f"校验不一致：{p.name}")
    print(f"校验通过 {len(files)} 个文件")
    return files, sums


def push_code(ver):
    """只推 main 和版本标签，开发分支不推。令牌不写进 URL，也不留在 git 配置里。"""
    helper = f'!f(){{ echo username={GITEE_REPO.split("/")[0]}; echo "password=$(cat {TOKEN_FILE})"; }};f'
    with tempfile.TemporaryDirectory() as tmp:
        bare = Path(tmp) / "m.git"
        run("git", "clone", "-q", "--bare", "--single-branch", "--branch", "main",
            f"git@github.com:{GH_REPO}.git", str(bare))
        run("git", "-C", str(bare), "fetch", "-q", "origin", "refs/tags/v*:refs/tags/v*")
        run("git", "-C", str(bare), "rev-parse", "-q", "--verify", f"refs/tags/v{ver}", stdout=subprocess.DEVNULL)
        run("git", "-C", str(bare), "-c", "credential.helper=", "-c", f"credential.helper={helper}", "push", "-q",
            f"https://gitee.com/{GITEE_REPO}.git", "refs/heads/main:refs/heads/main", "refs/tags/v*:refs/tags/v*")
    print("代码和标签已推到 Gitee")


def release_for(ver, body):
    tag = f"v{ver}"
    try:
        found = call("GET", f"/releases/tags/{tag}")
        if found and found.get("id"):
            return found
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    return call("POST", "/releases", {"tag_name": tag, "name": tag, "body": body,
                                      "target_commitish": "main", "prerelease": False})


def attachments(rid):
    return {a["name"]: a for a in call("GET", f"/releases/{rid}/attach_files?per_page=100") or []}


def upload(rid, path):
    boundary = uuid.uuid4().hex
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {kind}\r\n\r\n").encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    t = time.time()
    try:
        call("POST", f"/releases/{rid}/attach_files", raw=head + path.read_bytes() + tail,
             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    except urllib.error.HTTPError as e:
        sys.exit(f"上传 {path.name} 被拒绝（HTTP {e.code}）：{e.read().decode('utf-8', 'replace')[:300]}")
    print(f"  传好 {path.name}（{path.stat().st_size // 1048576} MB，{time.time() - t:.0f} 秒）")


def verify_public(ver, files, sums, sums_digest):
    """不带令牌下载回来，确认用户拿到的和 GitHub 上的是同一份。校验清单本身也要对。"""
    want = {p.name: sums[p.name] for p in files}
    want["SHA256SUMS.txt"] = sums_digest
    for name, digest in want.items():
        url = f"https://gitee.com/{GITEE_REPO}/releases/download/v{ver}/{name}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        t = time.time()
        h = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(req, timeout=300) as r:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
        if h.hexdigest() != digest:
            sys.exit(f"匿名下载校验不一致：{name}")
        print(f"  匿名下载校验通过 {name}（{size / 1048576:.1f} MB，{size / 1048576 / (time.time() - t):.1f} MB/s）")


def for_gitee(files):
    return [p for p in files if not p.name.endswith(NOT_ON_GITEE)]


def main(argv):
    if len(argv) != 1:
        sys.exit(__doc__)
    ver = argv[0].lstrip("v")
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        files, sums = fetch_release(ver, stage)
        files = for_gitee(files)
        push_code(ver)
        note = (f"肉呆去广告 v{ver}。更新说明：https://github.com/{GH_REPO}/releases/tag/v{ver}\n\n"
                "安装包和 GitHub Release 是同一份，可以用 SHA256SUMS.txt 核对。"
                "Windows 安装版只在 GitHub Release 上，这里有免安装版。免安装版不替换、也不卸载已安装的旧版；"
                "要让新版顶掉旧版，用 GitHub 上的安装版覆盖安装，或先卸载旧的「安卓去广告」（0.3.2 及更早版本装的名字），卸载不动数据与备份。")
        rid = release_for(ver, note)["id"]
        have = attachments(rid)
        sums_file = stage / "SHA256SUMS.txt"
        for p in [*files, sums_file]:
            if p.name in have and int(have[p.name].get("size") or -1) == p.stat().st_size:
                print(f"  已有 {p.name}")
                continue
            upload(rid, p)
        verify_public(ver, files, sums, sha256(sums_file))
    print(f"完成：https://gitee.com/{GITEE_REPO}/releases/tag/v{ver}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
