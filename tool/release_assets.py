"""下载页的 REL 与 GitHub Release 附件对账（#1136，沿用 #1003）。

用法：

    python3 tool/release_assets.py          # 比 index.html 的 REL.version 那个 tag，只比文件名
    python3 tool/release_assets.py v0.4.0   # 比指定的 tag
    python3 tool/release_assets.py --sha    # 文件名、大小、sha 三类都比

`REL.files` 每条的 `id` 是下载卡片的身份，`file` 是 Release 里的附件名；两边任一侧改了名字
而另一侧没跟上，用户点下载就是 404。`--sha` 再加比大小与 sha：页面上写的是给人看的校验值，
一个字节不同就是同一版本发了两批内容，而 GitHub 同一 tag 的资产内容不可变（换文件要重发版），
所以 sha 不会自己漂，对不上就是页面与 Release 不是同一批字节。差异分名字 / 大小 / sha 三类
分行列出，两侧各自点名。静态那一半（`id` 冻结、`file` 里的版本号等于 `REL.version`）在
`tests/test_rules_guards.py` 的 `ReleaseGuards` 里，不需要 GitHub 凭据。

`fetch_release()` 是取数底座：一次 `gh release view` 给全部附件的 `Asset`（名字、大小、
摘要），`fetch_assets()` 只是它的名字投影；生成校验清单与回填页面的 `tool/release_meta.py`
也消费它。

`read_entries()` 给页面条目的完整字段（版本、id、文件名、大小、sha），`read_page()` 是它的
`(id, file)` 投影；`human_size()` 是页面上的大小写法（十进制 MB、一位小数、四舍五入），
回填页面与这里的大小比对共用这一份，两边各写一份会漂。

退出码：0 一致；1 对不上（名字 / 大小 / sha 任一）；2 没法比完（读不到 REL、网络、API 限额、
tag 不存在、Release 没给出摘要、参数不认识）。同一轮既有对不上又有附件缺摘要时按 1 报：
差异已经确证，缺摘要那几句照样打在差异后面。
"""
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))   # 直接跑脚本与作为 tool.<模块> import 两种都认
from gh import GhError, json_of, runner_for                # noqa: E402
from stdio import use_utf8_console                         # noqa: E402

use_utf8_console()

PAGE = Path(__file__).resolve().parents[1] / "index.html"

# 只认 `const REL = {` 到顶格 `};` 这一段：页面别处也有 `id` / `file` 字样（DOM 与文案）。
BLOCK = re.compile(r"const REL = \{(.*?)\n\};", re.S)
VERSION = re.compile(r'\bversion:\s*"([^"]+)"')
ENTRY_ID = re.compile(r'\bid:\s*"([^"]+)"')
ENTRY_FILE = re.compile(r'\bfile:\s*"([^"]+)"')
ENTRY_SIZE = re.compile(r'\bsize:\s*"([^"]+)"')
ENTRY_SHA = re.compile(r'\bsha:\s*"([^"]+)"')

# Release 里不属于下载卡片的附件：校验清单随版本走，页面上没有它的入口。
EXTRA_ASSETS = frozenset({"SHA256SUMS.txt"})

USAGE = ("用法：python3 tool/release_assets.py [tag] [--sha]\n"
         "  不带 --sha 只比文件名；带 --sha 再比大小与 sha。留空 tag 取页面 REL.version。")

EXIT_OK, EXIT_MISMATCH, EXIT_UNREACHABLE = 0, 1, 2


class Entry(NamedTuple):
    """下载卡片上的一行：`id` 是卡片身份，其余是随版本变的三个数据字段。"""
    id: str
    file: str
    size: str
    sha: str


