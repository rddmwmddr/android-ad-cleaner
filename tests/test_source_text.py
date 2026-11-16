"""源码文本的两条机械规则：不写裸的零宽字符；基线钉提交 SHA，不写会随并行会话前进的引用。"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 拼接构造：这个文件自己也在扫描范围里。
FLOATING = ("git " + "archive origin/main", "git " + "archive main")
# 只查「给出命令」的地方。CHANGELOG 与 docs/ 记录的是当时怎么做的，改它们等于改写历史。
PRESCRIPTIVE = ("CLAUDE.md", "CONTEXT.md", "CODING_STANDARDS.md", "AGENTS.md")
# 用转义定义，这个文件自身不能出现裸字符。
FORBIDDEN = {
    "\u200b": "U+200B ZERO WIDTH SPACE",
    "\ufeff": "U+FEFF ZERO WIDTH NO-BREAK SPACE / BOM",
    "\u200c": "U+200C ZERO WIDTH NON-JOINER",
    "\u200d": "U+200D ZERO WIDTH JOINER",
    "\u2060": "U+2060 WORD JOINER",
}


class SourceTextTests(unittest.TestCase):
    def test_source_has_no_raw_zero_width_characters(self):
        hits = []
        for folder in ("tool", "devtools", "gui", "tests"):
            for path in sorted((ROOT / folder).rglob("*.py")):
                for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    for char, label in FORBIDDEN.items():
                        if char in line:
                            hits.append(f"{path.relative_to(ROOT)}:{lineno}: {label}")
        self.assertEqual(hits, [], "源码里不写裸零宽字符，用 \\u 转义：\n" + "\n".join(hits))


    def test_baselines_are_pinned_to_a_commit(self):
        """并行会话随时推进 main，浮动引用会让「改动前」悄悄变成另一份代码。"""
        paths = [ROOT / name for name in PRESCRIPTIVE]
        paths += [p for folder in ("tool", "devtools", "gui", "tests") for p in sorted((ROOT / folder).rglob("*.py"))]
        hits = []
        for path in paths:
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for literal in FLOATING:
                    if literal in line:
                        hits.append(f"{path.relative_to(ROOT)}:{lineno}: {literal}")
        self.assertEqual(hits, [], "基线要钉提交 SHA（先 `git rev-parse` 记下，再 archive）：\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
