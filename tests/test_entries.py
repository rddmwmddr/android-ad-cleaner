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

    def test_non_literal_reassignment_does_not_reuse_an_older_literal(self):
        """最后一次赋值不是字面量时不记出处：退回更早的旧值会把机型挂到别的包上。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "brand-model"
            model.mkdir()
            (model / "recipe.py").write_text(
                'package = "com.old"\npackage = helper()\ndef _():\n    p.start(package, ".B")\n',
                encoding="utf-8")
            self.assertEqual(entries.used_by(d), {})

    def test_honor_minus_one_screen_direct_entry_is_registered(self):
        """CLE-AN00 用 hiboard 直达负一屏首页，ENTRIES 要跟着登记（#671）。"""
        e = entries.ENTRIES["honor"]["负一屏"]
        self.assertTrue(any(d.activity == "com.hihonor.intelligent.LauncherActivity" for d in e.direct),
                        "honor·负一屏 缺 CLE-AN00 实测到的直达页")

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
            target = cmd.rsplit(" ", 1)[-1].strip("'")     # 手机上的 sh 会剥掉引号，替身照做
            pkg, act = target.split("/", 1)
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


def phone(reader):
    """一台带假读屏的 Phone，装配走 fixtures.phone_stub()。"""
    return fixtures.phone_stub("test", d=reader, W=1080, H=2400)


class ReachTest(unittest.TestCase):
    ENTRY = entries.Entry(menu="设置 → …",
                          direct=(entries.Direct("com.a", ".One"), entries.Direct("com.a", "com.a.Two")),
                          search=(entries.Search("广告", "广告与隐私"),))

    def reach(self, p, entry=None):
        return entries.reach(p, entry or self.ENTRY, log=lambda *a: None, sleep=no_wait, settle=0)

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

    def test_search_path_is_forwarded_when_the_entry_has_one(self):
        """同名结果有多条时按位置挑（#650 的 PMX110 广告跟踪）：reach() 要把 path 传下去。"""
        entry = entries.Entry(menu="…", search=(
            entries.Search("广告", "广告与隐私", path="隐私与安全 > 隐私"),))
        seen = []
        p = phone(FakeReader())
        p.setting = lambda kw, result, **extra: seen.append((kw, result, extra)) or False
        self.assertIsNone(self.reach(p, entry))
        self.assertEqual(seen, [("广告", "广告与隐私", {"path": "隐私与安全 > 隐私"})])

    def test_dollar_in_the_page_name_is_quoted_at_the_shell(self):
        """页面名带 $ 时手机上的 shell 会当变量展开（vivo `.Settings$AdAndPrivacy…`，#667）：引擎边界引用一次。"""
        r = FakeReader(lands={"com.a/com.a.Settings$Ad"})
        phone(r).start("com.a", ".Settings$Ad")
        self.assertEqual(r.shells[0], "am start -f 0x10008000 -n 'com.a/.Settings$Ad'")

    def test_plain_page_name_reaches_the_shell_unchanged(self):
        r = FakeReader(lands={"com.a/com.a.One"})
        phone(r).start("com.a", ".One")
        self.assertEqual(r.shells[0], "am start -f 0x10008000 -n com.a/.One")

    def test_keep_task_page_is_launched_bare(self):
        """ColorOS 17 的浏览器设置页带清栈参数会立刻退出（#165），只能裸 am start。"""
        r = FakeReader(lands={"com.b/com.b.Page"})
        entry = entries.Entry(menu="…", direct=(entries.Direct("com.b", ".Page", keep_task=True),))
        self.assertEqual(self.reach(phone(r), entry), "direct")
        self.assertEqual(r.shells[0], "am start -n com.b/com.b.Page")

    def test_keep_task_page_with_dollar_is_quoted_here(self):
        """`keep_task` 的裸 am start 不经 Phone.start，引用由 open_direct 自己做（#667）。"""
        r = FakeReader(lands={"com.b/com.b.Settings$Ad"})
        entry = entries.Entry(menu="…", direct=(entries.Direct("com.b", ".Settings$Ad", keep_task=True),))
        self.assertEqual(self.reach(phone(r), entry), "direct")
        self.assertEqual(r.shells[0], "am start -n 'com.b/com.b.Settings$Ad'")

    def test_expect_keeps_a_landed_page_out_of_the_fast_path(self):
        """落在对的页面但没看见判据文字，仍算没到。"""
        r = FakeReader(lands={"com.b/com.b.Page"}, page_text="别的页")
        entry = entries.Entry(menu="…", direct=(entries.Direct("com.b", ".Page", expect="个性化推荐"),))
        p = phone(r)
        seen = []
        p.expect_page = lambda expect, timeout=None: seen.append((expect, timeout)) or False
        p.setting = lambda kw, result: False
        self.assertIsNone(self.reach(p, entry))
        self.assertEqual(seen, [("个性化推荐", 3)])

    def test_disconnect_is_not_treated_as_a_dead_entry(self):
        """断线要上抛：当成「这一档不通」接着拉下一档，只会在断了的机器上继续点。"""
        import adb_link
        p = phone(FakeReader())

        def gone(*a, **k):
            raise adb_link.DeviceLost("device offline")
        p.start = gone
        with self.assertRaises(adb_link.DeviceLost):
            self.reach(p)

    def test_reader_failure_after_lost_flag_is_still_a_disconnect(self):
        """读屏抛的原始异常不一定转成 DeviceLost，但 Phone.lost 已置位：同样要上抛。"""
        p = phone(FakeReader())
        p.lost = True

        def broken(*a, **k):
            raise RuntimeError("uiautomator dump failed")
        p.start = broken
        with self.assertRaises(RuntimeError):
            self.reach(p)

    def test_bare_launch_failure_is_reported_as_cannot_open(self):
        """裸启动打不开要报「打不开」，不能报成「没落在这一页」——后者会让人去怀疑落点判据。"""
        r = FakeReader()
        entry = entries.Entry(menu="…", direct=(entries.Direct("com.b", ".Page", keep_task=True),))
        r.shell = lambda cmd, timeout=None: types.SimpleNamespace(
            output="Error: Activity not started, unable to resolve Intent", exit_code=1)
        p = phone(r)
        p.setting = lambda kw, result: False
        lines = []
        self.assertIsNone(entries.reach(p, entry, log=lines.append, sleep=no_wait, settle=0))
        self.assertTrue(any("打不开" in line for line in lines), lines)

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
