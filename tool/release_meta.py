"""发版元数据从 Release 事实生成（#1135，沿用 #1134 的取数底座与清单）。

用法：

    python3 tool/release_meta.py sums v0.4.4               # 在当刻目录写 SHA256SUMS.txt
    python3 tool/release_meta.py sums v0.4.4 --upload      # 再传进 Release 草稿并回读核对
    python3 tool/release_meta.py sums v0.4.4 --from-files <安装包所在目录>
    python3 tool/release_meta.py page v0.4.4               # 只校验能不能回填（不写盘）
    python3 tool/release_meta.py page v0.4.4 --write       # 回填 index.html 的 REL

清单条目是 `<sha256>  <文件名>`（两个空格），顺序与下载卡片的 id 顺序一致，不含清单文件自身。
摘要取自 Release 的资产；缺摘要、或某个卡片 id 匹配不到附件时整份拒绝，不留下半份文件。
`--from-files` 按资产名去目录里找文件重算摘要，用于摘要缺失或想复核。
`--upload` 只在 Release 还是草稿时允许：公开之后换文件，用户手里的校验值就对不上了。

`page --write` 只动数据字段：版本号、下载前缀里的版本段、五条卡片的文件名 / 大小 / sha、
发布日期；卡片的 `folder` / `title` / `sub` / `note` 逐字不动。先校验再用——卡片 id 对不上、
资产缺失、页面读不全时整份不写；写盘走临时文件，回读自检一致才替换。`REL.gitee` 默认不动
（Gitee 上传晚于页面更新），要一起回填时加 `--gitee`。

退出码：0 写出（上传则含回读一致）；1 拒绝生成 / 拒绝上传 / 拒绝回填；2 取数失败（网络、
API 限额、tag 不存在、参数不认识）。
"""
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))   # 直接跑脚本与作为 tool.<模块> import 两种都认
from release_assets import (BLOCK, Entry, fetch_release, human_size, map_entries,  # noqa: E402
                            read_entries, run_gh)
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
PAGE = Path(__file__).resolve().parents[1] / "index.html"
USAGE = ("用法：python3 tool/release_meta.py sums <tag> [--upload] [--from-files <目录>]\n"
         "      python3 tool/release_meta.py page <tag> [--write] [--gitee]")

EXIT_OK, EXIT_REFUSED, EXIT_UNREACHABLE = 0, 1, 2

SHA256 = re.compile(r"^[0-9a-f]{64}$")

# 回填只替换值，键与缩进原样留着：卡片上的文案字段不该因为回填而变。
VERSION_LINE = re.compile(r'(\bversion:\s*")([^"]*)(")')
GITHUB_LINE = re.compile(r'(\bgithub:\s*")([^"]*)(")')
GITEE_LINE = re.compile(r'(\bgitee:\s*")([^"]*)(")')
FILE_LINE = re.compile(r'(\bfile:\s*")([^"]*)(")')
SIZE_LINE = re.compile(r'(\bsize:\s*")([^"]*)(")')
SHA_LINE = re.compile(r'(\bsha:\s*")([^"]*)(")')
RELEASED_LINE = re.compile(r'(const RELEASED = ")([^"]*)(")')


class Refused(Exception):
    """事实不完整或状态不允许：拒绝生成 / 拒绝上传，手里这份结果就不出手。"""


def select(assets, what="生成"):
    """按下载卡片的顺序取出五条附件；某个 id 没有唯一匹配时整份拒绝。"""
    chosen = []
    for entry_id, suffix in SUFFIXES:
        matches = [asset for asset in assets if asset.name.endswith(suffix)]
        if not matches:
            raise Refused(f"{entry_id} 在 Release 里找不到附件（文件名应以 {suffix} 结尾）：拒绝{what}。")
        if len(matches) > 1:
            raise Refused(f"{entry_id} 匹配到多个附件（{'、'.join(a.name for a in matches)}）：拒绝{what}。")
        chosen.append(matches[0])
    return chosen


def digest_of(asset, hint):
    digest = asset.digest.removeprefix("sha256:")
    if not SHA256.match(digest):
        raise Refused(f"{asset.name} 没有 sha256 摘要：{hint}")
    return digest


def plan_sums(assets):
    """清单文本：一行一条 `<sha256>  <文件名>`，末尾带换行。"""
    lines = []
    for asset in select(assets):
        digest = digest_of(asset, "改用 --from-files <目录> 从本地文件重算。")
        lines.append(f"{digest}  {asset.name}")
    return "\n".join(lines) + "\n"