def map_entries(block, fn):
    """把 REL 块里每张卡片的原文交给 `fn(id, 原文)`，按原位置拼回。

    卡片的边界是 `id:`：条目里有嵌套的 `baidu: { ... }`，按括号切会切错。原文从 `id:`
    之后到下一张卡片之前，位置与顺序都取自页面，回填只动 `fn` 返回的那一段。
    """
    hits = list(ENTRY_ID.finditer(block))
    pieces, cursor = [], 0
    for index, hit in enumerate(hits):
        end = hits[index + 1].start() if index + 1 < len(hits) else len(block)
        pieces.append(block[cursor:hit.end()])
        pieces.append(fn(hit.group(1), block[hit.end():end]))
        cursor = end
    pieces.append(block[cursor:])
    return "".join(pieces)


def _first(pattern, chunk):
    """取唯一一次出现的值；一次都没有、或出现不止一次（卡片结构错位）都当读不出。"""
    found = pattern.findall(chunk)
    return found[0] if len(found) == 1 else ""


def read_entries(text):
    """从 index.html 的源码里读出 (REL.version, [Entry])；读不出返回 (None, [])。

    缺某个字段的卡片留空串，整页缺到没有条目时按「读不出」处理：调用方自己判完整性，
    回填页面时缺一条就不写。
    """
    match = BLOCK.search(text)
    if not match:
        return None, []
    block = match.group(1)
    found = VERSION.search(block)
    entries = []

    def collect(entry_id, chunk):
        entries.append(Entry(entry_id, _first(ENTRY_FILE, chunk), _first(ENTRY_SIZE, chunk),
                             _first(ENTRY_SHA, chunk)))
        return chunk

    map_entries(block, collect)
    if not found or not entries:
        return None, []
    return found.group(1), entries


def readable(version, entries):
    """页面能不能拿来比对：版本读得到、且每张卡片都有文件名。

    配对关系是这个模块唯一要保证的东西：给不出配对比给出一份空清单更安全。
    """
    return version is not None and all(entry.file for entry in entries)


def read_page(text):
    """`read_entries` 的 (id, file) 投影；读不全时返回 (None, [])。"""
    version, entries = read_entries(text)
    if not readable(version, entries):
        return None, []
    return version, [(entry.id, entry.file) for entry in entries]


def human_size(size):
    """页面上的大小写法：十进制 MB、一位小数、四舍五入（历史页面用的就是这个口径）。"""
    megabytes = Decimal(int(size)) / Decimal(1_000_000)
    return f"{megabytes.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} MB"


def compare(page_files, release_files):
    """两侧附件名的差集：(页面有 Release 没有, Release 有页面没有)，各自有序。"""
    page = set(page_files)
    release = set(release_files) - EXTRA_ASSETS
    return sorted(page - release), sorted(release - page)


# 页面卡片读不出某个字段时的占位：差异行里要看出是「页面没写」，不是「值长得像这个」。
EMPTY = "（空）"


class Diff(NamedTuple):
    """一次对账的差异：只在一侧的名字各一列，大小与 sha 每行是 (文件名, 页面, Release)。

    `unverified` 是 Release 侧没给摘要的附件——sha 没法比，既不算一致也不算对不上。
    """
    only_page: list[str]
    only_release: list[str]
    size: list[tuple[str, str, str]]
    sha: list[tuple[str, str, str]]
    unverified: list[str]


def compare_meta(entries, assets):
    """按文件名把页面条目与 Release 附件配上，再比大小与 sha；配不上的名字单列。

    大小按页面口径（`human_size`）比：页面写的是给人看的数，回填与比对必须是同一份格式化。
    """
    only_page, only_release = compare([entry.file for entry in entries],
                                      [asset.name for asset in assets])
    page = {entry.file: entry for entry in entries}
    release = {asset.name: asset for asset in assets if asset.name not in EXTRA_ASSETS}
    size, sha, unverified = [], [], []
    for name in sorted(set(page) & set(release)):
        entry, asset = page[name], release[name]
        want_size = human_size(asset.size)
        if entry.size != want_size:
            size.append((name, entry.size or EMPTY, want_size))
        digest = asset.digest.removeprefix("sha256:")
        if not digest:
            unverified.append(name)
        elif entry.sha != digest:
            sha.append((name, entry.sha or EMPTY, digest))
    return Diff(only_page, only_release, size, sha, unverified)


