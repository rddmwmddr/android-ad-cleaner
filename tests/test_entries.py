"""入口速查表（tool/entries.py）：每条入口有出处、文档与表同步、reach() 按快慢回退。"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import entries  # noqa: E402
import fixtures  # noqa: E402

DOCS = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "清单").glob("*.md")
                 if p.name != "入口速查.md")
RECIPES = str(ROOT / "recipes")


def no_wait(_seconds):
    """等页面时不要真睡：until() 有轮数上限，换成 no-op 就立刻退出。"""


class SourceTest(unittest.TestCase):
    """没有出处的入口会让引擎跳到别处：每条都要在机型脚本里用过，或在手动清单里写着。"""

    def test_every_entry_has_a_source(self):
        used = entries.used_by(RECIPES)
        for fam, groups in entries.ENTRIES.items():
            for name, e in groups.items():
                self.assertTrue(e.menu, f"{fam}·{name} 缺菜单路径")
                for d in e.direct:
                    key = ("direct", d.pkg, entries.full(d.pkg, d.activity))
                    self.assertTrue(key in used or d.activity.lstrip(".") in DOCS,
                                    f"{fam}·{name} 直达 {key} 没有出处")
                for s in e.search:
                    self.assertTrue(("search", s.keyword, s.result) in used or f"搜索「{s.keyword}」" in DOCS
                                    or f"搜「{s.keyword}」" in DOCS, f"{fam}·{name} 搜索「{s.keyword}」没有出处")

    def test_every_brand_in_recipes_has_a_family_table(self):
        """脚本里出现过的品牌都要查得到。三星进目录时就是漏了这一步（#605）。"""
        brands = {p.name.split("-", 1)[0].lower() for p in (ROOT / "recipes").iterdir() if p.is_dir()}
        for brand in brands:
            fam = entries.family(brand)
            self.assertIn(fam, entries.ENTRIES, f"recipes/ 里的 {brand} 没有家族表")

    def test_every_family_has_entries_and_a_label(self):
        for fam in entries.ENTRIES:
            self.assertIn(fam, entries.LABEL, f"{fam} 缺文档里的写法")
        for fam in set(entries.FAMILY.values()):
            self.assertIn(fam, entries.ENTRIES, f"FAMILY 里的 {fam} 没有任何分组")

    def test_family_normalizes_sub_brands(self):
        self.assertEqual(entries.family("Redmi"), "xiaomi")
        self.assertEqual(entries.family("REDMI"), "xiaomi")
        self.assertEqual(entries.family("poco"), "xiaomi")
        self.assertEqual(entries.family("iQOO"), "vivo")
        self.assertEqual(entries.family("OnePlus"), "oppo")
        self.assertEqual(entries.family("realme"), "oppo")
        self.assertEqual(entries.family("samsung"), "samsung")
        self.assertIsNotNone(entries.lookup("REDMI", "系统广告"))
        self.assertIsNone(entries.lookup("google", "系统广告"))

    def test_used_by_reads_variable_packages(self):
        """honor-WKL-AN20 写的是 p.start(package, ".X")：只认字面量会把这台机漏掉。"""
        used = entries.used_by(RECIPES)
        key = ("direct", "com.hihonor.systemmanager",
               "com.hihonor.systemmanager.mainscreen.SettingActivity")
        self.assertIn(key, used)
        self.assertIn("WKL-AN20", used[key])

    def test_doc_is_generated_from_table(self):
        doc = (ROOT / "docs" / "清单" / "入口速查.md").read_text(encoding="utf-8")
        self.assertEqual(doc, entries.markdown(RECIPES),
                         "改了 tool/entries.py 或机型脚本后重新生成：python3 tool/entries.py > docs/清单/入口速查.md")