def page_entries(assets, version):
    """五张卡片的预期字段，顺序与 `SUFFIXES` 一致；摘要缺失或版本段不符时整份拒绝。

    文件名第二段就是版本（`AndroidAdCleaner-<版本>-<平台>.<后缀>`）：tag 与资产对不上时
    写进页面会让版本一致性守卫红，所以在这里先挡住。
    """
    entries = []
    for (entry_id, _), asset in zip(SUFFIXES, select(assets, what="回填"), strict=True):
        if asset.name.split("-")[1:2] != [version]:
            raise Refused(f"{asset.name} 的文件名里没有版本 {version}：tag 与资产对不上，拒绝回填。")
        entries.append(Entry(entry_id, asset.name, human_size(asset.size), digest_of(
            asset, "Release 没给出这份附件的摘要，页面先不写。")))
    return entries


def retag(url, version, what="下载前缀"):
    """把下载前缀里的版本段换成 `v<version>`；前缀不是这个形状时拒绝，不猜。"""
    if not url:
        raise Refused(f"{what} 是空的：先填上再回填，或这次别动它。")
    head, sep, rest = url.rpartition("/download/")
    if not sep or not re.fullmatch(r"v[^/]+/", rest):
        raise Refused(f"{what} {url} 不是 /download/v<版本>/ 的形状：结构变了，拒绝回填。")
    return f"{head}{sep}v{version}/"


def replace_once(pattern, text, fn, what):
    """只替换第一处；一处都读不到就拒绝——页面结构变了，余下的替换没有意义。"""
    new, count = pattern.subn(lambda m: m.group(1) + fn(m.group(2)) + m.group(3), text, count=1)
    if count != 1:
        raise Refused(f"{what} 在页面里读不到：结构变了，拒绝回填。")
    return new


def sub_value(pattern, text, value):
    return pattern.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)


def fill_entry(chunk, entry):
    """在一张卡片的原文里替换 file / size / sha；同一个字段出现两次也拒绝。"""
    for pattern, value, field in ((FILE_LINE, entry.file, "file"),
                                  (SIZE_LINE, entry.size, "size"),
                                  (SHA_LINE, entry.sha, "sha")):
        if len(pattern.findall(chunk)) != 1:
            raise Refused(f"{entry.id} 这张卡片里 {field} 不是一个：页面读不出完整条目，拒绝回填。")
        chunk = sub_value(pattern, chunk, value)
    return chunk


def plan_page(text, assets, version, released, gitee=False):
    """回填后的页面文本：只动数据字段与发布日期，卡片的文案与结构逐字留给页面。"""
    match = BLOCK.search(text)
    if not match:
        raise Refused("页面里读不到 REL 块：结构变了，拒绝回填。")
    _, entries = read_entries(text)
    wanted = {entry.id: entry for entry in page_entries(assets, version)}
    page_ids = [entry.id for entry in entries]
    if len(page_ids) != len(set(page_ids)) or set(page_ids) != set(wanted):
        raise Refused(f"页面卡片的 id（{'、'.join(page_ids)}）与五个附件（{'、'.join(wanted)}）"
                      "对不上：拒绝回填。")
    incomplete = [entry.id for entry in entries if not (entry.file and entry.size and entry.sha)]
    if incomplete:
        raise Refused(f"页面里这些卡片读不出完整条目（{'、'.join(incomplete)}）：拒绝回填。")

    head, sep, tail = match.group(1).partition("files:")
    if not sep:
        raise Refused("页面里 REL 没有 files 段：结构变了，拒绝回填。")
    head = replace_once(VERSION_LINE, head, lambda _: version, "REL.version")
    head = replace_once(GITHUB_LINE, head, lambda url: retag(url, version, "REL.github"), "REL.github")
    if gitee:
        head = replace_once(GITEE_LINE, head, lambda url: retag(url, version, "REL.gitee"), "REL.gitee")
    tail = map_entries("files:" + tail, lambda entry_id, chunk: fill_entry(chunk, wanted[entry_id]))
    new_text = text[:match.start(1)] + head + tail + text[match.end(1):]
    return replace_once(RELEASED_LINE, new_text, lambda _: released, "RELEASED")


def page_ok(text, version, entries, released):
    """写后回读：版本、五条的 file / size / sha、发布日期都与预期逐字一致（按 id 比，不按顺序）。"""
    got_version, got_entries = read_entries(text)
    if got_version != version or len(got_entries) != len(entries):
        return False
    got = {entry.id: (entry.file, entry.size, entry.sha) for entry in got_entries}
    want = {entry.id: (entry.file, entry.size, entry.sha) for entry in entries}
    found = RELEASED_LINE.search(text)
    return got == want and found is not None and found.group(2) == released


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