class Asset(NamedTuple):
    """Release 上的一个附件：`digest` 是 `gh` 原文，形如 `sha256:<64 位十六进制>`。"""
    name: str
    size: int
    digest: str


def fetch_release(tag, runner=None):
    """`gh release view <tag>` 的全量附件；取不到时抛 GhError。"""
    try:
        rows = json_of(runner or runner_for(), "release", "view", tag, "--json", "assets",
                       source=f"`gh release view {tag}`")["assets"]
        return [Asset(name=str(row.get("name") or ""), size=int(row.get("size") or 0),
                      digest=str(row.get("digest") or "")) for row in rows]
    except (AttributeError, ValueError, KeyError, TypeError) as error:
        raise GhError(f"读不出 {tag} 的附件：{error}") from error


def fetch_assets(tag, runner=None):
    """`fetch_release` 的名字投影：附件名清单；取不到时抛 GhError。"""
    return [asset.name for asset in fetch_release(tag, runner)]


def parse(argv):
    """`[tag] [--sha]`，顺序随意；不认识的参数与多余的位置参数当场拒绝，不猜。"""
    tag, with_sha = "", False
    for item in argv:
        if item == "--sha":
            with_sha = True
        elif item.startswith("-"):
            raise ValueError(f"不认识的参数：{item}")
        elif tag:
            raise ValueError(f"多余的参数：{item}")
        else:
            tag = item.strip()
    return tag, with_sha


def print_names(diff):
    if diff.only_page:
        print("  页面有、Release 没有：" + "、".join(diff.only_page), file=sys.stderr)
    if diff.only_release:
        print("  Release 有、页面没有：" + "、".join(diff.only_release), file=sys.stderr)


def print_fields(diff):
    if diff.size:
        print("  大小对不上：", file=sys.stderr)
        for name, page_value, release_value in diff.size:
            print(f"    {name}：页面 {page_value} / Release {release_value}", file=sys.stderr)
    if diff.sha:
        print("  sha 对不上：", file=sys.stderr)
        for name, page_value, release_value in diff.sha:
            print(f"    {name}：页面 {page_value} / Release {release_value}", file=sys.stderr)


def main(argv, fetch=fetch_release, page=PAGE):
    try:
        wanted, with_sha = parse(argv)
    except ValueError as error:
        print(f"{error}\n{USAGE}", file=sys.stderr)
        return EXIT_UNREACHABLE
    name = Path(page).name
    version, entries = read_entries(Path(page).read_text(encoding="utf-8"))
    if not readable(version, entries):
        print(f"{page} 里读不到 REL 的 version 与 files：页面结构变了，这条检查没法比对。",
              file=sys.stderr)
        return EXIT_UNREACHABLE
    tag = wanted or f"v{version}"
    try:
        release = fetch(tag)
    except RuntimeError as error:
        print(f"取不到 {tag} 的附件，没法比对：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    if with_sha:
        diff = compare_meta(entries, release)
    else:
        only_page, only_release = compare([entry.file for entry in entries],
                                          [asset.name for asset in release])
        diff = Diff(only_page, only_release, [], [], [])
    differs = bool(diff.only_page or diff.only_release or diff.size or diff.sha)
    if differs:
        print(f"{tag} 与 {name} 的 REL 对不上：", file=sys.stderr)
        print_names(diff)
        print_fields(diff)
    if diff.unverified:
        print("  Release 没给出这些附件的摘要，sha 比不了：" + "、".join(diff.unverified),
              file=sys.stderr)
    if differs:
        return EXIT_MISMATCH          # 差异已经确证：缺摘要不把它降级成「取不到数」
    if diff.unverified:
        return EXIT_UNREACHABLE       # 只有比不了的那部分：既不能报一致，也不栽赃成对不上
    what = "REL.files 的名字、大小、sha" if with_sha else "REL.files"
    print(f"{tag} 的 {len(entries)} 个附件与 {what} 一致。")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
