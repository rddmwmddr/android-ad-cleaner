"""入口速查表（tool/entries.py）：每条入口有出处、文档与表同步、reach() 按快慢回退。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import entries  # noqa: E402

DOCS = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "清单").glob("*.md")
                 if p.name != "入口速查.md")


class SourceTest(unittest.TestCase):
    """没有出处的入口会让引擎跳到别处：每条都要在机型脚本里用过，或在手动清单里写着。"""

    def test_every_entry_has_a_source(self):
        used = entries.used_by(str(ROOT / "recipes"))
        for fam, sections in entries.ENTRIES.items():
            for name, e in sections.items():
                self.assertTrue(e.menu, f"{fam}·{name} 缺菜单路径")
                for d in e.direct:
                    key = ("direct", d.pkg, entries.full(d.pkg, d.activity))
                    self.assertTrue(key in used or d.activity.lstrip(".") in DOCS, f"{fam}·{name} 直达 {key} 没有出处")
                for s in e.search:
                    self.assertTrue(("search", s.keyword, s.result) in used or f"搜索「{s.keyword}」" in DOCS
                                    or f"搜「{s.keyword}」" in DOCS, f"{fam}·{name} 搜索「{s.keyword}」没有出处")

    def test_every_brand_maps_to_a_family_with_entries(self):
        for brand, fam in entries.FAMILY.items():
            self.assertIn(fam, entries.ENTRIES, brand)
        self.assertEqual(entries.family("Redmi"), "小米")
        self.assertIsNotNone(entries.lookup("REDMI", "系统广告"))
        self.assertIsNone(entries.lookup("google", "系统广告"))

    def test_doc_is_generated_from_table(self):
        doc = (ROOT / "docs" / "清单" / "入口速查.md").read_text(encoding="utf-8")
        self.assertEqual(doc, entries.markdown(str(ROOT / "recipes")),
                         "改了 tool/entries.py 或机型脚本后重新生成：python3 tool/entries.py > docs/清单/入口速查.md")


class FakePhone:
    def __init__(self, lands=(), searches=()):
        self.lands, self.searches = set(lands), set(searches)
        self.shells, self.searched, self.current = [], [], "launcher/.Home"
        outer = self

        class Reader:
            def shell(self, cmd):
                outer.shells.append(cmd)
                page = cmd.rsplit(" ", 1)[-1]
                if page in outer.lands:
                    outer.current = page
                return type("R", (), {"output": "Starting: Intent"})()
        self.reader = Reader()

    def focus(self):
        return self.current

    def expect_page(self, expect, timeout):
        return True

    def setting(self, keyword, result):
        self.searched.append(keyword)
        return keyword in self.searches


class ReachTest(unittest.TestCase):
    ENTRY = entries.Entry(menu="设置 → …",
                          direct=(entries.Direct("com.a", ".One"), entries.Direct("com.a", "com.a.Two")),
                          search=(entries.Search("广告", "广告与隐私"),))

    def test_direct_first(self):
        p = FakePhone(lands={"com.a/com.a.One"})
        self.assertEqual(entries.reach(p, self.ENTRY, log=lambda *a: None), "direct")
        self.assertEqual(p.searched, [])

    def test_falls_back_to_search(self):
        import wait
        saved = wait.until
        wait.until = lambda sample, **k: sample() or None     # 不真等 4 秒
        try:
            p = FakePhone(searches={"广告"})
            self.assertEqual(entries.reach(p, self.ENTRY, log=lambda *a: None), "search")
            self.assertEqual(len(p.shells), 2)
            self.assertEqual(entries.reach(FakePhone(), self.ENTRY, log=lambda *a: None), None)
        finally:
            wait.until = saved


if __name__ == "__main__":
    unittest.main()
