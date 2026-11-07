"""把 site.css 渲染进官网两页的 <style>（#653）。

用法：python tool/gen_site_css.py
只改 site.css 一处，跑本脚本，两页同时生效；漏跑则 tests/test_doc_consistency.py 红。

渲染范围是两页 <style> 里 `site-css:start` / `site-css:end` 标记之间的内容，其余一字不动。
页面不引用 site.css 本身：GitHub Pages 与机主服务器上的单文件副本都只认页面里内联的那份。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "site.css"
TARGETS = {
    "home": ROOT / "index.html",
    "tutorial": ROOT / "android-tutorial.html",
}
START = "/* site-css:start */"
END = "/* site-css:end */"


def load_css():
    css = SOURCE.read_text(encoding="utf-8").strip("\n")
    if not css.strip():
        sys.exit("site.css 没有内容")
    return css


def check_markers(text, name):
    """每页必须恰好一对标记、且 start 在 end 之前，否则 replace_region 会切错位置。"""
    starts, ends = text.count(START), text.count(END)
    if (starts, ends) != (1, 1):
        raise ValueError(f"{name} 的 site-css 标记区应恰好一对（实际 start={starts} end={ends}）")
    if text.index(START) > text.index(END):
        raise ValueError(f"{name} 的 site-css 结束标记在开始标记之前")


def replace_region(text, rendered):
    """把标记之间的旧内容换成 rendered，标记本身保留。"""
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return head + START + "\n" + rendered + "\n" + END + tail


def main():
    css = load_css()
    texts = {key: path.read_text(encoding="utf-8") for key, path in TARGETS.items()}
    for key, path in TARGETS.items():
        try:
            check_markers(texts[key], path.name)
        except ValueError as e:
            sys.exit(str(e))
    for key, path in TARGETS.items():
        updated = replace_region(texts[key], css)
        if updated != texts[key]:
            path.write_text(updated, encoding="utf-8", newline="\n")
            print(f"updated {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
