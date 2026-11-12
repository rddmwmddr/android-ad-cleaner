"""下载页的 REL 与 GitHub Release 附件对账（#1003）。

用法：

    python3 tool/release_assets.py          # 比 index.html 的 REL.version 那个 tag
    python3 tool/release_assets.py v0.4.0   # 比指定的 tag

`REL.files` 每条的 `id` 是下载卡片的身份，`file` 是 Release 里的附件名；两边任一侧改了名字
而另一侧没跟上，用户点下载就是 404。静态那一半（`id` 冻结、`file` 里的版本号等于
`REL.version`）在 `tests/test_rules_guards.py` 的 `ReleaseGuards` 里，不需要 GitHub 凭据；
这里只比名字集合，不比 sha——sha 每次发版都变，比对会天天误报。

`fetch_release()` 是取数底座：一次 `gh release view` 给全部附件的 `Asset`（名字、大小、
摘要），`fetch_assets()` 只是它的名字投影。生成校验清单的 `tool/release_meta.py` 也消费它。

`read_entries()` 给页面条目的完整字段（版本、id、文件名、大小、sha），`read_page()` 是它的
`(id, file)` 投影；`human_size()` 是页面上的大小写法（十进制 MB、一位小数、四舍五入），
回填页面与将来的对账共用这一份，两边各写一份会漂。

退出码：0 一致；1 两侧文件名不一致；2 取数失败（读不到 REL、网络、API 限额、tag 不存在）。
"""
import json
import re
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))   # 直接跑脚本与作为 tool.<模块> import 两种都认
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


def read_page(text):
    """`read_entries` 的 (id, file) 投影；任一卡片读不出文件名就返回 (None, [])。

    配对关系是这个模块唯一要保证的东西：给不出配对比给出一份空清单更安全。
    """
    version, entries = read_entries(text)
    if version is None or any(not entry.file for entry in entries):
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


class Asset(NamedTuple):
    """Release 上的一个附件：`digest` 是 `gh` 原文，形如 `sha256:<64 位十六进制>`。"""
    name: str
    size: int
    digest: str


def run_gh(*args):
    """跑 `gh <args>` 并返回 stdout；跑不起或退出码非 0 时抛 RuntimeError（取数失败的统一形状）。"""
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError as error:
        raise RuntimeError(f"跑不起 gh：{error}") from error
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()
        raise RuntimeError(detail or f"gh 退出码 {done.returncode}")
    return done.stdout


def fetch_release(tag):
    """`gh release view <tag>` 的全量附件；取不到时抛 RuntimeError。"""
    try:
        rows = json.loads(run_gh("release", "view", tag, "--json", "assets"))["assets"]
        return [Asset(name=str(row.get("name") or ""), size=int(row.get("size") or 0),
                      digest=str(row.get("digest") or "")) for row in rows]
    except (AttributeError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"读不出 {tag} 的附件：{error}") from error


def fetch_assets(tag):
    """`fetch_release` 的名字投影：附件名清单；取不到时抛 RuntimeError。"""
    return [asset.name for asset in fetch_release(tag)]


def main(argv, fetch=fetch_assets, page=PAGE):
    version, entries = read_page(Path(page).read_text(encoding="utf-8"))
    if version is None:
        print(f"{page} 里读不到 REL 的 version 与 files：页面结构变了，这条检查没法比对。",
              file=sys.stderr)
        return EXIT_UNREACHABLE
    tag = argv[0].strip() if argv and argv[0].strip() else f"v{version}"
    try:
        release = fetch(tag)
    except RuntimeError as error:
        print(f"取不到 {tag} 的附件，没法比对：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    files = [name for _, name in entries]
    only_page, only_release = compare(files, release)
    if only_page or only_release:
        print(f"{tag} 与 {Path(page).name} 的 REL.files 对不上：", file=sys.stderr)
        if only_page:
            print("  页面有、Release 没有：" + "、".join(only_page), file=sys.stderr)
        if only_release:
            print("  Release 有、页面没有：" + "、".join(only_release), file=sys.stderr)
        return EXIT_MISMATCH
    print(f"{tag} 的 {len(files)} 个附件与 REL.files 一致。")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