def write_checked(path, text, check):
    """临时文件 → 读回已落盘的原文自检 → 原子替换；自检不过就删掉临时文件，页面保持原样。"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        if not check(tmp.read_text(encoding="utf-8")):
            raise Refused(f"{path} 写后回读与预期不一致：不落盘，页面保持原样。")
        os.replace(tmp, path)
    except (OSError, Refused):
        tmp.unlink(missing_ok=True)
        raise


def release_is_draft(tag):
    """`gh release view <tag>` 的 isDraft；取不到时抛 RuntimeError。"""
    return run_gh("release", "view", tag, "--json", "isDraft", "--jq", ".isDraft").strip() == "true"


def release_published(tag):
    """Release 发布时间的 UTC 日期（`YYYY-MM-DD`）；还没发布时拒绝回填。"""
    raw = run_gh("release", "view", tag, "--json", "publishedAt", "--jq", ".publishedAt").strip()
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise Refused(f"{tag} 还没发布（publishedAt 是空的）：页面先不写。") from None
    if moment.tzinfo is None:          # 没有时区的读数按 UTC 认，不拿本机时区去猜
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).date().isoformat()


def upload_asset(tag, path):
    """把清单传进 Release；草稿阶段允许覆盖，即公开状态由调用方先拦下。"""
    run_gh("release", "upload", tag, str(path), "--clobber")


def readback_matches(assets, path):
    local = file_digest(path)
    return any(asset.name == MANIFEST and asset.digest.removeprefix("sha256:") == local
               for asset in assets)


class Options(NamedTuple):
    command: str
    tag: str
    from_dir: str | None = None
    upload: bool = False
    write: bool = False
    gitee: bool = False


def parse(argv):
    if not argv:
        raise ValueError("缺子命令，只认 sums / page")
    command, rest = argv[0], list(argv[1:])
    allowed = {"sums": {"--upload", "--from-files"}, "page": {"--write", "--gitee"}}.get(command)
    if allowed is None:
        raise ValueError(f"不认识的子命令：{command}")
    tag, from_dir, flags = "", None, set()
    while rest:
        item = rest.pop(0)
        if item == "--from-files":
            if command != "sums":
                raise ValueError("--from-files 只给 sums 用")
            if not rest:
                raise ValueError("--from-files 后面要跟目录")
            from_dir = rest.pop(0)
        elif item.startswith("-"):
            if item not in allowed:
                raise ValueError(f"{command} 不认识的参数：{item}")
            flags.add(item)
        elif tag:
            raise ValueError(f"多余的参数：{item}")
        else:
            tag = item
    if not tag:
        raise ValueError("缺 tag")
    return Options(command, tag, from_dir, "--upload" in flags, "--write" in flags,
                   "--gitee" in flags)


def run_sums(opts, fetch, upload, draft, out):
    tag = opts.tag
    path = Path(out) if out else Path.cwd() / MANIFEST
    try:
        assets = fetch(tag)
        if opts.from_dir is not None:
            assets = from_files(assets, opts.from_dir)
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
    if not opts.upload:
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


def run_page(opts, fetch, published, page, verify):
    tag, path = opts.tag, Path(page)
    version = tag.removeprefix("v")
    try:
        page_text = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"读不到 {path}：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    try:
        assets = fetch(tag)
        entries = page_entries(assets, version)
        released = published(tag)
        new_text = plan_page(page_text, assets, version, released, gitee=opts.gitee)
    except Refused as error:
        print(error, file=sys.stderr)
        return EXIT_REFUSED
    except RuntimeError as error:
        print(f"取不到 {tag} 的发布信息：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if not opts.write:
        print(f"{tag} 的五个附件能回填进 {path.name}；加 --write 就写盘。")
        return EXIT_OK
    try:
        write_checked(path, new_text, lambda read: verify(read, version, entries, released))
    except Refused as error:
        print(error, file=sys.stderr)
        return EXIT_REFUSED
    except OSError as error:
        print(f"写不进 {path}：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    print(f"{path.name} 已回填到 {tag}：五个文件名、大小、sha 与发布日期 {released}。")
    if not opts.gitee:
        print("REL.gitee 没动（Gitee 上传晚于页面更新）；发完国内下载再跑一次并加 --gitee。")
    return EXIT_OK


def main(argv, fetch=fetch_release, upload=upload_asset, draft=release_is_draft,
         published=release_published, page=PAGE, verify=page_ok, out=None):
    try:
        opts = parse(argv)
    except ValueError as error:
        print(f"{error}\n{USAGE}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if opts.command == "page":
        return run_page(opts, fetch=fetch, published=published, page=page, verify=verify)
    return run_sums(opts, fetch=fetch, upload=upload, draft=draft, out=out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
