"""发版校验清单从 Release 事实生成（#1134）。

用法：

    python3 tool/release_meta.py sums v0.4.4               # 在当刻目录写 SHA256SUMS.txt
    python3 tool/release_meta.py sums v0.4.4 --upload      # 再传进 Release 草稿并回读核对
    python3 tool/release_meta.py sums v0.4.4 --from-files <安装包所在目录>

条目是 `<sha256>  <文件名>`（两个空格），顺序与下载卡片的 id 顺序一致，不含清单文件自身。
摘要取自 Release 的资产；缺摘要、或某个卡片 id 匹配不到附件时整份拒绝，不留下半份文件。
`--from-files` 按资产名去目录里找文件重算摘要，用于摘要缺失或想复核。
`--upload` 只在 Release 还是草稿时允许：公开之后换文件，用户手里的校验值就对不上了。

退出码：0 写出（上传则含回读一致）；1 拒绝生成 / 拒绝上传；2 取数失败（网络、API 限额、
tag 不存在、参数不认识）。
"""
import hashlib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # 直接跑脚本与作为 tool.<模块> import 两种都认
from release_assets import fetch_release, run_gh           # noqa: E402
from stdio import use_utf8_console                         # noqa: E402

use_utf8_console()

# 下载卡片 id → 附件名后缀，顺序就是清单顺序（与 index.html 的 REL.files 一致，
# tests/test_release_meta.py 守着两边不漂）。win-setup 不在 updates.SUFFIXES 里：
# 应用内更新只认那四个目标，安装版不在其中。
SUFFIXES = (
    ("mac-arm64", "mac-arm64.dmg"),
    ("mac-intel", "mac-intel.dmg"),
    ("win-setup", "windows-setup.exe"),
    ("win-zip", "windows-portable.zip"),
    ("android", "android-arm64.apk"),
)

MANIFEST = "SHA256SUMS.txt"
USAGE = "用法：python3 tool/release_meta.py sums <tag> [--upload] [--from-files <目录>]"

EXIT_OK, EXIT_REFUSED, EXIT_UNREACHABLE = 0, 1, 2

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Refused(Exception):
    """事实不完整或状态不允许：拒绝生成 / 拒绝上传，手里这份结果就不出手。"""


def select(assets):
    """按下载卡片的顺序取出五条附件；某个 id 没有唯一匹配时整份拒绝。"""
    chosen = []
    for entry_id, suffix in SUFFIXES:
        matches = [asset for asset in assets if asset.name.endswith(suffix)]
        if not matches:
            raise Refused(f"{entry_id} 在 Release 里找不到附件（文件名应以 {suffix} 结尾）：拒绝生成。")
        if len(matches) > 1:
            raise Refused(f"{entry_id} 匹配到多个附件（{'、'.join(a.name for a in matches)}）：拒绝生成。")
        chosen.append(matches[0])
    return chosen


def plan_sums(assets):
    """清单文本：一行一条 `<sha256>  <文件名>`，末尾带换行。"""
    lines = []
    for asset in select(assets):
        digest = asset.digest.removeprefix("sha256:")
        if not SHA256.match(digest):
            raise Refused(f"{asset.name} 没有 sha256 摘要：改用 --from-files <目录> 从本地文件重算。")
        lines.append(f"{digest}  {asset.name}")
    return "\n".join(lines) + "\n"


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def from_files(assets, root):
    """按资产名去 root 里找文件重算摘要；缺一个即拒绝。"""
    root = Path(root)
    rebuilt = []
    for asset in select(assets):
        path = root / asset.name
        if not path.is_file():
            raise Refused(f"{root} 里没有 {asset.name}：拒绝生成。")
        rebuilt.append(asset._replace(digest="sha256:" + file_digest(path)))
    return rebuilt


def write_atomic(path, text):
    """先写同目录临时文件再替换：写到一半中断不留半份清单。"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def release_is_draft(tag):
    """`gh release view <tag>` 的 isDraft；取不到时抛 RuntimeError。"""
    return run_gh("release", "view", tag, "--json", "isDraft", "--jq", ".isDraft").strip() == "true"


def upload_asset(tag, path):
    """把清单传进 Release；草稿阶段允许覆盖，即公开状态由调用方先拦下。"""
    run_gh("release", "upload", tag, str(path), "--clobber")


def readback_matches(assets, path):
    local = file_digest(path)
    return any(asset.name == MANIFEST and asset.digest.removeprefix("sha256:") == local
               for asset in assets)


def parse(argv):
    if not argv or argv[0] != "sums":
        raise ValueError("缺子命令，只认 sums" if not argv else f"不认识的子命令：{argv[0]}")
    tag, from_dir, do_upload = "", None, False
    rest = list(argv[1:])
    while rest:
        item = rest.pop(0)
        if item == "--upload":
            do_upload = True
        elif item == "--from-files":
            if not rest:
                raise ValueError("--from-files 后面要跟目录")
            from_dir = rest.pop(0)
        elif item.startswith("-"):
            raise ValueError(f"不认识的参数：{item}")
        elif tag:
            raise ValueError(f"多余的参数：{item}")
        else:
            tag = item
    if not tag:
        raise ValueError("缺 tag")
    return tag, from_dir, do_upload


def main(argv, fetch=fetch_release, upload=upload_asset, draft=release_is_draft, out=None):
    try:
        tag, from_dir, do_upload = parse(argv)
    except ValueError as error:
        print(f"{error}\n{USAGE}", file=sys.stderr)
        return EXIT_UNREACHABLE
    path = Path(out) if out else Path.cwd() / MANIFEST
    try:
        assets = fetch(tag)
        if from_dir is not None:
            assets = from_files(assets, from_dir)
        text = plan_sums(assets)
    except Refused as error:
        print(error, file=sys.stderr)
        return EXIT_REFUSED
    except RuntimeError as error:
        print(f"取不到 {tag} 的附件：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    try:
        write_atomic(path, text)
    except OSError as error:
        print(f"写不进 {path}：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    print(f"{tag} 的 {len(SUFFIXES)} 个附件已写进 {path}")
    if not do_upload:
        return EXIT_OK
    try:
        is_draft = draft(tag)
    except RuntimeError as error:
        print(f"读不到 {tag} 的发布状态：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if not is_draft:
        print(f"{tag} 已公开，不再上传 {MANIFEST}：公开之后换文件，用户手里的校验值就对不上了。",
              file=sys.stderr)
        return EXIT_REFUSED
    try:
        upload(tag, path)
    except RuntimeError as error:
        print(f"上传 {MANIFEST} 失败：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    try:
        readback = fetch(tag)
    except RuntimeError as error:
        print(f"清单已上传，但回读 {tag} 失败：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if not readback_matches(readback, path):
        print(f"上传后回读 {tag}，{MANIFEST} 的摘要与本地文件不一致：上传没有生效。",
              file=sys.stderr)
        return EXIT_REFUSED
    print(f"已传进 {tag} 的草稿，回读摘要一致。")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
