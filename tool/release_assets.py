"""下载页的 REL 与 GitHub Release 附件对账（#1003）。

用法：

    python3 tool/release_assets.py          # 比 index.html 的 REL.version 那个 tag
    python3 tool/release_assets.py v0.4.0   # 比指定的 tag

`REL.files` 每条的 `id` 是下载卡片的身份，`file` 是 Release 里的附件名；两边任一侧改了名字
而另一侧没跟上，用户点下载就是 404。静态那一半（`id` 冻结、`file` 里的版本号等于
`REL.version`）在 `tests/test_rules_guards.py` 的 `ReleaseGuards` 里，不需要 GitHub 凭据；
这里只比名字集合，不比 sha——sha 每次发版都变，比对会天天误报。

退出码：0 一致；1 两侧文件名不一致；2 取数失败（读不到 REL、网络、API 限额、tag 不存在）。
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # 直接跑脚本与作为 tool.<模块> import 两种都认
from stdio import use_utf8_console                         # noqa: E402

use_utf8_console()

PAGE = Path(__file__).resolve().parents[1] / "index.html"

# 只认 `const REL = {` 到顶格 `};` 这一段：页面别处也有 `id` / `file` 字样（DOM 与文案）。
BLOCK = re.compile(r"const REL = \{(.*?)\n\};", re.S)
VERSION = re.compile(r'\bversion:\s*"([^"]+)"')
ENTRY_ID = re.compile(r'\bid:\s*"([^"]+)"')
ENTRY_FILE = re.compile(r'\bfile:\s*"([^"]+)"')

# Release 里不属于下载卡片的附件：校验清单随版本走，页面上没有它的入口。
EXTRA_ASSETS = frozenset({"SHA256SUMS.txt"})

EXIT_OK, EXIT_MISMATCH, EXIT_UNREACHABLE = 0, 1, 2


def read_page(text):
    """从 index.html 的源码里读出 (REL.version, [(id, file)])；读不出返回 (None, [])。

    id 与 file 的条数对不上时也按「读不出」处理：配对关系是这个模块唯一要保证的东西，
    给不出配对比给出一份空清单更安全。
    """
    match = BLOCK.search(text)
    if not match:
        return None, []
    block = match.group(1)
    found = VERSION.search(block)
    ids, files = ENTRY_ID.findall(block), ENTRY_FILE.findall(block)
    if not found or not ids or len(ids) != len(files):
        return None, []
    return found.group(1), list(zip(ids, files, strict=True))    # 上面已判过 len(ids) == len(files)


def compare(page_files, release_files):
    """两侧附件名的差集：(页面有 Release 没有, Release 有页面没有)，各自有序。"""
    page = set(page_files)
    release = set(release_files) - EXTRA_ASSETS
    return sorted(page - release), sorted(release - page)


def fetch_assets(tag):
    """`gh release view <tag>` 的附件名清单；取不到时抛 RuntimeError。"""
    try:
        done = subprocess.run(
            ["gh", "release", "view", tag, "--json", "assets", "--jq", ".assets[].name"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as error:
        raise RuntimeError(f"跑不起 gh：{error}") from error
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()
        raise RuntimeError(detail or f"gh 退出码 {done.returncode}")
    return [name for name in done.stdout.splitlines() if name.strip()]


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