class FakeReader:
    """读屏替身：按命令回前台与页面文字。`lands` 是这台「手机」进得去的包名/页面。"""

    def __init__(self, lands=(), searches=(), page_text="首页"):
        self.lands, self.searches = set(lands), set(searches)
        self.page_text = page_text
        self.shells, self.searched = [], []
        self.settings = {}
        self.current = "launcher/.Home"

    def shell(self, cmd, timeout=None):
        self.shells.append(cmd)
        out = ""
        if cmd.startswith("am start"):
            pkg, act = cmd.rsplit(" ", 1)[-1].split("/", 1)
            page = f"{pkg}/{pkg + act if act.startswith('.') else act}"
            # 页面不在 lands 里就落在同 App 的别的页：App 到了前台，但不是要的那一页
            self.current = page if page in self.lands else f"{pkg}/.SomeOtherActivity"
            out = f"Starting: Intent {{ cmp={page} }}"
        elif "dumpsys window" in cmd:
            out = f"  mCurrentFocus=Window{{4c2 u0 {self.current}}}\n"
        return types.SimpleNamespace(output=out, exit_code=0)

    def window_size(self):
        return 1080, 2400

    def dump_hierarchy(self):
        return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
                f'<node text="{self.page_text}" package="com.a" class="android.widget.TextView" '
                'bounds="[100,400][900,500]" clickable="true" enabled="true" /></hierarchy>')

    def app_stop(self, package):
        return None

    def close(self):
        self.closed = True


def phone(reader, lands=(), searches=()):
    """一台带假读屏的 Phone，装配走 fixtures.phone_stub()。"""
    return fixtures.phone_stub("test", d=reader, W=1080, H=2400)


class ReachTest(unittest.TestCase):
    ENTRY = entries.Entry(menu="设置 → …",
                          direct=(entries.Direct("com.a", ".One"), entries.Direct("com.a", "com.a.Two")),
                          search=(entries.Search("广告", "广告与隐私"),))

    def reach(self, p, entry=None):
        return entries.reach(p, entry or self.ENTRY, log=lambda *a: None, sleep=no_wait)

    def test_direct_first(self):
        r = FakeReader(lands={"com.a/com.a.One"})
        self.assertEqual(self.reach(phone(r)), "direct")
        self.assertEqual(r.searched, [])

    def test_wrong_page_is_not_a_landing(self):
        """同包的别的页面、以及别的包里的同名页面，都不算到。只比类名尾段时后者会被当成到了。"""
        r = FakeReader()
        p = phone(r)
        r.current = "com.a/com.a.SettingsActivity"
        self.assertFalse(entries.landed(p, entries.Direct("com.a", ".One")))
        r.current = "com.other/com.other.One"
        self.assertFalse(entries.landed(p, entries.Direct("com.a", ".One")))
        r.current = "com.a/.One"
        self.assertTrue(entries.landed(p, entries.Direct("com.a", ".One")))

    def test_falls_back_to_search(self):
        r = FakeReader()
        r.setting = lambda kw, result: r.searched.append(kw) or kw in ("广告",)
        p = phone(r)
        p.setting = r.setting
        self.assertEqual(self.reach(p), "search")
        self.assertEqual(r.searched, ["广告"])
        launches = [c for c in r.shells if c.startswith("am start") and "com.a/" in c]
        self.assertEqual(len(launches), 2)          # 两条直达都试过才降级

    def test_nothing_reachable_returns_none(self):
        p = phone(FakeReader())
        p.setting = lambda kw, result: False
        self.assertIsNone(self.reach(p))

    def test_keep_task_page_is_launched_bare(self):
        """ColorOS 17 的浏览器设置页带清栈参数会立刻退出（#165），只能裸 am start。"""
        r = FakeReader(lands={"com.b/com.b.Page"})
        entry = entries.Entry(menu="…", direct=(entries.Direct("com.b", ".Page", keep_task=True),))
        self.assertEqual(self.reach(phone(r), entry), "direct")
        self.assertEqual(r.shells[0], "am start -n com.b/com.b.Page")

    def test_expect_keeps_a_landed_page_out_of_the_fast_path(self):
        """落在对的页面但没看见判据文字，仍算没到。"""
        r = FakeReader(lands={"com.b/com.b.Page"}, page_text="别的页")
        entry = entries.Entry(menu="…", direct=(entries.Direct("com.b", ".Page", expect="个性化推荐"),))
        p = phone(r)
        p.setting = lambda kw, result: False
        self.assertIsNone(self.reach(p, entry))

    def test_launch_failure_moves_to_the_next_entry(self):
        r = FakeReader(lands={"com.a/com.a.Two"})

        def boom(cmd, timeout=None):
            if "-n com.a/com.a.One" in cmd:
                raise RuntimeError("Activity not exported")
            return FakeReader.shell(r, cmd, timeout)
        r.shell = boom
        self.assertEqual(self.reach(phone(r)), "direct")


if __name__ == "__main__":
    unittest.main()
