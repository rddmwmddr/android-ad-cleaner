"""入口速查表与各品牌脚本怎么走到某个入口（tool/entries.py）。

两部分：表本身（每条入口有出处、文档与表同步、reach() 按直达与搜索回退），
以及消费它的行为——齿轮判据、直达与回退、浏览器 / 主题 / 商店 / 负一屏这几段怎么进页。
每个来源文件的原票号留在那段注释里。
"""
import ast
import contextlib
import io
import re
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adb_link  # noqa: E402
import chan_fast  # noqa: E402
import entries  # noqa: E402
import fast  # noqa: E402
import fixtures  # noqa: E402
import recipe_source  # noqa: E402
import row  # noqa: E402
from fast import ScreenLocked  # noqa: E402
from row import icon_hit  # noqa: E402
from fixtures import (EMPTY_PAGE, Clock, clocked, fake_phone, load_recipe,  # noqa: E402
                      phone_mock, phone_stub, stub)

DOCS = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "清单").glob("*.md")
                 if p.name != "入口速查.md")
RECIPES = str(ROOT / "recipes")


def no_wait(_seconds):
    """等页面时不要真睡：until() 有轮数上限，换成 no-op 就立刻退出。"""


def _store_factory(p, g):
    """一份最小的段体工厂：入口写在实现里，包名住在调用脚本的模块常量里。"""
    def store():
        p.start(g["MARKET"], ".Main")
    return store


def _browser_home_factory(p, g):
    """段体只调导航助手：包名与页面名两层都在注入面里。"""
    def browser_home():
        return g["settings_direct"]()
    return browser_home


def _settings_direct_factory(p, g):
    def settings_direct():
        return g["open_app_settings"]("com.example.browser", "com.example.browser.Settings", "设置")
    return settings_direct


class SourceTest(unittest.TestCase):
    """没有出处的入口会让引擎跳到别处：每条都要在机型脚本里用过，或在手动清单里写着。"""

    def test_every_entry_has_a_source(self):
        used = entries.used_by(RECIPES)
        for fam, groups in entries.ENTRIES.items():
            for name, e in groups.items():
                self.assertTrue(e.menu, f"{fam}·{name} 缺菜单路径")
                for d in e.direct:
                    if d.action:
                        self.assertTrue(d.activity, f"{fam}·{name} 的 Intent 档缺落点页面")
                        self.assertTrue(("intent", d.action, d.pkg) in used
                                        or (d.action in DOCS and d.pkg in DOCS),
                                        f"{fam}·{name} 的 Intent 入口 {d.action}（{d.pkg}）没有出处")
                        continue
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

    def test_used_by_reads_public_intent_launches(self):
        """9 份脚本把 APP_SETTINGS 抄成三种写法：字面量、拼接的变量、模板常量 .format 传参。
        漏掉任何一种，「用过的机型」与「可提速提示」都会少机型（#956）。"""
        used = entries.used_by(RECIPES)
        market = ("intent", "oppo.intent.action.APP_SETTINGS", "com.heytap.market")
        self.assertIn(market, used)
        self.assertIn("PMX110", used[market])      # `-p " + package` + app_settings(MARKET)
        self.assertIn("PJA110", used[market])      # SETTINGS_INTENT.format(package)
        self.assertIn("PKX110", used[market])      # 助手函数被传入字面量
        browser = ("intent", "oppo.intent.action.APP_SETTINGS", "com.heytap.browser")
        self.assertIn("PLG110", used[browser])
        self.assertNotIn("PMX110", used[browser])  # PMX110 的浏览器走裸 `-n`，不是这个 Intent
        self.assertIn(("intent", "oppo.intent.action.APP_SETTINGS", "com.heytap.themestore"),
                      used)                        # 字面量：PKH110

    def test_markdown_shows_the_public_intent_and_its_models(self):
        doc = entries.markdown(RECIPES)
        row = next(line for line in doc.splitlines() if line.startswith("| 软件商店 |"))
        self.assertIn("`am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market`", row)
        self.assertIn("PMX110", row)               # 「用过的机型」进了这一格
        self.assertIn("`am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.browser`", doc)
        self.assertIn("OPPO / 软件商店 / ", doc)    # 可提速提示覆盖这一档

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

    def test_a_locally_defined_helper_is_not_the_injected_one(self):
        """脚本定义了同名助手，注入面那份就不在场上：不扣减会把它记成用过别家的 Intent。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "brand-model"
            model.mkdir()
            (model / "recipe.py").write_text(
                'def app_settings(package, *markers):\n'
                '    return package\n\n\n'
                'def _():\n'
                '    app_settings("com.hihonor.appmarket", "内容推荐服务")\n',
                encoding="utf-8")
            self.assertEqual(entries.used_by(d), {})

    def test_navigation_implementations_ignore_caller_constants(self):
        """`used_by()` 把调用脚本的常量一并传给每份注入实现：今天没有导航助手按名字取外部值，
        所以传与不传必须逐字相同，否则这条接线会悄悄改变「用过的机型」（#1209）。"""
        import recipe_source
        import recipe_steps
        constants = {"MARKET": ("com.example.market",), "HOT": ("热点资讯",)}
        for name, impl in recipe_source.injected_sources().items():
            if name in recipe_steps.STEPS:
                continue
            self.assertEqual(recipe_source.scan_source(impl, externals=constants).calls,
                             recipe_source.scan_source(impl).calls, name)

    def test_an_entry_inside_a_step_implementation_is_credited_to_the_caller(self):
        """段体搬进注入面之后，实现里的拉起仍认得出属于哪个机型（#1209）。"""
        import recipe_steps
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "xiaomi-model"
            model.mkdir()
            (model / "recipe.py").write_text(
                'MARKET = "com.example.market"\n\n\n'
                '@step("商店")\n'
                'def _():\n'
                '    store()\n',
                encoding="utf-8")
            with patch.dict(recipe_steps.STEPS, {"store": _store_factory}):
                used = entries.used_by(d)
        self.assertEqual(used, {("direct", "com.example.market",
                                 "com.example.market.Main"): {"model"}})

    def test_an_entry_two_hops_down_is_credited_to_the_caller(self):
        """段体调导航助手、入口写在助手实现里（#1212）：只看脚本那一层会把调段体的机型漏掉。"""
        import recipe_nav
        import recipe_steps
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "oneplus-model"
            model.mkdir()
            (model / "recipe.py").write_text(
                '@step("浏览器首页")\n'
                'def _():\n'
                '    browser_home()\n',
                encoding="utf-8")
            with patch.dict(recipe_steps.STEPS, {"browser_home": _browser_home_factory}), \
                    patch.dict(recipe_nav.NAV, {"settings_direct": _settings_direct_factory}):
                used = entries.used_by(d)
        self.assertEqual(used, {("intent", "oppo.intent.action.APP_SETTINGS", "com.example.browser"):
                                {"model"}})

    def test_a_locally_defined_helper_two_hops_down_is_not_the_injected_one(self):
        """脚本本地定义了段体要调的导航助手：注入版不在场上，第二层也不记出处（#1212）。"""
        import recipe_nav
        import recipe_steps
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "oneplus-model"
            model.mkdir()
            (model / "recipe.py").write_text(
                'def settings_direct():\n'
                '    return False\n\n\n'
                '@step("浏览器首页")\n'
                'def _():\n'
                '    browser_home()\n',
                encoding="utf-8")
            with patch.dict(recipe_steps.STEPS, {"browser_home": _browser_home_factory}), \
                    patch.dict(recipe_nav.NAV, {"settings_direct": _settings_direct_factory}):
                used = entries.used_by(d)
        self.assertEqual(used, {})

    def test_open_app_settings_needs_two_arguments(self):
        """只传了包名的 open_app_settings 不算出处：把包名当成页面会给这台机凭空挂一条 Intent。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "brand-model"
            model.mkdir()
            (model / "recipe.py").write_text(
                'def open_app_settings(package):\n'
                '    p.start(package, ".SettingsActivity")\n\n\n'
                'def _():\n'
                '    open_app_settings("com.heytap.market")\n',
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
    """读屏替身：按命令回前台与页面文字。`lands` 是这台「手机」进得去的包名/页面，
    `intents` 是公开 Intent 按包名落到的页面。"""

    def __init__(self, lands=(), searches=(), page_text="首页", intents=None):
        self.lands, self.searches = set(lands), set(searches)
        self.intents = dict(intents or {})
        self.page_text = page_text
        self.shells, self.searched = [], []
        self.settings = {}
        self.current = "launcher/.Home"

    def shell(self, cmd, timeout=None):
        self.shells.append(cmd)
        out = ""
        if cmd.startswith("am start") and " -a " in cmd:
            pkg = re.search(r" -p (\S+)", cmd).group(1)
            # 不在 intents 里就落在同 App 的别的页：App 到了前台，但不是要的那一页
            self.current = self.intents.get(pkg, f"{pkg}/.SomeOtherActivity")
            out = f"Starting: Intent {{ pkg={pkg} }}"
        elif cmd.startswith("am start"):
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

    def test_allow_search_false_never_opens_the_settings_search(self):
        """只试直达档：设置搜索会把设备交给系统设置，入口必须留在本 App 里时不能走（#912）。"""
        r = FakeReader()
        seen = []
        p = phone(r)
        p.setting = lambda *a, **kw: seen.append(a) or True
        self.assertIsNone(entries.reach(p, self.ENTRY, log=lambda *a: None,
                                        sleep=no_wait, settle=0, allow_search=False))
        self.assertEqual(seen, [])
        launches = [c for c in r.shells if c.startswith("am start") and "com.a/" in c]
        self.assertEqual(len(launches), 2)          # 两条直达都试过，只是不降级到搜索

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

    INTENT = entries.Entry(menu="…", direct=(
        entries.Direct("com.a", ".Market", action="oppo.intent.action.APP_SETTINGS"),))

    def test_public_intent_entry_launches_with_the_action(self):
        """Intent 档用 `am start -f 0x10008000 -a <action> -p <包名>` 拉起，落点仍按包名/页面核对。"""
        r = FakeReader(intents={"com.a": "com.a/com.a.Market"})
        self.assertEqual(self.reach(phone(r), self.INTENT), "direct")
        self.assertEqual(r.shells[0],
                         "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.a")

    def test_intent_landing_on_another_page_moves_to_the_next_entry(self):
        """Intent 把 App 拉到前台却落在别的页：这一档不算到，换下一条。"""
        r = FakeReader(lands={"com.a/com.a.Market"})   # Intent 没登记落点 → 停在别的页
        entry = entries.Entry(menu="…", direct=(
            entries.Direct("com.a", ".Market", action="oppo.intent.action.APP_SETTINGS"),
            entries.Direct("com.a", ".Market")))
        self.assertEqual(self.reach(phone(r), entry), "direct")
        launches = [c for c in r.shells if c.startswith("am start")]
        self.assertEqual(len(launches), 2)
        self.assertTrue(launches[0].startswith("am start -f 0x10008000 -a "))
        self.assertEqual(launches[1], "am start -f 0x10008000 -n com.a/.Market")

    def test_intent_disconnect_is_not_treated_as_a_dead_entry(self):
        """Intent 档断线同样上抛，不当成「这一档不通」。"""
        import adb_link
        r = FakeReader()

        def gone(cmd, timeout=None):
            raise adb_link.DeviceLost("device offline")
        r.shell = gone
        with self.assertRaises(adb_link.DeviceLost):
            self.reach(phone(r), self.INTENT)

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


# ---------- 来源 tests/test_assistant_entry_901.py ----------
#   #901：OPPO / 一加 / realme 负一屏入口的手势加固与失败现场。
#   
#   两份脚本（PMX110 / PLZ110）的同一段实现在这里一起守：滑动起点让开 ColorOS 的左缘返回手势区、
#   已经在负一屏时不再滑走、认不到头像入口时留下停在哪个 Activity 与页面结构摘要。真机落点仍要另验。


RECIPES_901 = {
    "PMX110": ROOT / "recipes" / "oppo-PMX110" / "recipe.py",
    "PLZ110": ROOT / "recipes" / "oneplus-PLZ110" / "recipe.py",
}
LAUNCHER_901 = "com.android.launcher/com.android.launcher3.Launcher"
ASSISTANT_SETTING_901 = "com.coloros.assistantscreen/setting.RecommendServiceSettingActivity"
MARKET_SETTING_901 = "com.heytap.market/com.heytap.market.settings.SettingActivity"
HOME_901 = "input keyevent HOME"

ICON_PAGE_901 = '''<hierarchy>
  <node resource-id="com.coloros.assistantscreen:id/head_icon" clickable="true"
        bounds="[40,80][160,200]"/>
</hierarchy>'''
MARKET_PAGE_901 = '''<hierarchy>
  <node resource-id="com.heytap.market:id/head_icon" clickable="true"
        bounds="[900,80][1020,200]"/>
</hierarchy>'''
HOME_PAGE_901 = '''<hierarchy>
  <node text="桌面" bounds="[0,0][1080,120]"/>
  <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,300][1000,380]"/>
</hierarchy>'''


def page_901(xml):
    return ET.fromstring(xml)


def phone_901(**over):
    p = phone_mock(W=1080, H=2400)
    p.locked.return_value = False
    p.focus.return_value = LAUNCHER_901
    p.texts.return_value = []
    p.on_screen.return_value = True
    for key, value in over.items():
        setattr(p, key, value)
    return p


def shell_recorder_901(p, swipes, before=HOME_PAGE_901, after=ICON_PAGE_901, focus_before=LAUNCHER_901,
                   after_home=HOME_PAGE_901):
    """记下发过的 swipe；按 HOME / 滑动推进页面与前台，让第一次滑动就到达负一屏。"""
    state = {"front": focus_before, "home": False}

    def shell(cmd):
        if cmd.startswith("input keyevent HOME"):
            state["front"], state["home"] = LAUNCHER_901, True
        elif cmd.startswith("input swipe"):
            swipes.append(cmd)
        return SimpleNamespace(output="", exit_code=0)

    p.d.shell.side_effect = shell
    p.focus.side_effect = lambda: state["front"]
    p.tree.side_effect = lambda: page_901(after if swipes else after_home if state["home"] else before)


def commands_901(p):
    return [call.args[0] for call in p.d.shell.call_args_list]


def load_901(p, recipe):
    scope, _ = load_recipe(p, recipe)
    return scope


def action_901(scope, recipe, name):
    """取真实分段的函数体，以便给它的协作者注入替身；不复制分段实现。"""
    node = next(n for n in ast.parse(recipe.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.decorator_list
                and n.decorator_list[0].args[0].value == name)
    node.decorator_list, node.name = [], "selected_action"
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(recipe), "exec"), scope)
    return scope["selected_action"]


class AssistantEntryTests(unittest.TestCase):
    def test_swipe_starts_inside_the_left_edge_gesture_zone(self):
        """起点从 W//7 起：ColorOS 最左一条是返回 / 侧边栏手势区，8 落在里面。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                swipes = []
                shell_recorder_901(p, swipes)
                icon = load_901(p, recipe)["assistant_icon"]()
                self.assertEqual(icon.get("resource-id"),
                                 "com.coloros.assistantscreen:id/head_icon")
                self.assertEqual(swipes, [f"input swipe {1080 // 7} 1200 {1080 * 6 // 7} 1200 250"])
                self.assertGreater(1080 // 7, 8)

    def test_already_on_the_screen_skips_home_and_swipes(self):
        """已经在负一屏：不再按 HOME、不再右滑，否则把自己划走。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                p.tree.return_value = page_901(ICON_PAGE_901)
                load_901(p, recipe)["assistant_icon"]()
                self.assertEqual(commands_901(p), [])

    def test_assistant_settings_page_is_not_treated_as_arrived(self):
        """停在负一屏设置页：包名是它自己的，但不在首页，必须回桌面重进。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                swipes = []
                shell_recorder_901(p, swipes, focus_before=ASSISTANT_SETTING_901)
                load_901(p, recipe)["assistant_icon"]()
                self.assertEqual(commands_901(p)[:2], [HOME_901, HOME_901])
                self.assertEqual(swipes, [f"input swipe {1080 // 7} 1200 {1080 * 6 // 7} 1200 250"])

    def test_a_foreign_app_avatar_is_not_the_assistant_screen(self):
        """别的 App 上的同资源名头像不算到达：不按 HOME 就会在错的应用里点下去。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                swipes = []
                shell_recorder_901(p, swipes, before=MARKET_PAGE_901, focus_before=MARKET_SETTING_901)
                icon = load_901(p, recipe)["assistant_icon"]()
                self.assertEqual(commands_901(p)[:2], [HOME_901, HOME_901])
                self.assertEqual(icon.get("resource-id"), "com.coloros.assistantscreen:id/head_icon")

    def test_known_home_texts_are_enough_to_stop_swiping(self):
        """头像入口认不出但首页两条文案都在：停在原地报现场，不再一轮轮滑走。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                p.tree.return_value = page_901(HOME_PAGE_901)
                p.texts.return_value = [("我的服务", (0, 100, 300, 160), {}),
                                        ("添加卡片", (0, 200, 300, 260), {})]
                with self.assertRaisesRegex(RuntimeError, "未确认负一屏头像入口"):
                    load_901(p, recipe)["assistant_icon"]()
                self.assertEqual(commands_901(p), [])
                self.assertIn("唯一的负一屏头像入口", p.note_miss.call_args.args[0])

    def test_one_of_the_two_home_texts_is_not_enough(self):
        """只有一条文案的页面（如商店「我的」页）不当成负一屏：同族实测要求两条都在。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                p.texts.return_value = [("我的服务", (0, 100, 300, 160), {})]
                swipes = []
                shell_recorder_901(p, swipes)
                load_901(p, recipe)["assistant_icon"]()
                self.assertEqual(commands_901(p)[:2], [HOME_901, HOME_901])
                self.assertEqual(len(swipes), 1)

    def test_home_is_pressed_twice_when_another_app_is_in_front(self):
        """不在桌面：先两次 HOME 回默认桌面并等页面站稳，再滑；顺序不能反。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                swipes = []
                shell_recorder_901(p, swipes, focus_before="com.tencent.mm/.ui.LauncherUI")
                load_901(p, recipe)["assistant_icon"]()
                self.assertEqual(commands_901(p)[:2], [HOME_901, HOME_901])
                self.assertIn("input swipe", commands_901(p)[2])
                p.await_page.assert_any_call()

    def test_home_landing_on_the_screen_stops_before_swiping(self):
        """HOME 也可能正好落在负一屏（PLR110 实测）：到了就不再滑，否则把自己划走。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                swipes = []
                shell_recorder_901(p, swipes, after_home=ICON_PAGE_901)
                load_901(p, recipe)["assistant_icon"]()
                self.assertEqual(commands_901(p), [HOME_901])
                self.assertEqual(swipes, [])

    def test_swiping_stops_when_home_does_not_bring_the_desktop_back(self):
        """HOME 被吞掉时不能在别的 App 里连做右滑。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                p.focus.return_value = "com.tencent.mm/.ui.LauncherUI"
                p.tree.return_value = page_901(HOME_PAGE_901)
                with self.assertRaisesRegex(RuntimeError, "未停在系统桌面"):
                    load_901(p, recipe)["assistant_icon"]()
                self.assertFalse(any("input swipe" in c.args[0]
                                     for c in p.d.shell.call_args_list))

    def test_missing_entry_reports_where_the_swipe_stopped(self):
        """认不到头像入口：输出带上停在哪个 Activity 与页面结构摘要，文案保持不变。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                out = io.StringIO()
                p = fake_phone(size=(1080, 2340), stages=((0.0, HOME_PAGE_901),),
                               focus=((0.0, LAUNCHER_901),), await_page=lambda *a, **k: None,
                               say=lambda *a, **k: print(*a, file=out, flush=True))  # noqa: B023 - 当轮创建当轮消费，load() 同步执行
                with self.assertRaisesRegex(RuntimeError, "未确认负一屏头像入口"):
                    load_901(p, recipe)["assistant_icon"]()
                text = out.getvalue()
                self.assertIn("停在 com.android.launcher", text)
                self.assertIn("标题", text)
                self.assertIn("开关", text)
                self.assertIn("结构", text)
                self.assertIn("读到 0 个", text)

    def test_switches_after_the_entrance_are_unchanged(self):
        """头像入口在：点它进设置页，随后仍是「推荐服务」→「热点资讯」两步。"""
        for name, recipe in RECIPES_901.items():
            with self.subTest(name):
                p = phone_901()
                p.tree.return_value = page_901(ICON_PAGE_901)
                scope = load_901(p, recipe)
                for helper in ("row", "close_named", "open_page", "hide_carousel"):
                    scope[helper] = Mock()
                action_901(scope, recipe, "负一屏")()
                self.assertEqual([c.args[0] for c in scope["row"].call_args_list],
                                 ["设置", "推荐服务"])
                self.assertIn("InfoFlowSettingActivity", scope["open_page"].call_args.args[0])
                scope["close_named"].assert_called_once_with(["热点资讯"], "热点资讯")
                scope["hide_carousel"].assert_called_once_with()
                p.click.assert_called_once()
                self.assertEqual(commands_901(p), [])


# ---------- 来源 tests/test_browser_basic_mode_414.py、tests/test_browser_basic_mode_460.py ----------
#   #414 / #460：拒绝浏览器协议后落到基本模式设置页，浏览器段要说明原因并跳过。
#
#   REDMI K100（M786BC）上拒绝协议后进入 `BasicModeSettingActivity`，隐私和安全、主页、
#   搜索、功能设置都不在这一页；旧脚本照常找入口，43 秒后报「设置入口未找到」。#414 先只给了
#   xiaomi-M154FF 这条判定；#460 把同一判定铺到其余七份同款浏览器段（browser_settings()、
#   require(p.tap(...))、by_id 与 recipe_os4.py 的 monkey 拉起几种形状），一份都不能漏。

BASIC_460 = "com.android.browser/com.android.browser.basicmode.BasicModeSettingActivity"
HOME_460 = "com.android.browser/com.android.browser.MainActivity"
# 先试直达设置页、落空后才裸拉起首页的那两份（#667、#912）
FIRST_HOP = {
    "xiaomi-M154FF": ".preferences.activity.CustomizationPreferenceActivity",
    "xiaomi-24129PN74C": ".BrowserSettingsActivity",
}

RECIPES_460 = (
    (ROOT / "recipes/xiaomi-M154FF/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/xiaomi-25102RKBEC/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/redmi-25060RK16C/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/xiaomi-24129PN74C/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/redmi-23113RKC6C/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/xiaomi-2512BPNDAC/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/xiaomi-2505APX7BC/recipe.py", ("com.android.browser",)),
    # 这份不走 p.start：强停后用 monkey 拉起
    (ROOT / "recipes/xiaomi-24129PN74C/recipe_os4.py", None),
    (ROOT / "recipes/redmi-24122RKC7C/recipe.py", ("com.android.browser", ".BrowserActivity")),
)


class BrowserBasicModeTests(unittest.TestCase):
    def run_browser_step(self, recipe, focus):
        """只跑「浏览器」一段：点、返回、入口探测都是 Mock，记录调用。

        M154FF 的直达带 activity，基本模式下设置页被转走、落不到预期页（#414），所以让它抛错，
        脚本回退到裸拉起首页；其余脚本的直达失败由落点判据自己处理。"""
        def start(pkg, activity=None, **kw):
            if activity:
                raise RuntimeError("启动后停在非预期页面")

        p = phone_mock()
        if recipe.parent.name == "xiaomi-M154FF":
            p.start.side_effect = start
        p.locked = lambda: False
        p.focus.return_value = focus
        p.tree.return_value = fast.ET.fromstring('<hierarchy rotation="0"></hierarchy>')
        p.find.return_value = None
        p.texts.return_value = []
        _, out = load_recipe(p, recipe, ["浏览器"])
        return p, out.getvalue()

    def test_basic_mode_page_is_skipped_with_a_readable_reason(self):
        for recipe, start_args in RECIPES_460:
            with self.subTest(recipe=str(recipe)):
                p, out = self.run_browser_step(recipe, BASIC_460)
                if recipe.parent.name in FIRST_HOP and start_args:
                    # 先试直达、落空后才裸拉起首页：两次调用，顺序固定
                    self.assertEqual([c.args for c in p.start.call_args_list],
                                     [("com.android.browser", FIRST_HOP[recipe.parent.name]),
                                      start_args])
                elif start_args:
                    p.start.assert_called_once_with(*start_args)
                self.assertIn("== 浏览器", out)
                self.assertIn("基本模式", out)
                self.assertNotIn("出错", out)
                self.assertNotIn("未完成", out)
                p.click.assert_not_called()
                p.tap.assert_not_called()
                p.back.assert_not_called()
                p.entry.assert_not_called()

    def test_normal_home_page_still_goes_through_the_settings_entries(self):
        for recipe, start_args in RECIPES_460:
            with self.subTest(recipe=str(recipe)):
                p, out = self.run_browser_step(recipe, HOME_460)
                if recipe.parent.name == "xiaomi-M154FF":
                    self.assertEqual([c.args for c in p.start.call_args_list],
                                     [("com.android.browser", FIRST_HOP["xiaomi-M154FF"]),
                                      start_args])
                    self.assertIn("浏览器设置入口未找到", out)
                elif start_args and recipe.parent.name != "xiaomi-24129PN74C":
                    p.start.assert_called_once_with(*start_args)
                self.assertIn("== 浏览器", out)
                self.assertNotIn("基本模式", out)


# ---------- 来源 tests/test_browser_entry_331.py ----------
#   #331：进入设置页后页面还没画完就探测入口，五个入口整段误报「没找到」。
#   
#   Android 17 上设置页渲染更慢：点完齿轮 Activity 已经换了，读屏还是空白页。
#   入口探测要先等页面站稳再判定，找不到时留下能定位的结构，而不是只打一句「没找到」。


ENTRIES_331 = ["隐私和安全", "主页设置", "搜索设置", "功能设置", "网页浏览设置"]


def page_331(entries=ENTRIES_331, top="设置"):
    rows = "".join(
        f'<node class="android.widget.TextView" text="{t}" clickable="true" '
        f'bounds="[48,{320 + i * 120}][600,{420 + i * 120}]" />'
        for i, t in enumerate(entries))
    return f"""<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="{top}" bounds="[48,96][360,180]" />
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2340]">
      {rows}
      <node class="android.widget.Switch" text="个性化内容推荐" checkable="true" checked="true" bounds="[900,320][1020,420]" />
    </node>
  </node>
</hierarchy>"""


SETTINGS_PAGE_331 = page_331()
HALF_PAGE_331 = page_331(ENTRIES_331[:2])
OTHER_PAGE_331 = page_331(["别的页"])


class BrowserEntryTests(unittest.TestCase):
    def phone(self, stages, **fields):
        clock = Clock()
        clocked(self, fast, clock)
        return fake_phone(clock=clock, stages=stages, **fields), clock

    def test_entry_waits_for_settings_page_to_render(self):
        """空白页先出现、1 秒后才换成完整设置页：等页之后五个入口都该找得到。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (1.0, SETTINGS_PAGE_331)])
        for name in ENTRIES_331:
            self.assertTrue(p.entry(name), name)

    def test_entry_keeps_waiting_while_the_page_is_still_repainting(self):
        """页面一屏一屏往上长（每屏都比上一屏多）：不能停在中间那屏就去找入口。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (0.2, OTHER_PAGE_331), (0.4, HALF_PAGE_331),
                           (0.6, SETTINGS_PAGE_331)])
        self.assertTrue(p.entry("网页浏览设置"))

    def test_entry_retries_after_the_page_finishes_rendering(self):
        """第一轮只等到半画完的页面就去找、没找到；第二轮页面又画完一版，得能找回来。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (0.4, HALF_PAGE_331), (1.5, SETTINGS_PAGE_331)])
        self.assertTrue(p.entry("网页浏览设置", budget=2.4))

    def test_entry_gives_up_within_budget_when_page_never_renders(self):
        """页面始终空白时，等页预算耗尽就判失败，不会无限等。"""
        p, clock = self.phone([(0.0, EMPTY_PAGE)])
        self.assertFalse(p.entry("隐私和安全", budget=2.4))
        self.assertGreaterEqual(clock.t, 2.4)
        self.assertLess(clock.t, 3.0)

    def test_entry_keeps_the_section_from_going_off_path_after_a_miss(self):
        """可选入口 miss 不能把段级 miss 留在 1，否则后面的必需入口会被「快速放弃」。"""
        p, _ = self.phone([(0.0, SETTINGS_PAGE_331)])
        p.tap("不存在的必需入口", exact=True)
        self.assertGreater(p.miss, 0)
        self.assertFalse(p.entry("也不存在的入口"))
        self.assertEqual(p.miss, 0)

    def test_missing_entry_logs_activity_and_structure_without_page_text(self):
        """入口确实不存在时，日志要带 Activity 与结构摘要，且不打印页面文字。"""
        p, _ = self.phone([(0.0, SETTINGS_PAGE_331)])
        lines = []
        p.say = p.conn.say = lambda *a, **k: lines.append(" ".join(str(x) for x in a))
        p.screen.focus = lambda: "com.android.browser/.BrowserSettingsActivity"
        self.assertFalse(p.entry("不存在的入口"))
        log = "\n".join(lines)
        self.assertIn("BrowserSettingsActivity", log)
        self.assertIn("结构", log)
        self.assertIn("开关", log)
        for text in ENTRIES_331:
            self.assertNotIn(text, log)

    def test_note_miss_lets_a_dropped_connection_through(self):
        """诊断读不到页面时只该少一段摘要；断线是 RuntimeError，不能被当成「页面没认出来」吞掉。"""
        p, _ = self.phone([(0.0, SETTINGS_PAGE_331)])
        p.screen.focus = lambda: "com.android.browser/.BrowserSettingsActivity"

        def gone():
            raise RuntimeError("设备已断开")

        p.screen.tree = gone
        with self.assertRaisesRegex(RuntimeError, "设备已断开"):
            p.note_miss("不存在的入口")

    def test_note_miss_survives_an_unparsable_page(self):
        p, _ = self.phone([(0.0, SETTINGS_PAGE_331)])
        p.screen.focus = lambda: "com.android.browser/.BrowserSettingsActivity"
        lines = []
        p.say = p.conn.say = lambda *a, **k: lines.append(" ".join(str(x) for x in a))
        p.screen.tree = lambda: (_ for _ in ()).throw(fast.ET.ParseError("bad"))
        p.note_miss("不存在的入口")
        self.assertIn("页面结构读不到", "\n".join(lines))

    def test_in_settings_page_recognizes_the_settings_activity(self):
        p, _ = self.phone([(0.0, SETTINGS_PAGE_331)],
                          focus=((0.0, "com.android.browser/.BrowserSettingsActivity"),))
        self.assertTrue(p.in_settings_page())
        p.screen.focus = lambda: "com.android.browser/.MainActivity"
        self.assertFalse(p.in_settings_page())

    def test_browser_settings_rejects_a_gear_click_that_did_not_open_settings(self):
        """点完齿轮页面没换（点击被吞）：不能当成进了设置页，否则后面入口全打在旧页上。"""
        p = Mock(W=1080, H=2340)
        p.screen = p      # 机型脚本直接写 p.tree()，与观测基座用同一处桩
        p.screen.tree.return_value = fast.ET.fromstring(
            '<hierarchy><node text="设置" class="android.widget.ImageView" clickable="false" '
            'bounds="[900,100][1020,220]"/></hierarchy>')
        p.screen.on_screen.return_value = True
        p.screen.focus.return_value = "com.android.browser/.MainActivity"
        p.in_settings_page.return_value = False
        p.screen.texts.return_value = []
        scope, _ = load_recipe(p, ROOT / "recipes/xiaomi-M154FF/recipe.py")
        self.assertFalse(scope["browser_settings"]())
        p.back.assert_not_called()

    def test_row_summary_skips_offscreen_and_status_bar_nodes(self):
        """摘要只数屏内的节点：状态栏文字、折叠屏合上后的内屏残留都不算。"""
        xml = """<hierarchy rotation="0">
          <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2340]">
            <node class="android.widget.TextView" package="com.android.systemui" text="12:00" bounds="[48,24][180,72]" />
            <node class="android.widget.TextView" text="设置" bounds="[48,96][360,180]" />
            <node class="android.widget.TextView" text="内屏残留" bounds="[48,2600][360,2700]" />
            <node class="android.widget.Switch" checkable="true" bounds="[900,320][1020,420]" />
          </node>
        </hierarchy>"""
        out = row.summary(fast.ET.fromstring(xml), 1080, 2340)
        self.assertIn("标题 1 个", out)
        self.assertIn("开关 1 个", out)

    def test_row_summary_reports_counts_and_chain(self):
        root = fast.ET.fromstring(SETTINGS_PAGE_331)
        out = row.summary(root, 1080, 2340)
        self.assertIn("标题 1 个", out)
        self.assertIn("开关 1 个", out)
        self.assertIn("结构 ", out)

    def test_row_link_matches_channel_chain_format(self):
        """入口诊断与渠道「未确认」共用一份控件链渲染。"""
        root = fast.ET.fromstring(SETTINGS_PAGE_331)
        parents = {c: n for n in root.iter("node") for c in n}
        node = next(n for n in root.iter("node") if n.get("checkable") == "true")
        self.assertEqual(chan_fast.chain(node, parents), row.link(node, parents))


# ---------- 来源 tests/test_browser_settings_586.py ----------
#   #586：小米 / 红米浏览器段进设置页要校验落点。
#   
#   浏览器 20.30 在首页工具栏右上角还有一个叫「设置」的图标，底部「菜单」的弹窗还没画出来时
#   按文字点会落到它上面，进的是首页编辑面板；后面几页入口全部找不到，整段 0 项又不报错。
#   两条时间轴：落到工具栏面板时不点任何开关并报出停在哪一页；正常进设置页时照常走到目标行。


XIAOMI_586 = ROOT / "recipes/xiaomi-24129PN74C"
RECIPES_586 = ("recipe.py", "recipe_os4.py")
REDMI_K70_586 = ROOT / "recipes/redmi-23113RKC6C/recipe.py"
XIAOMI_17U_586 = ROOT / "recipes/xiaomi-2512BPNDAC/recipe.py"

BROWSER_586 = "com.android.browser/.BrowserActivity"
BROWSER_SETTINGS_586 = "com.android.browser/.BrowserSettingsActivity"
ADS_586 = call(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全")

# 首页：底部「菜单」标签 + 工具栏右上角那个也叫「设置」的图标（y≈144，点它是 #586 的错路）
HOME_586 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="设置" clickable="true" bounds="[960,96][1056,192]" />
    <node class="android.widget.TextView" text="主页" bounds="[0,2280][216,2400]" />
    <node class="android.widget.TextView" text="菜单" bounds="[432,2280][648,2400]" />
  </node>
</hierarchy>"""

# 点完「菜单」从底部升起的弹窗。两份「设置」卡在 0.3 屏高两侧（2400 屏上是 y=720）：
# 上面那份（top=700）是压在判据上的诱饵，只差 20 像素就会抢走点击，必须点不到。
POPUP_586 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="设置" clickable="true" bounds="[960,96][1056,192]" />
    <node class="android.widget.TextView" text="头像" bounds="[48,600][600,700]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[720,700][1020,760]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[720,730][1020,790]" />
  </node>
</hierarchy>"""

# 点到工具栏那个「设置」之后落的页：首页编辑面板，Activity 不是设置页
TOOLBAR_PANEL_586 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="页面布局" bounds="[48,300][600,400]" />
    <node class="android.widget.TextView" text="快捷网址" bounds="[48,420][600,520]" />
    <node class="android.widget.TextView" text="全网热榜" bounds="[48,540][600,640]" />
  </node>
</hierarchy>"""

SETTINGS_586 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="隐私和安全" clickable="true" bounds="[48,320][600,420]" />
    <node class="android.widget.TextView" text="搜索设置" clickable="true" bounds="[48,440][600,540]" />
  </node>
</hierarchy>"""

DECOY_SETTING_586 = (870, 730)           # top=700：在 0.3 屏高之上，不该被点到
POPUP_SETTING_586 = (870, 760)           # top=730：刚过 0.3 屏高，弹窗里那一行
TOOLBAR_SETTING_Y_586 = 144              # 工具栏图标的 y


def timeline_phone_586(case, stages, focus, clicked=None):
    """假手机 + 播放时间轴：一次点击/返回换一页，页面由时间轴决定。

    假钟经 `clocked()` 装入并登记还原（ADR-0033 的五个阶段各读一份 `time`）：只装不还，
    后面的用例会拿到这只钟，导航里「等 6 秒」那类循环就按残留时间跑。
    """
    clock = Clock(click_cost=2.0)
    clocked(case, fast, clock)
    p = fake_phone(clock=clock, size=(1080, 2400), stages=stages, focus=focus)
    if clicked is not None:
        stub(p, "click", lambda x, y: (clicked.append((x, y)), clock.click())[1])
    p.start = Mock(return_value=True)
    p.off = Mock()
    return p


class XiaomiBrowserSettingsTests(unittest.TestCase):
    def browser_step(self, p, recipe):
        scope, out = load_recipe(p, XIAOMI_586 / recipe, only="浏览器")
        return scope, out.getvalue()

    def test_lands_in_settings_page_and_walks_to_the_target_row(self):
        """正常路径：菜单 → 弹窗「设置」→ BrowserSettingsActivity，后面的行照常处理。"""
        expected = {
            # OS3 这份还要处理「显示猜你想搜模块」，也就是 #281 手动补上的那一项
            "recipe.py": [ADS_586, call(only=["显示猜你想搜模块"], page="浏览器·搜索设置")],
            "recipe_os4.py": [ADS_586],
        }
        for name in RECIPES_586:
            with self.subTest(recipe=name):
                p = timeline_phone_586(self, [(0.0, HOME_586), (1.0, POPUP_586), (3.0, SETTINGS_586)],
                                   focus=((0.0, BROWSER_586), (3.0, BROWSER_SETTINGS_586)))
                scope, _out = self.browser_step(p, name)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual(p.off.call_args_list, expected[name])

    def test_toolbar_panel_is_not_taken_for_the_settings_page(self):
        """落到工具栏面板时：不点任何开关、不在面板上找子页，报出停在哪一页。"""
        for name in RECIPES_586:
            with self.subTest(recipe=name):
                clicked = []
                p = timeline_phone_586(self, [(0.0, HOME_586), (1.0, POPUP_586), (3.0, TOOLBAR_PANEL_586),
                                    (5.0, HOME_586), (7.0, POPUP_586), (9.0, TOOLBAR_PANEL_586), (11.0, HOME_586)],
                                   focus=((0.0, BROWSER_586),), clicked=clicked)
                scope, out = self.browser_step(p, name)
                self.assertEqual(scope["FAILED_STEPS"], ["浏览器"])
                p.off.assert_not_called()
                self.assertIn("浏览器设置页没有打开", out)
                self.assertIn(BROWSER_586, out)
                # 两次都只点弹窗那一行：0.3 屏高之上的两份「设置」一次都没碰
                self.assertEqual(clicked.count(POPUP_SETTING_586), 2)
                self.assertNotIn(DECOY_SETTING_586, clicked)
                self.assertNotIn(TOOLBAR_SETTING_Y_586, [y for _x, y in clicked])


class RedmiBrowserSettingsTests(unittest.TestCase):
    def test_my_page_reaches_settings_and_retries_once(self):
        """K70 走「我的 → 设置」：第一次落空要退回来再点一次，第二次认出设置页就算成功。"""
        p = phone_mock()
        p.tap.return_value = True
        p.in_settings_page.side_effect = [False, True]
        scope, _ = load_recipe(p, REDMI_K70_586)
        scope["mine_settings"]()
        self.assertEqual(p.tap.call_args_list,
                         [call("我的", exact=True, scrolls=0), call("设置", exact=True, scrolls=0)] * 2)
        p.back.assert_called_once()

    def test_my_page_never_lands_reports_the_page_it_stopped_on(self):
        p = phone_mock()
        p.tap.return_value = True
        p.in_settings_page.return_value = False
        p.focus.return_value = BROWSER_586
        scope, _ = load_recipe(p, REDMI_K70_586)
        with self.assertRaisesRegex(RuntimeError, f"浏览器设置页没有打开；停在 {BROWSER_586}"):
            scope["mine_settings"]()
        self.assertEqual(p.back.call_count, 2)


class Xiaomi17UltraBrowserSettingsTests(unittest.TestCase):
    """2512BPNDAC 按 resource-id 点两个按钮，要点不到工具栏那个；落点仍要校验（#586）。"""

    PAGE = """<hierarchy rotation="0">
      <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
        <node class="android.widget.ImageView" resource-id="com.android.browser:id/action_more"
              clickable="true" bounds="[432,2280][648,2400]" />
        <node class="android.widget.TextView" resource-id="com.android.browser:id/action_menu_setting"
              clickable="true" bounds="[720,1100][1020,1200]" />
      </node>
    </hierarchy>"""

    def mock_phone(self, settings_after_click):
        p = phone_mock()
        p.tree.return_value = ET.fromstring(self.PAGE)
        p.focus.return_value = BROWSER_586
        p.in_settings_page.side_effect = settings_after_click
        return p

    def test_settings_page_is_reached(self):
        p = self.mock_phone([True])
        scope, _ = load_recipe(p, XIAOMI_17U_586)
        scope["menu_settings"]()
        self.assertEqual([c.args for c in p.click.call_args_list],
                         [(540, 2340), (870, 1150)])
        p.back.assert_not_called()

    def test_wrong_landing_retries_then_reports_the_page(self):
        p = self.mock_phone([False, False])
        scope, _ = load_recipe(p, XIAOMI_17U_586)
        with self.assertRaisesRegex(RuntimeError, "浏览器设置页没有打开"):
            scope["menu_settings"]()
        self.assertEqual(p.back.call_count, 2)


# ---------- 来源 tests/test_direct_entries_667.py ----------
#   #667：小米 M154FF、vivo V2547DA 的设置页能直达就直达，打不开才走菜单，断线不当成「这一档不通」。


XIAOMI_667 = ROOT / "recipes" / "xiaomi-M154FF" / "recipe.py"
VIVO_667 = ROOT / "recipes" / "vivo-V2547DA" / "recipe_android17.py"


def phone_667(start=None, lost=False):
    p = fixtures.phone_mock(lost=lost)
    p.locked.return_value = False
    p.focus.return_value = ""
    p.entry.return_value = False
    p.switches.return_value = []
    if start is not None:
        p.start.side_effect = start
    return p


def started_667(p):
    return [c.args[:2] if len(c.args) > 1 else c.args[:1] for c in p.start.call_args_list]


def expects_667(p):
    return [c.kwargs.get("expect") for c in p.start.call_args_list]


def shells_667(p):
    return [c.args[0] for c in p.d.shell.call_args_list]


def fail_direct_667(pkg, activity=None, **kw):
    if activity:
        raise RuntimeError("无法打开")


class XiaomiTest(unittest.TestCase):
    def run_step(self, name, p):
        return load_recipe(p, XIAOMI_667, only=name)

    def test_system_ads_goes_straight_to_the_page(self):
        p = phone_667()
        self.run_step("系统广告", p)
        self.assertEqual(started_667(p), [("com.android.settings", ".ad.AdServiceSettings")])
        self.assertEqual(expects_667(p), ["个性化广告推荐"])       # 落点判据要真的传下去
        p.off.assert_called_once_with(only=["个性化广告推荐"], page="系统·广告服务")
        self.assertFalse(any("android.settings.SETTINGS" in c for c in shells_667(p)))

    def test_system_ads_falls_back_to_the_menu(self):
        p = phone_667(fail_direct_667)
        self.run_step("系统广告", p)
        self.assertTrue(any("android.settings.SETTINGS" in c for c in shells_667(p)))
        self.assertEqual(p.entry.call_args_list[0].args[0], "隐私与安全")

    def test_lost_connection_does_not_walk_the_menu(self):
        """断线交还引擎、整轮停下，不逐段记台账（ADR-0029）；这里只守「不许改走菜单」。"""
        p = phone_667(adb_link.DeviceLost("断了"))
        with self.assertRaises(adb_link.DeviceLost):
            self.run_step("系统广告", p)
        self.assertEqual(shells_667(p), [])

    def test_lost_in_the_middle_does_not_look_like_an_unreachable_page(self):
        """读到一半断线时 Phone 只置 lost、抛的是普通 RuntimeError（#293、#667）：不能当成「这一页打不开」。"""
        p = phone_667()
        p.lost = True
        p.start.side_effect = RuntimeError("device offline")
        scope, _ = self.run_step("系统广告", p)
        self.assertEqual(shells_667(p), [])
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])

    def test_store_opens_settings_directly(self):
        p = phone_667()
        self.run_step("应用商店", p)
        self.assertEqual(started_667(p), [("com.xiaomi.market", ".ui.MarketPreferenceActivity")])
        self.assertEqual(expects_667(p), ["通知设置"])
        p.go.assert_not_called()

    def test_store_falls_back_to_my_page(self):
        p = phone_667(fail_direct_667)
        p.tree.return_value.iter.return_value = []
        p.find.return_value = None
        self.run_step("应用商店", p)
        self.assertEqual(started_667(p)[-1], ("com.xiaomi.market",))
        p.go.assert_called_once_with("我的", "设置")

    def test_downloads_goes_straight_to_the_feed_page(self):
        p = phone_667()
        self.run_step("下载管理", p)
        self.assertEqual(started_667(p), [("com.android.providers.downloads.ui", ".activity.InfoFlowSettingActivity")])
        self.assertEqual(expects_667(p), ["资源推荐"])
        p.off.assert_called_once_with(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")

    def test_browser_does_not_depend_on_the_home_page(self):
        # 后台屏上首页的工具栏和底栏认不出来，以前报「设置入口未找到」，这一段就失败了
        p = phone_667()
        p.tree.side_effect = AssertionError("直达时不该读浏览器首页找入口")
        scope, _ = self.run_step("浏览器", p)
        self.assertEqual(started_667(p), [("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity"),
                                      ("com.android.browser", ".BrowserSettingsActivity")])
        self.assertEqual(expects_667(p), ["个性化内容推荐", None])
        p.off.assert_called_once_with(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·个性化推荐")
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_browser_second_hop_does_not_fail_the_segment(self):
        """18 Fold 这类版本可能没有 .BrowserSettingsActivity：打不开只跳过子项，不让整段报未完成。"""
        def second_hop_missing(pkg, activity=None, **kw):
            if activity == ".BrowserSettingsActivity":
                raise RuntimeError("无法打开")

        p = phone_667(second_hop_missing)
        scope, out = self.run_step("浏览器", p)
        self.assertIn("直达不通", out.getvalue())
        p.off.assert_called_once_with(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·个性化推荐")
        # 只找过这三个子项，没有回头读首页或设置页找别的入口
        self.assertEqual([c.args[0] for c in p.entry.call_args_list], ["主页设置", "搜索设置", "功能设置"])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_browser_basic_mode_still_skips_on_the_menu_path(self):
        p = phone_667(fail_direct_667)
        p.focus.return_value = "com.android.browser/.basicmode.BasicModeSettingActivity"
        scope, out = self.run_step("浏览器", p)
        self.assertIn("基本模式", out.getvalue())
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_calendar_goes_straight_and_weather_keeps_its_menu(self):
        p = phone_667()
        p.find.return_value = None
        p.tree.return_value.iter.return_value = []
        self.run_step("天气和日历", p)
        self.assertEqual(started_667(p), [("com.miui.weather2",),
                                      ("com.android.calendar", ".settings.UserExperienceActionBarActivity")])
        self.assertEqual(expects_667(p), [None, "内容推广"])
        p.off.assert_called_once()
        self.assertEqual(p.off.call_args.kwargs["page"], "com.android.calendar·用户体验计划")


class VivoTest(unittest.TestCase):
    def run_step(self, name, p):
        return load_recipe(p, VIVO_667, only=name)

    def test_system_ads_passes_the_literal_activity(self):
        """页面名带 $：引用只在引擎的 shell 边界做一次（Phone._launch），脚本这层保持字面量。"""
        p = phone_667()
        self.run_step("系统广告", p)
        self.assertEqual(started_667(p), [("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo")])
        self.assertEqual(expects_667(p), ["智能推荐服务"])
        p.off.assert_called_once_with(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")

    def test_lost_in_the_middle_does_not_walk_the_menu(self):
        p = phone_667()
        p.lost = True
        p.start.side_effect = RuntimeError("device offline")
        scope, _ = self.run_step("系统广告", p)
        self.assertEqual(shells_667(p), [])
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])

    def test_system_ads_falls_back_to_the_menu(self):
        p = phone_667(fail_direct_667)
        self.run_step("系统广告", p)
        self.assertTrue(any("android.settings.SETTINGS" in c for c in shells_667(p)))

    def test_magazine_goes_straight_to_the_page(self):
        p = phone_667()
        self.run_step("阅图锁屏", p)
        self.assertEqual(started_667(p), [("com.vivo.magazine", ".ui.MagazineSettings")])
        self.assertEqual(expects_667(p), ["锁屏横滑进入阅图"])
        self.assertEqual(shells_667(p), [])

    def test_search_opens_settings_directly(self):
        p = phone_667()
        p.entry.side_effect = lambda name, scrolls=6: name == "首页展示内容"
        self.run_step("全局搜索", p)
        self.assertEqual(started_667(p), [("com.vivo.globalsearch", ".view.SearchSettingsActivity")])
        self.assertEqual(expects_667(p), ["首页展示内容"])
        self.assertEqual(shells_667(p), [])
        p.off.assert_called_once_with(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容")

    def test_search_stops_when_the_menu_has_no_entry(self):
        p = phone_667(fail_direct_667)
        self.run_step("全局搜索", p)
        p.off.assert_not_called()
        self.assertEqual([c.args[0] for c in p.entry.call_args_list], ["系统管理与升级"])

    def test_hot_search_row_is_closed_without_scrolling(self):
        p = phone_667()
        p.find.return_value = object()
        p.entry.side_effect = lambda name, scrolls=6: name in ("首页展示内容", "推荐热搜榜单")
        self.run_step("全局搜索", p)
        self.assertEqual([c.kwargs["page"] for c in p.off.call_args_list],
                         ["全局搜索·首页展示内容", "全局搜索·热搜榜单"])
        hot = [c for c in p.entry.call_args_list if c.args[0] == "推荐热搜榜单"]
        self.assertEqual(hot[0].kwargs["scrolls"], 0)      # 这一页只有几行，不滚（#667）

    def test_hot_search_row_is_not_searched_for_when_absent(self):
        p = phone_667()
        p.find.return_value = None
        p.entry.side_effect = lambda name, scrolls=6: name == "首页展示内容"
        self.run_step("全局搜索", p)
        self.assertFalse(any(c.args[0] == "推荐热搜榜单" for c in p.entry.call_args_list))


class RecipeQuotingTest(unittest.TestCase):
    """页面名的 shell 引用只在 Phone._launch 做一次。脚本里再 shlex.quote 会叠成两层，
    am 收到带字面引号的类名（#667 审查时 vivo V2417A 就是这么被弄坏的）。"""

    def test_no_recipe_quotes_the_page_name_before_start(self):
        offenders = []
        for path in sorted((ROOT / "recipes").glob("*/recipe*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not (isinstance(node.func, ast.Attribute) and node.func.attr == "start"):
                    continue
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) \
                            and arg.func.attr == "quote":
                        offenders.append(f"{path.relative_to(ROOT)}:{arg.lineno}")
        self.assertEqual(offenders, [], "页面名照字面量传，引用交给 Phone._launch")


class OpenDirectTest(unittest.TestCase):
    def test_activity_is_passed_to_phone_start_unquoted(self):
        """引用交给 Phone._launch；这一层保持字面量，used_by() 才认得出是哪台机在用（#667 审查）。"""
        p = fixtures.phone_mock()
        entries.open_direct(p, entries.Direct("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo"))
        self.assertEqual(p.start.call_args.args, ("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo"))

    def test_plain_activity_is_left_alone(self):
        p = fixtures.phone_mock()
        entries.open_direct(p, entries.Direct("com.android.settings", ".ad.AdServiceSettings"))
        self.assertEqual(p.start.call_args.args, ("com.android.settings", ".ad.AdServiceSettings"))


# ---------- 来源 tests/test_entry_hops_286.py ----------
#   OPPO Find X8s（PKT110）：换页的入口要确认页面真的换了，没换就重点；失败时报出停在哪一页（#286）。
#   
#   0.3.0 日志里主题商店「我的」→「设置」、视频「我的」→「设置」各只点一次；点击被关弹窗的淡出
#   动画吞掉后仍当成已经换页，下一步在旧页上找入口，整段以「未找到入口」结束。只补终点页面的
#   文字不够——「我的」点开后页面上本来就有「设置」，真正没发生的是换页。



def phone_286(taps=1):
    """真 `Phone`，只把读屏、点击、等页面换成可编排的替身。`taps` 次点击后 tap 返回 False。"""
    p = phone_stub("test", W=1080, H=2400)
    p.say = Mock()
    p.screen.sig = Mock(return_value="点击前的页面")
    stub(p, "page_text", Mock(return_value="主题 / 壁纸 / 字体"))
    stub(p, "find", Mock(return_value=(540, 2300)))
    rounds = {"left": taps}

    def tap(text, **kw):
        if rounds["left"] <= 0:
            return False
        rounds["left"] -= 1
        if kw.get("seen") is not None:
            kw["seen"].append("点击前的页面")
        return True

    stub(p, "tap", Mock(side_effect=tap))
    return p


def load_step_286(p, only):
    """按段名加载并执行：返回 (scope, 标准输出)。"""
    scope, out = load_recipe(p, ROOT / "recipes/oppo-PKT110/recipe.py", only)
    return scope, out.getvalue()


class EnterRetriesSwallowedTapTests(unittest.TestCase):
    def test_swallowed_first_tap_is_tapped_again(self):
        """第一次点完页面没换：enter 要再点一次，第二次换页后返回。"""
        p = phone_286(taps=2)
        p.screen.settle = Mock(side_effect=[False, True])
        p.enter("我的")
        self.assertEqual([c.args[0] for c in p.navigator.tap.call_args_list], ["我的", "我的"])

    def test_a_tap_that_lands_is_not_repeated(self):
        p = phone_286()
        p.screen.settle = Mock(return_value=True)
        p.enter("我的")
        p.navigator.tap.assert_called_once()
        self.assertEqual(p.navigator.tap.call_args.kwargs["scrolls"], 0)

    def test_page_that_never_changes_reports_the_page_it_stayed_on(self):
        p = phone_286(taps=3)
        p.screen.settle = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, "页面没有变化.*主题 / 壁纸 / 字体"):
            p.enter("我的")
        self.assertEqual(p.navigator.tap.call_count, 3)

    def test_missing_entry_is_reported_with_the_page_text(self):
        p = phone_286(taps=0)
        with self.assertRaisesRegex(RuntimeError, "未找到入口「我的」.*主题 / 壁纸 / 字体"):
            p.enter("我的")
        p.navigator.tap.assert_called_once()

    def test_change_is_measured_from_the_click_not_from_before_the_scroll(self):
        """入口要翻页才找得到：翻页也会改页面，基准要取点击那一刻，否则点被吞也判成功。"""
        p = phone_286()
        p.screen.sig = Mock(return_value="翻页前")
        rounds = {"left": 1}

        def tap(text, **kw):
            p.screen.sig.return_value = "翻到入口那一屏"
            kw["seen"].append(p.sig())
            rounds["left"] -= 1
            return True

        stub(p, "tap", Mock(side_effect=tap))
        p.screen.settle = Mock(return_value=True)
        p.enter("个性化管理", scrolls=6)
        p.screen.settle.assert_called_once_with("翻到入口那一屏", 2.0)

    def test_suffixed_bottom_tab_is_tapped_by_contains_match(self):
        """底栏常读作「我的，有新消息」：精确找不到时退回包含匹配，换页仍由页面变化判定。"""
        p = phone_286()
        p.screen.settle = Mock(return_value=True)
        stub(p, "find", Mock(side_effect=lambda text, **kw: (540, 2300) if not kw.get("exact") else None))
        p.enter("我的")
        self.assertIs(p.navigator.tap.call_args.kwargs["exact"], False)


class ThemeStoreStepTests(unittest.TestCase):
    pages = [
        [("消息通知", True, (1, 2)), ("开屏广告", True, (1, 3))],
        [("消息通知", False, (1, 2)), ("开屏广告", False, (1, 3))],
        [("个性化推荐设置", True, (1, 2))],
        [("个性化推荐设置", False, (1, 2))],
    ]

    def make(self):
        p = phone_mock()
        p.locked.return_value = False
        p.switches.side_effect = [list(page) for page in self.pages]
        return p

    def test_every_screen_change_in_the_theme_store_is_confirmed(self):
        p = self.make()
        scope, _ = load_step_286(p, ["主题商店"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual([c.args[0] for c in p.enter.call_args_list],
                         ["我的", "服务管理", "消息与广告",              # 主路径
                          "我的", "隐私",                             # to_privacy
                          "我的", "隐私"])                            # 确认后退回，回读前重进
        self.assertEqual(scope["VERIFIED_SWITCHES"], 3)

    def test_theme_store_falls_back_to_the_settings_gear_icon(self):
        """17.22 的「设置」是右上角没有文字的齿轮：文字找不到就用图标，并用设置页的内容确认（#286）。"""
        p = self.make()
        p.tap.side_effect = lambda text, **kw: text != "设置"
        p.tap_icon.return_value = True
        scope, _ = load_step_286(p, ["主题商店"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.tap_icon.assert_called_with(["服务管理", "隐私"])

    def test_theme_store_reports_when_neither_text_nor_icon_opens_settings(self):
        p = self.make()
        p.tap.side_effect = lambda text, **kw: text != "设置"
        p.tap_icon.return_value = False
        scope, out = load_step_286(p, ["主题商店"])
        self.assertEqual(scope["FAILED_STEPS"], ["主题商店"])
        self.assertIn("没找到「设置」入口", out)

    def test_theme_store_fails_when_a_hop_does_not_land(self):
        p = self.make()
        p.enter.side_effect = RuntimeError("点「设置」后页面没有变化；当前页：主题 / 壁纸")
        scope, out = load_step_286(p, ["主题商店"])
        self.assertEqual(scope["FAILED_STEPS"], ["主题商店"])
        self.assertIn("页面没有变化", out)


class VideoStepTests(unittest.TestCase):
    def make(self):
        p = phone_mock()
        p.locked.return_value = False
        p.switches.side_effect = [
            [("个性化广告推荐", True, (1, 2)), ("个性化内容推荐", True, (1, 3))],
            [("个性化广告推荐", False, (1, 2)), ("个性化内容推荐", False, (1, 3))],
        ]
        return p

    def test_video_confirms_the_tab_and_the_settings_page_before_the_row(self):
        p = self.make()
        scope, _ = load_step_286(p, ["视频"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(p.enter.call_args_list,
                         [call("我的"), call("设置"), call("个性化管理", scrolls=6)])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 2)


class PageTextTests(unittest.TestCase):
    def test_page_text_joins_the_visible_texts(self):
        p = phone_stub("test", W=1080, H=2400)
        p.screen.texts = Mock(return_value=[("我的", (0, 0, 1, 1), None), ("设置", (0, 2, 1, 3), None)])
        self.assertEqual(p.page_text(), "我的 / 设置")

    def test_page_text_is_empty_on_an_empty_page(self):
        p = phone_stub("test", W=1080, H=2400)
        p.screen.texts = Mock(return_value=[])
        self.assertEqual(p.page_text(), "")


# ---------- 来源 tests/test_gear_match_305.py ----------
#   HyperOS 机型脚本的 gear()：只认设置图标，不把正文/描述里含「设置」的干扰行当成入口（#305）。


# 干扰样本来自 #305 与 #374 的真机读数。
STORE_ROW_305 = ('<node class="android.widget.TextView" text="去功能设置里重新开启"'
             ' clickable="true" bounds="[0,600][1080,680]"/>')
THEME_TILE_305 = ('<node class="android.widget.ImageView" content-desc="设置壁纸"'
              ' clickable="true" bounds="[0,900][540,1200]"/>')
GEAR_ICON_305 = ('<node class="android.widget.ImageView" content-desc="设置"'
             ' clickable="true" bounds="[950,120][1040,210]"/>')
MORE_MENU_305 = ('<node class="android.widget.ImageView" content-desc="更多"'
             ' clickable="true" bounds="[980,120][1040,180]"/>')
TEXT_ENTRY_305 = ('<node class="android.widget.TextView" text="设置"'
              ' clickable="true" bounds="[100,900][300,980]"/>')
LOW_GEAR_305 = ('<node class="android.widget.ImageView" content-desc="设置"'
            ' clickable="true" bounds="[950,1500][1040,1590]"/>')
# 工具栏图标本身不可点、文字正好是「设置」：靠尺寸启发式命中（test_release_regressions 守同一类页面）。
TOOLBAR_TEXT_ICON_305 = ('<node class="android.widget.ImageView" text="设置"'
                     ' clickable="false" bounds="[900,100][1020,220]"/>')
# 齿轮的 id 形态：iv_setting 要认，securitySettingSwitchLayout 不认（后者是「应用安全检测」入口）。
ID_GEAR_305 = ('<node class="android.widget.ImageView" resource-id="com.android.market:id/iv_setting"'
           ' clickable="true" bounds="[950,120][1040,210]"/>')
ID_SECURITY_305 = ('<node class="android.widget.TextView"'
               ' resource-id="com.xiaomi.market:id/securitySettingSwitchLayout"'
               ' clickable="true" bounds="[0,1400][1080,1500]"/>')

GEAR_CENTER_305 = (995, 165)


def gear_users_1210():
    """注入面里真的用上齿轮的实现名（沿用 #1151 的「注入那份也算」口径）。

    判据走 `fixtures.normalize()`：`g["gear"]` 折回裸名、docstring 与注释都不剩，实现里提一句不算。"""
    return {name for name, source in recipe_source.injected_sources().items()
            if any((isinstance(node, ast.Name) and node.id == "gear")
                   or (isinstance(node, ast.FunctionDef) and node.name == "gear")
                   for node in ast.walk(ast.parse(fixtures.normalize(source))))}


def hyperos_recipes_305():
    """用了 gear() 的小米 / 红米机型脚本 —— 本地定义、注入助手与调用注入段体的都算（沿用 #1151 的口径）。

    段体搬进注入面之后脚本正文里只剩 `theme()` 这类一行调用，按正文找 `gear(` 会把它们漏掉：
    这一族用例照旧全绿，沿用 #305 的那批样本却再没有一条打到引擎那份实现。"""
    gear_users = gear_users_1210()
    for path in sorted(ROOT.glob("recipes/*/recipe*.py")):
        if not path.parent.name.startswith(("xiaomi-", "redmi-")):
            continue
        text = path.read_text(encoding="utf-8")
        if "gear(" in text or any(f"{name}(" in text for name in gear_users):
            yield path


def make_phone_305(nodes):
    p = phone_mock(W=1080, H=2400)
    p.tree.return_value = ET.fromstring(f"<hierarchy>{nodes}</hierarchy>")
    p.on_screen.return_value = True
    p.find.return_value = None
    p.tap.return_value = True
    return p


def call_gear_305(path, phone, **kwargs):
    scope, _ = load_recipe(phone, path)
    return scope["gear"](**kwargs)


class GearMatcherTests(unittest.TestCase):
    def each(self, nodes):
        return [(path, make_phone_305(nodes)) for path in hyperos_recipes_305()]

    def label(self, path):
        return f"{path.parent.name}/{path.stem}"

    def test_the_sample_set_still_covers_the_shared_gear(self):
        """样本按「用到 gear()」选，不按「本地定义」选（#1151）。

        搬进 `recipe_nav` 的六份脚本不再有本地 `def gear(`，按定义选样本时它们会静默掉出去，
        这一族用例照旧全绿 —— 引擎那份实现就再没有一条 #305 样本打到它。"""
        self.assertGreaterEqual(len(list(hyperos_recipes_305())), 15)

    def test_store_row_is_not_mistaken_for_settings(self):
        for path, phone in self.each(STORE_ROW_305 + GEAR_ICON_305):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_305(path, phone), "没找到真齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER_305)

    def test_theme_tile_is_not_mistaken_for_settings(self):
        for path, phone in self.each(THEME_TILE_305 + GEAR_ICON_305):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_305(path, phone), "没找到真齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER_305)

    def test_interference_row_alone_is_not_a_settings_entry(self):
        for path, phone in self.each(STORE_ROW_305):
            with self.subTest(recipe=self.label(path)):
                self.assertFalse(call_gear_305(path, phone), "把干扰行当成了设置入口")
                phone.click.assert_not_called()

    def test_security_switch_layout_id_is_not_a_settings_entry(self):
        for path, phone in self.each(ID_SECURITY_305):
            with self.subTest(recipe=self.label(path)):
                self.assertFalse(call_gear_305(path, phone), "把 securitySettingSwitchLayout 当成设置入口")
                phone.click.assert_not_called()

    def test_gear_identified_by_setting_word_in_its_id(self):
        for path, phone in self.each(ID_GEAR_305):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_305(path, phone), "没认出 iv_setting 形态的齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER_305)

    def test_more_menu_still_reaches_the_gear(self):
        for path, phone in self.each(MORE_MENU_305):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_305(path, phone), "没走通「更多」菜单")
                phone.tap.assert_called_with("设置", exact=True, scrolls=0)

    def test_text_settings_entry_still_reachable(self):
        for path, phone in self.each(TEXT_ENTRY_305):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_305(path, phone), "点不到文字「设置」")
                self.assertEqual(phone.click.call_args_list[0].args, (200, 940))

    def test_toolbar_text_icon_without_clickable_flag_still_opens_settings(self):
        for path, phone in self.each(TOOLBAR_TEXT_ICON_305):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_305(path, phone, toolbar_only=True), "没点到不可点的工具栏图标")
                self.assertEqual(phone.click.call_args_list[0].args, (960, 160))

    def test_toolbar_only_ignores_gear_below_the_toolbar(self):
        for path, phone in self.each(LOW_GEAR_305):
            with self.subTest(recipe=self.label(path)):
                self.assertFalse(call_gear_305(path, phone, toolbar_only=True),
                                 "在工具栏模式点了页面中部的齿轮")


# ---------- 来源 tests/test_icon_hit_530.py ----------
#   设置入口判据收进引擎（#530）：描述或正文恰好是「设置」，或 id 末段是 setting 词。
#   
#   原先 13 份小米 / 红米脚本各复制一份 `icon_hit`（#305 引入），vivo 参考脚本的 `gear()` 又是
#   另一套子串匹配。本文件分三层守：引擎谓词本身、13 份脚本不再各留副本、vivo `gear()` 在说明行
#   两种先后下都只点齿轮。



class IconHitTests(unittest.TestCase):
    def test_exact_desc_is_a_settings_entry(self):
        self.assertTrue(icon_hit({"content-desc": "设置"}))

    def test_exact_english_text_is_a_settings_entry(self):
        self.assertTrue(icon_hit({"text": "settings"}))

    def test_matching_is_case_insensitive(self):
        self.assertTrue(icon_hit({"text": "SETTINGS"}))

    def test_desc_with_extra_words_is_not_a_settings_entry(self):
        self.assertFalse(icon_hit({"content-desc": "设置壁纸"}))

    def test_body_text_containing_settings_is_not_a_settings_entry(self):
        self.assertFalse(icon_hit({"text": "去功能设置里重新开启"}))

    def test_id_starting_with_setting_is_a_settings_entry(self):
        self.assertTrue(icon_hit({"resource-id": "com.android.market:id/iv_setting"}))

    def test_setting_embedded_in_a_longer_id_segment_is_not_a_settings_entry(self):
        self.assertFalse(icon_hit(
            {"resource-id": "com.xiaomi.market:id/securitySettingSwitchLayout"}))

    def test_setting_suffix_segment_in_id_is_a_settings_entry(self):
        self.assertTrue(icon_hit({"resource-id": "com.vivo.appstore:id/gear_setting"}))

    def test_empty_node_is_not_a_settings_entry(self):
        self.assertFalse(icon_hit({}))

    def test_whitespace_around_the_label_is_ignored(self):
        self.assertTrue(icon_hit({"content-desc": "  设置  "}))


class ScriptsShareOnePredicateTests(unittest.TestCase):
    """13 份小米 / 红米脚本不再各留一份 icon_hit，改用引擎这一份（#530）。"""

    def test_no_recipe_defines_its_own_icon_hit(self):
        offenders = []
        for path in sorted(ROOT.glob("recipes/*/recipe*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "icon_hit":
                    offenders.append(f"{path.parent.name}/{path.name}:{node.lineno}")
        self.assertEqual(offenders, [], "脚本里还留着 icon_hit 的本地副本")


VIVO_RECIPES_530 = (ROOT / "recipes/vivo-V2547DA/recipe.py",
                ROOT / "recipes/vivo-V2547DA/recipe_android17.py")


def calls_on_p_530(tree, method):
    """`p.<method>(...)` 调用点。"""
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == method
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "p"]


class VivoStoreEntryTests(unittest.TestCase):
    """vivo 参考脚本的商店段改用引擎入口，不再按精确文字点底栏（#530）。"""

    def test_store_section_uses_the_bottom_tab_helper(self):
        for path in VIVO_RECIPES_530:
            with self.subTest(recipe=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = [a.value for call in calls_on_p_530(tree, "tab")
                         for a in call.args if isinstance(a, ast.Constant)]
                self.assertIn("我的", names, "商店段没改用 p.tab(\"我的\")")


# 齿轮与两种说明行：正文版来自 #305 的小米样本，description 版才是 vivo 旧子串匹配真正会误点的形状。
GEAR_530 = ('<node class="android.widget.ImageView" content-desc="设置" clickable="true"'
        ' bounds="[950,120][1040,210]"/>')
GEAR_CENTER_530 = (995, 165)
TEXT_DECOY_530 = ('<node class="android.widget.TextView" text="去功能设置里重新开启" clickable="true"'
              ' bounds="[0,600][1080,680]"/>')
DESC_DECOY_530 = ('<node class="android.widget.TextView" content-desc="去功能设置里重新开启"'
              ' clickable="true" bounds="[0,900][1080,980]"/>')
SETTINGS_530 = "com.bbk.appstore/.ui.menu.AppstoreSettingsActivity"
# 看起来像图标但没勾 clickable：旧实现漏掉，新实现按尺寸启发式认。
UNCLICKABLE_GEAR_530 = ('<node class="android.widget.ImageView" content-desc="设置" clickable="false"'
                    ' bounds="[900,100][1020,220]"/>')


def make_phone_530(nodes):
    p = phone_mock(W=1080, H=2400)
    p.tree.return_value = ET.fromstring(f"<hierarchy>{nodes}</hierarchy>")
    p.on_screen.return_value = True
    p.tap.return_value = False
    # 点完才进商店设置页：gear() 要求页面确实换了才算命中（#575）
    p.focus.side_effect = lambda: (SETTINGS_530 if p.click.called
                                   else "com.bbk.appstore/.MainActivity")
    p.in_settings_page.side_effect = lambda: bool(p.click.called)
    return p


def call_gear_530(path, phone):
    scope, _ = load_recipe(phone, path)
    return scope["gear"]()


class VivoGearTests(unittest.TestCase):
    """vivo 参考脚本的 gear() 用引擎判据：说明行与齿轮并存时，两种先后都只点齿轮（#530）。

    vivo 旧实现按 content-desc / resource-id 子串匹配，把说明行排在前就会点它；收窄成精确判据
    后必须两种顺序都只点齿轮，这是这次唯一的行为变化，没有真机，只能靠合成页面守。
    """

    def each(self, nodes):
        return [(path, make_phone_530(nodes)) for path in VIVO_RECIPES_530]

    def label(self, path):
        return path.name

    def test_text_decoy_before_the_gear_is_not_clicked(self):
        for path, phone in self.each(TEXT_DECOY_530 + GEAR_530):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_530(path, phone), "没找到真齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER_530)

    def test_text_decoy_after_the_gear_is_not_clicked(self):
        for path, phone in self.each(GEAR_530 + TEXT_DECOY_530):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_530(path, phone), "没找到真齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER_530)

    def test_desc_decoy_alone_is_not_a_settings_entry(self):
        for path, phone in self.each(DESC_DECOY_530):
            with self.subTest(recipe=self.label(path)):
                self.assertFalse(call_gear_530(path, phone), "把说明行当成了设置入口")
                phone.click.assert_not_called()

    def test_unclickable_icon_sized_gear_is_clicked(self):
        for path, phone in self.each(UNCLICKABLE_GEAR_530):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear_530(path, phone), "没点到不可点的齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, (960, 160))


# ---------- 来源 tests/test_recipe_fast_entries_796.py ----------
#   #796：慢脚本改走直达。PNM-AN10 三段与 PLR110 下拉搜索不再靠桌面手势逐层点菜单。
#   
#   守的是「入口换了」这个可观察行为：拉起的是哪个 Activity、有没有再按 HOME / 滑动、
#   直达不通时退回了原路径、断线不被吞成「入口改名」。真机上的落点仍要另验。


PNM_796 = ROOT / "recipes" / "honor-PNM-AN10" / "recipe.py"
PLR_796 = ROOT / "recipes" / "oneplus-PLR110" / "recipe.py"

HIBOARD_START_796 = "am start -f 0x10008000 -n com.hihonor.hiboard/com.hihonor.intelligent.LauncherActivity"
SEARCH_SETTING_796 = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"


def phone_796(**over):
    p = phone_mock(W=1080, H=2400)
    p.locked.return_value = False
    p.focus.return_value = ""
    p.find.return_value = None
    p.tap.return_value = True
    p.texts.return_value = []
    p.setting.return_value = True
    for key, value in over.items():
        setattr(p, key, value)
    return p


def load_796(p, recipe, name):
    scope, out = load_recipe(p, recipe, only=name)
    return scope, out.getvalue()


def page_texts_796(*labels, top=100):
    return [(label, (0, top, 100, top + 40), {}) for label in labels]


def home_presses_796(p):
    """按 HOME 的次数：shell 与 `d.press` 两条路都算。"""
    return ([c.args[0] for c in p.d.shell.call_args_list if "keyevent HOME" in c.args[0]]
            + [c.args[0] for c in p.d.press.call_args_list if c.args[0] == "home"])


def landing_failed_796(pkg, activity=None, **kw):
    """只有直达广告与隐私页这一条失败，同段后面拉智能推荐服务页照常。"""
    if activity == ".oaid.ui.AdvertisingPrivacyActivity":
        raise RuntimeError("启动后停在非预期页面")


class PnmSearchEntryTests(unittest.TestCase):
    def test_search_opens_the_search_home_directly(self):
        """直达搜索首页：「更多」在屏上时直接点，不再按 HOME 再下拉。"""
        p = phone_796(texts=lambda: page_texts_796("更多", top=int(2400 * 0.5)))
        scope, _ = load_796(p, PNM_796, "搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.start.assert_called_once_with(
            "com.hihonor.search", ".feature.mainpage.presentation.page.HomeActivity", expect="更多")
        self.assertEqual(home_presses_796(p), [])
        p.click.assert_called_once()

    def test_missing_more_entry_fails_instead_of_finishing_quietly(self):
        """「更多」始终找不到：记成未完成，不再当成跑完。"""
        p = phone_796()
        scope, out = load_796(p, PNM_796, "搜索")
        self.assertEqual(scope["FAILED_STEPS"], ["搜索"])
        self.assertIn("找不到搜索框旁的「更多」", out)


class PnmNegativeScreenEntryTests(unittest.TestCase):
    def test_negative_screen_opens_the_hiboard_activity(self):
        """负一屏直达：一次 am start 就够，不再先回桌面再右滑。"""
        p = phone_796(find=lambda text, **kw: object() if text == "头像" else None)
        scope, _ = load_796(p, PNM_796, "负一屏")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(p.d.shell.call_args_list[0].args[0], HIBOARD_START_796)
        self.assertEqual(home_presses_796(p), [])
        self.assertEqual(len(p.d.shell.call_args_list), 1)
        p.tap.assert_any_call("头像", exact=True, scrolls=0)

    def test_negative_screen_falls_back_to_the_swipe_when_the_activity_does_not_land(self):
        """直达没落到负一屏（后台屏上进不去）：退回桌面右滑，仍找不到才算失败。"""
        p = phone_796()
        scope, out = load_796(p, PNM_796, "负一屏")
        self.assertEqual(scope["FAILED_STEPS"], ["负一屏"])
        self.assertIn("负一屏没打开", out)
        self.assertEqual(p.d.shell.call_args_list[0].args[0], HIBOARD_START_796)
        self.assertEqual(len(home_presses_796(p)), 1)
        self.assertTrue(any("input swipe" in c.args[0] for c in p.d.shell.call_args_list))


class PnmAdTrackingEntryTests(unittest.TestCase):
    def test_ad_tracking_opens_the_privacy_activity_directly(self):
        """直达广告与隐私页：不再先搜设置、也不点三层菜单。"""
        p = phone_796()
        scope, _ = load_796(p, PNM_796, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.start.assert_any_call(
            "com.hihonor.id", ".oaid.ui.AdvertisingPrivacyActivity", expect="应用广告跟踪管理")
        p.setting.assert_not_called()

    def test_ad_tracking_falls_back_to_the_settings_search(self):
        """直达打不开（页面没导出 / 落点不对）：退回设置搜索，不让整段失败。"""
        p = phone_796()
        p.start.side_effect = landing_failed_796
        scope, _ = load_796(p, PNM_796, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.start.assert_any_call(
            "com.hihonor.id", ".oaid.ui.AdvertisingPrivacyActivity", expect="应用广告跟踪管理")
        p.setting.assert_called_once_with("广告", "广告与隐私")

    def test_ad_tracking_does_not_swallow_a_lost_connection(self):
        """断线不是「这一档不通」：不许当成入口改名去走设置搜索。

        段包装把 `DeviceLost` 交还引擎，整轮停下、退出码 1；不逐段记台账（ADR-0029）。"""
        p = phone_796()
        p.start.side_effect = adb_link.DeviceLost("adb 断了")
        with self.assertRaises(adb_link.DeviceLost):
            load_796(p, PNM_796, "广告跟踪")
        p.setting.assert_not_called()

    def test_ad_tracking_does_not_swallow_a_locked_screen(self):
        """锁屏同理：上抛给上层停段，不静默换入口。"""
        p = phone_796()
        p.start.side_effect = ScreenLocked("手机锁屏")
        scope, _ = load_796(p, PNM_796, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], ["广告跟踪"])
        p.setting.assert_not_called()


class PlrSearchEntryTests(unittest.TestCase):
    def test_pull_down_search_lands_on_the_settings_page_via_the_scheme(self):
        """PLR110：scheme 直接落到设置页，不再按 HOME、左滑躲速览、下拉、收键盘、点底部「设置」。"""
        p = phone_796(focus=lambda: "com.heytap.quicksearchbox/.ui.activity.SearchSettingActivity",
                  texts=lambda: page_texts_796("搜索范围"))
        scope, _ = load_796(p, PLR_796, "下拉搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(p.d.shell.call_args_list[0].args[0], SEARCH_SETTING_796)
        self.assertEqual(home_presses_796(p), [])
        self.assertFalse(any("input swipe" in c.args[0] for c in p.d.shell.call_args_list))
        p.tap.assert_any_call("搜索范围", exact=True)

    def test_pull_down_search_falls_back_to_the_desktop_gesture(self):
        """scheme 打不开：退回桌面下拉点底部「设置」，两步都不通才记未完成。"""
        p = phone_796(focus=lambda: "com.android.launcher/.Launcher")
        scope, out = load_796(p, PLR_796, "下拉搜索")
        self.assertEqual(scope["FAILED_STEPS"], ["下拉搜索"])
        self.assertIn("下拉没进全局搜索", out)
        self.assertIn("没进全局搜索设置页", out)
        self.assertEqual(p.d.shell.call_args_list[0].args[0], SEARCH_SETTING_796)
        self.assertEqual(len(home_presses_796(p)), 1)
        self.assertTrue(any("input swipe" in c.args[0] for c in p.d.shell.call_args_list))


# ---------- 来源 tests/test_store_privacy_933.py ----------
#   #933：OPPO / 一加 / realme 五支脚本的软件商店隐私入口。
#   
#   商店 App 独立升级，设置页那一行在有的版本里叫「隐私」，有的叫「隐私授权管理」；#907 只改了
#   PMX110 / PLZ110，这五支仍写死单一文案，认不到就是整段 0 项或整段失败。这里一次守住五支：
#   两种文案都认、「隐私」优先、点进去按落点页面判、认不到时留下停在哪个页面与结构摘要。
#   真机落点仍要另验。


PRIVACY_933 = ("隐私", "隐私授权管理")
MARKET_933 = "com.heytap.market/com.heytap.market.mine.cn.setting.ui."
PRIVACY_PAGE_933 = MARKET_933 + "PrivacyActivity"
RECIPES_933 = {
    "PLG110": ROOT / "recipes/oppo-PLG110/recipe.py",
    "PMA110": ROOT / "recipes/oppo-PMA110/recipe.py",
    "PKX110": ROOT / "recipes/oneplus-PKX110/recipe.py",
    "RMX3700": ROOT / "recipes/realme-RMX3700/recipe.py",
    "PHK110": ROOT / "recipes/oneplus-PHK110/recipe_android15.py",
}


def load_933(phone, recipe):
    scope, _ = load_recipe(phone, recipe)
    return scope


def action_933(scope, recipe, name):
    """取真实分段的函数体，以便给它的协作者注入替身；不复制分段实现。"""
    node = next(n for n in ast.parse(recipe.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.decorator_list
                and n.decorator_list[0].args[0].value == name)
    node.decorator_list, node.name = [], "selected_action"
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(recipe), "exec"), scope)
    return scope["selected_action"]


def tapping_phone_933(present):
    """只在 `present` 里的文案点得动的假手机。"""
    p = phone_mock(W=1080, H=2340)
    p.locked.return_value = False
    p.tap.side_effect = lambda text, **kwargs: text in present
    return p


def segment_phone_933():
    """商店段自己的点击（「我的」→「设置」这些）一律成功，只让入口方法被断言。"""
    p = phone_mock(W=1080, H=2340)
    p.locked.return_value = False
    p.tap.return_value = True
    return p


def store_page_933(title):
    """停在商店隐私页：标题按本机商店版本叫「隐私」或「隐私授权管理」，页上没有开关。"""
    p = phone_mock(W=1080, H=2340)
    p.locked.return_value = False
    p.focus.return_value = PRIVACY_PAGE_933
    p.tree.return_value = ET.fromstring(
        f'<hierarchy><node text="{title}" bounds="[0,0][1080,150]"/></hierarchy>')
    p.texts.return_value = [(title, (40, 40), {})]
    p.switches.return_value = []
    return p


class TapPageEntryTests(unittest.TestCase):
    """PLG110 与 PMA110 的 `tap_page(text, activity, title=None, scrolls=4)`。"""

    RECIPES = {name: RECIPES_933[name] for name in ("PLG110", "PMA110")}

    def entry(self, recipe, present):
        p = tapping_phone_933(present)
        scope = load_933(p, recipe)
        scope["wait_page"] = Mock()
        return p, scope

    def test_each_wording_opens_the_store_privacy_page(self):
        for name, recipe in self.RECIPES.items():
            for wording in PRIVACY_933:
                with self.subTest(recipe=name, wording=wording):
                    p, scope = self.entry(recipe, {wording})
                    scope["tap_page"](PRIVACY_933, PRIVACY_PAGE_933, scrolls=8)
                    scope["wait_page"].assert_called_once_with(PRIVACY_PAGE_933, wording)
                    p.note_miss.assert_not_called()

    def test_privacy_wording_wins_when_both_are_on_the_page(self):
        for name, recipe in self.RECIPES.items():
            with self.subTest(name):
                p, scope = self.entry(recipe, set(PRIVACY_933))
                scope["tap_page"](PRIVACY_933, PRIVACY_PAGE_933, scrolls=8)
                self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["隐私"])

    def test_neither_wording_keeps_the_page_scene_and_the_sentence(self):
        for name, recipe in self.RECIPES.items():
            with self.subTest(name):
                p, scope = self.entry(recipe, set())
                with self.assertRaisesRegex(RuntimeError, "未找到入口「隐私」"):
                    scope["tap_page"](PRIVACY_933, PRIVACY_PAGE_933, scrolls=8)
                p.note_miss.assert_called_once_with("隐私 / 隐私授权管理")
                scope["wait_page"].assert_not_called()

    def test_a_single_name_still_works_and_keeps_the_old_message(self):
        """这两份脚本的其余十来处入口仍是单字面量，行为与失败句不能跟着变。"""
        for name, recipe in self.RECIPES.items():
            with self.subTest(name):
                p, scope = self.entry(recipe, {"搜索范围"})
                scope["tap_page"]("搜索范围", MARKET_933 + "ServeManagerActivity")
                scope["wait_page"].assert_called_once_with(MARKET_933 + "ServeManagerActivity", "搜索范围")
                p.tap.assert_called_once_with("搜索范围", exact=True, scrolls=4, quiet=False)

                p, scope = self.entry(recipe, set())
                with self.assertRaisesRegex(RuntimeError, "未找到入口「搜索范围」"):
                    scope["tap_page"]("搜索范围", MARKET_933 + "ServeManagerActivity")
                p.note_miss.assert_called_once_with("搜索范围")


class Pkx110EntryTests(unittest.TestCase):
    def entry(self, present):
        p = tapping_phone_933(present)
        scope = load_933(p, RECIPES_933["PKX110"])
        scope["wait_page"] = Mock(return_value=True)
        return p, scope

    def test_each_wording_opens_the_store_privacy_page(self):
        for wording in PRIVACY_933:
            with self.subTest(wording):
                p, scope = self.entry({wording})
                self.assertTrue(scope["tap_page"](PRIVACY_933, PRIVACY_PAGE_933, PRIVACY_933))
                scope["wait_page"].assert_called_once_with(PRIVACY_PAGE_933, PRIVACY_933)
                p.note_miss.assert_not_called()

    def test_privacy_wording_wins_when_both_are_on_the_page(self):
        p, scope = self.entry(set(PRIVACY_933))
        scope["tap_page"](PRIVACY_933, PRIVACY_PAGE_933, PRIVACY_933)
        self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["隐私"])

    def test_neither_wording_keeps_the_page_scene(self):
        p, scope = self.entry(set())
        self.assertFalse(scope["tap_page"](PRIVACY_933, PRIVACY_PAGE_933, PRIVACY_933))
        p.note_miss.assert_called_once_with("隐私 / 隐私授权管理")
        scope["wait_page"].assert_not_called()

    def test_page_title_accepts_either_wording(self):
        for wording in PRIVACY_933:
            with self.subTest(wording):
                scope = load_933(store_page_933(wording), RECIPES_933["PKX110"])
                self.assertTrue(scope["wait_page"]("PrivacyActivity", PRIVACY_933))

    def test_failed_landing_is_not_retried_on_the_next_wording(self):
        """点开了但没落到隐私页：就此停段，不在别的页面上再点一次同名行。"""
        p, scope = self.entry(set(PRIVACY_933))
        scope["wait_page"] = Mock(return_value=False)
        self.assertFalse(scope["tap_page"](PRIVACY_933, PRIVACY_PAGE_933, PRIVACY_933))
        p.tap.assert_called_once_with("隐私", exact=True, quiet=True)


class Phk110EntryTests(unittest.TestCase):
    def entry(self, present):
        p = tapping_phone_933(present)
        scope = load_933(p, RECIPES_933["PHK110"])
        scope["page"] = Mock(return_value=True)
        return p, scope

    def test_each_wording_opens_the_store_privacy_page(self):
        for wording in PRIVACY_933:
            with self.subTest(wording):
                p, scope = self.entry({wording})
                self.assertTrue(scope["navigate"](PRIVACY_933, "PrivacyActivity", PRIVACY_933))
                scope["page"].assert_called_once_with("PrivacyActivity", PRIVACY_933)
                p.note_miss.assert_not_called()

    def test_privacy_wording_wins_when_both_are_on_the_page(self):
        p, scope = self.entry(set(PRIVACY_933))
        scope["navigate"](PRIVACY_933, "PrivacyActivity", PRIVACY_933)
        self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["隐私"])

    def test_neither_wording_keeps_the_page_scene(self):
        p, scope = self.entry(set())
        self.assertFalse(scope["navigate"](PRIVACY_933, "PrivacyActivity", PRIVACY_933))
        p.note_miss.assert_called_once_with("隐私 / 隐私授权管理")
        scope["page"].assert_not_called()

    def test_page_title_accepts_either_wording(self):
        for wording in PRIVACY_933:
            with self.subTest(wording):
                scope = load_933(store_page_933(wording), RECIPES_933["PHK110"])
                self.assertTrue(scope["page"]("PrivacyActivity", PRIVACY_933))


class Rmx3700EntryTests(unittest.TestCase):
    def test_tap_by_scroll_tries_both_wordings(self):
        for wording in PRIVACY_933:
            with self.subTest(wording):
                p = phone_mock(W=1080, H=2340)
                p.find.side_effect = lambda text, exact=False: text == wording  # noqa: B023 - 当轮创建当轮消费，tap_by_scroll 同步调用
                scope = load_933(p, RECIPES_933["RMX3700"])
                self.assertTrue(scope["tap_by_scroll"](PRIVACY_933))
                p.tap.assert_called_once_with(wording, exact=True, scrolls=0)

    def test_privacy_wording_is_tried_first(self):
        p = phone_mock(W=1080, H=2340)
        p.find.return_value = True
        scope = load_933(p, RECIPES_933["RMX3700"])
        scope["tap_by_scroll"](PRIVACY_933)
        self.assertEqual(p.find.call_args_list[0].args[0], "隐私")

    def test_neither_wording_ends_the_scroll(self):
        p = phone_mock(W=1080, H=2340)
        p.find.return_value = False
        p.scroll_more.return_value = False
        scope = load_933(p, RECIPES_933["RMX3700"])
        self.assertFalse(scope["tap_by_scroll"](PRIVACY_933))
        p.tap.assert_not_called()
        p.scroll_more.assert_called_once_with()

    def test_page_title_accepts_either_wording(self):
        for wording in PRIVACY_933:
            with self.subTest(wording):
                scope = load_933(store_page_933(wording), RECIPES_933["RMX3700"])
                self.assertTrue(scope["wait_page"]("PrivacyActivity", PRIVACY_933))


class StoreSegmentTests(unittest.TestCase):
    """商店段把两种文案一起交给本脚本的入口方法 —— 撤掉实现这几条就红。"""

    def segment(self, name, step, **stubs):
        scope = load_933(segment_phone_933(), RECIPES_933[name])
        for helper, value in stubs.items():
            scope[helper] = Mock(return_value=value)
        action_933(scope, RECIPES_933[name], step)()
        return scope

    def test_plg110_passes_both_wording(self):
        scope = self.segment("PLG110", "软件商店",
                             app_settings=None, tap_page=None, close_named=None, read_switches={})
        self.assertEqual(scope["tap_page"].call_args_list[0].args[0], PRIVACY_933)

    def test_pma110_passes_both_wording(self):
        scope = self.segment("PMA110", "软件商店", app_settings=None, tap_page=None, close_named=None)
        self.assertEqual(scope["tap_page"].call_args_list[0].args[0], PRIVACY_933)

    def test_pkx110_passes_both_wording(self):
        scope = self.segment("PKX110", "软件商店·个性化",
                             open_app_settings=True, tap_page=True, off_exact=True)
        self.assertEqual(scope["tap_page"].call_args_list[0].args[0], PRIVACY_933)

    def test_rmx3700_passes_both_wording(self):
        scope = self.segment("RMX3700", "软件商店", tap_by_scroll=True, wait_page=True)
        self.assertIn(PRIVACY_933, [c.args[0] for c in scope["tap_by_scroll"].call_args_list])

    def test_phk110_passes_both_wording(self):
        scope = self.segment("PHK110", "软件商店个性化",
                             open_settings=True, navigate=True, off_exact=True)
        self.assertEqual(scope["navigate"].call_args_list[0].args[0], PRIVACY_933)

    def test_rmx3700_missing_row_keeps_the_original_line_and_the_scene(self):
        p = segment_phone_933()
        scope = load_933(p, RECIPES_933["RMX3700"])
        scope["tap_by_scroll"] = Mock(return_value=False)
        scope["wait_page"] = Mock(return_value=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            action_933(scope, RECIPES_933["RMX3700"], "软件商店")()
        self.assertIn("没找到「隐私授权管理」", out.getvalue())
        p.note_miss.assert_called_once_with("隐私 / 隐私授权管理")


# ---------- 来源 tests/test_theme_browser_entry_912.py ----------
#   #912：浏览器段直达优先，主题段用底栏 tab 进「我的」。
#   
#   报告者那台 Xiaomi 15 Pro（2410DPN6CC）两条入口都断在同一处：入口靠 `gear()` 读一次界面树、
#   点一次图标，没有等待也没有第二入口。反过来，浏览器设置页有导出，`am start -n
#   com.android.browser/.BrowserSettingsActivity` 实测能直接落过去；主题「我的」在底栏只有
#   content-desc（读作「未选中,我的」），而内容区还有「我的点赞 / 我的收藏 / 我的订单」。
#   
#   三条行为各一组用例：直达成功；直达落空按「菜单」→「我的」回退；主题 tab 命中的是底栏。
#   页面节点取自报告者贴的 dump（1080×2400）。


RECIPE_912 = ROOT / "recipes/xiaomi-24129PN74C/recipe.py"
BROWSER_HOME_912 = "com.android.browser/com.android.browser.BrowserActivity"
BROWSER_BASIC_912 = "com.android.browser/com.android.browser.basicmode.BasicModeSettingActivity"

# 底栏没有「菜单」，只有「我的」（MIX Flip 2 那类布局）
BOTTOM_WITHOUT_MENU_912 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="主页" bounds="[0,2280][216,2400]" />
    <node class="android.widget.TextView" text="视频" bounds="[216,2280][432,2400]" />
    <node class="android.widget.TextView" text="免费小说" bounds="[648,2280][864,2400]" />
    <node class="android.widget.TextView" text="我的" bounds="[864,2280][1080,2400]" />
  </node>
</hierarchy>"""

# 报告者那台机浏览器「我的」页：顶部图标只有 content-desc、自身可点，底栏标签也只有 desc
BROWSER_MINE_912 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" resource-id="com.android.browser:id/iv_personal_scan"
          content-desc="扫一扫" clickable="true" bounds="[538,139][654,255]" />
    <node class="android.widget.ImageView" resource-id="com.android.browser:id/iv_personal_incognito"
          content-desc="无痕模式" clickable="true" bounds="[666,139][782,255]" />
    <node class="android.widget.ImageView" resource-id="com.android.browser:id/iv_personal_night_mode"
          content-desc="夜间模式" clickable="true" bounds="[794,139][910,255]" />
    <node class="android.widget.ImageView" resource-id="com.android.browser:id/iv_personal_settings"
          content-desc="设置" clickable="true" bounds="[922,139][1038,255]" />
    <node class="android.view.ViewGroup" resource-id="com.android.browser:id/action_person"
          content-desc="我的已选中" clickable="true" bounds="[864,2226][1080,2355]">
      <node class="android.widget.TextView" text="我的" clickable="false" bounds="[942,2307][1002,2348]" />
    </node>
  </node>
</hierarchy>"""

# 主题「我的」页：内容区三行「我的…」，底栏只有 content-desc 的标签，右上是只有 desc 的图标
THEME_MINE_912 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.thememanager" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="我的点赞" clickable="true" bounds="[48,700][400,780]" />
    <node class="android.widget.TextView" text="我的收藏" clickable="true" bounds="[48,800][400,880]" />
    <node class="android.widget.TextView" text="我的订单" clickable="true" bounds="[48,900][400,980]" />
    <node class="android.widget.ImageView" resource-id="com.android.thememanager:id/settings"
          content-desc="设置" clickable="true" bounds="[967,200][1044,277]" />
    <node class="android.widget.RelativeLayout" content-desc="未选中,我的" clickable="true"
          bounds="[776,2212][1011,2355]" />
  </node>
</hierarchy>"""

# 同一页，顶部那一排图标这一帧还没画出来（「设置」晚一帧进树）
THEME_MINE_EARLY_912 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.thememanager" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="我的点赞" clickable="true" bounds="[48,700][400,780]" />
    <node class="android.widget.RelativeLayout" content-desc="未选中,我的" clickable="true"
          bounds="[776,2212][1011,2355]" />
  </node>
</hierarchy>"""

THEME_MINE_FOCUS_912 = "com.android.thememanager/.ThemeResourceProxyTabActivity"
BROWSER_GEAR_912 = (980, 197)           # iv_personal_settings 的中心
THEME_GEAR_912 = (1005, 238)            # com.android.thememanager:id/settings 的中心
MINE_TAB_CENTER_912 = (893, 2283)
BROWSER_MINE_TAB_912 = (972, 2327)      # action_person 里那个「我的」文字
CONTENT_CENTERS_912 = [(224, 740), (224, 840), (224, 940)]      # 「我的点赞 / 收藏 / 订单」


class ClockCase(unittest.TestCase):
    """假时钟装进 fast：Phone 里的等待都按假时间走。"""

    def install(self):
        clock = Clock()
        clocked(self, fast, clock)
        self.clock = clock
        return clock


class BrowserDirectTests(ClockCase):
    def browser_phone(self, stages, focus):
        clock = self.install()
        p = fake_phone(clock=clock, size=(1080, 2400), stages=stages, focus=focus)
        p.entry = Mock(return_value=False)          # 后面几页入口不在这一段要测的东西里
        p.back = Mock()                             # 结尾的 back(2) 不算「点过什么」
        return p, clock

    def test_direct_settings_page_is_tried_before_the_menu(self):
        """直达落在设置页时，只拉起这一个页面：不走「菜单」，也不点底栏「我的」。"""
        started = []
        p, clock = self.browser_phone([(0.0, BROWSER_MINE_912)], ((0.0, BROWSER_HOME_912),))

        def start(pkg, activity=None, **kw):
            started.append((pkg, activity))
            if activity:
                p.screen.focus = lambda: f"{pkg}/{activity}"
        p.start = start
        scope, out = load_recipe(p, RECIPE_912, only="浏览器")
        self.assertIn("直达浏览器设置页", out.getvalue())
        self.assertEqual(started, [("com.android.browser", ".BrowserSettingsActivity")])
        self.assertEqual(clock.clicks, 0)           # 底栏一个都没点
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_falls_back_to_the_menu_then_my_tab(self):
        """直达落空时按「菜单」→「我的」→ 齿轮走，用的是报告者贴的「我的」页节点。"""
        clicked = []
        p, clock = self.browser_phone([(0.0, BROWSER_MINE_912)], ((0.0, BROWSER_HOME_912),))
        stub(p, "click", lambda x, y: (clicked.append((x, y)), clock.click())[1])
        p.in_settings_page = Mock(return_value=True)    # 落点判据由 #960 的用例守

        def start(pkg, activity=None, **kw):
            if activity:
                raise RuntimeError("无法打开")
        p.start = start
        scope, out = load_recipe(p, RECIPE_912, only="浏览器")
        self.assertIn("· 底栏没有「菜单」，改走「我的」→ 设置", out.getvalue())
        self.assertEqual(clicked, [BROWSER_MINE_TAB_912, BROWSER_GEAR_912])
        p.in_settings_page.assert_called_once_with()
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_basic_mode_page_is_still_skipped_after_trying_the_direct(self):
        """基本模式的机型直达会落到 BasicModeSettingActivity：落点判不过，仍按跳过收尾（#414）。"""
        p, clock = self.browser_phone([(0.0, BOTTOM_WITHOUT_MENU_912)], ((0.0, BROWSER_BASIC_912),))
        p.start = Mock()                            # 拉起不改变前台，两张页面都不认
        scope, out = load_recipe(p, RECIPE_912, only="浏览器")
        self.assertIn("基本模式", out.getvalue())
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(clock.clicks, 0)

    def test_entry_failure_reports_the_page_evidence(self):
        """两条回退都不通时，收尾行带页面现场（与「到了但页面不对」同形）。"""
        p, _clock = self.browser_phone([(0.0, BOTTOM_WITHOUT_MENU_912)], ((0.0, BROWSER_HOME_912),))

        def start(pkg, activity=None, **kw):
            if activity:
                raise RuntimeError("无法打开")
        p.start = start
        p.tab = Mock(return_value=False)            # 底栏也没有「我的」
        scope, out = load_recipe(p, RECIPE_912, only="浏览器")
        text = out.getvalue()
        self.assertEqual(scope["FAILED_STEPS"], ["浏览器"])
        self.assertIn(f"浏览器底部没有「菜单」，也没有「我的」标签；停在 {BROWSER_HOME_912}", text)
        self.assertIn("当次读到 0 个开关", text)      # 现场是 page_evidence() 的四段，不是一句 focus


class ThemeSettingsTests(ClockCase):
    """主题「我的」：底栏标签只有 desc、内容区有同名文字，齿轮晚一帧进树。"""

    def setUp(self):
        clock = self.install()
        self.clicked = []
        self.p = fake_phone(clock=clock, size=(1080, 2400), stages=[(0.0, THEME_MINE_912)],
                            focus=((0.0, THEME_MINE_FOCUS_912),))
        stub(self.p, "click", lambda x, y: (self.clicked.append((x, y)), clock.click())[1])

    def load(self):
        scope, _ = load_recipe(self.p, RECIPE_912)
        scope["time"] = self.clock        # 脚本级等待也走同一只假钟
        return scope

    def test_my_tab_hits_the_bottom_bar_not_the_content_rows(self):
        scope = self.load()
        scope["gear"] = Mock(return_value=True)
        with contextlib.redirect_stdout(io.StringIO()):
            scope["theme_settings"]()
        self.assertEqual(self.clicked, [MINE_TAB_CENTER_912])
        for center in CONTENT_CENTERS_912:
            self.assertNotIn(center, self.clicked)
        scope["gear"].assert_called_once_with()

    def test_settings_icon_showing_up_late_is_waited_for(self):
        """图标前一帧还不在树里：等它进树再交给 gear()，齿轮照样点得中。

        去掉那次等待，gear() 的第一帧快照看到的是没有图标的页面，两次都失败（返红）。"""
        p = phone_mock()
        p.locked = lambda: False
        p.W, p.H = 1080, 2400
        p.tab.return_value = True
        p.find.return_value = None
        p.tap.return_value = False
        p.in_settings_page.return_value = True
        pages = [ET.fromstring(THEME_MINE_EARLY_912), ET.fromstring(THEME_MINE_EARLY_912),
                 ET.fromstring(THEME_MINE_912)]
        p.screen.tree.side_effect = lambda: pages[min(p.tree.call_count - 1, len(pages) - 1)]
        scope, _ = load_recipe(p, RECIPE_912)
        with contextlib.redirect_stdout(io.StringIO()):
            scope["theme_settings"]()
        p.click.assert_called_once_with(*THEME_GEAR_912)
        self.assertGreaterEqual(p.tree.call_count, 4)   # 等的那几帧 + gear() 自己那一帧

    def test_two_misses_report_the_page_evidence(self):
        scope = self.load()
        scope["gear"] = Mock(return_value=False)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, f"主题设置入口没找到；停在 {THEME_MINE_FOCUS_912}"):
                scope["theme_settings"]()
        self.assertEqual(scope["gear"].call_count, 2)


# ---------- 来源 tests/test_theme_entry_730.py ----------
#   机型脚本拉起主题管理包必须带 activity（#730）。
#   
#   `com.android.thememanager` 没有 LAUNCHER activity：`Phone.start` 不带 activity 会退到
#   monkey，一律 `** No activities found to run, monkey aborted.`，主题段必失败。主题商店
#   （`com.miui.themestore`）不可见的机型正好落在兜底分支上，所以兜底也要带 activity。

# 活动名只认 entries 这一处：它改名时守卫要跟着红，而不是脚本与用例一起静默漂移。
_ENTRY_730 = next(d for d in entries.ENTRIES["xiaomi"]["主题"].direct if d.pkg == "com.android.thememanager")
THEME, DIRECT = _ENTRY_730.pkg, _ENTRY_730.activity
SKIP_730 = "本机没有主题管理包，跳过"


def recipes_730():
    return sorted((ROOT / "recipes").glob("*/recipe*.py"))


def literal_730(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def monkey_shells_730(tree):
    """`p.d.shell("… monkey … com.android.thememanager …")`：注定 abort 的那条命令。"""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "shell"):
            continue
        text = literal_730(node.args[0])
        if text and "monkey" in text and THEME in text:
            hits.append(node.lineno)
    return hits


def bare_starts_730(tree):
    """`p.start("com.android.thememanager")`（activity 缺省 / 空）：引擎会退到 monkey。"""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "start"):
            continue
        if literal_730(node.args[0]) != THEME:
            continue
        activity = node.args[1] if len(node.args) > 1 else None
        for keyword in node.keywords:
            if keyword.arg == "activity":
                activity = keyword.value
        if activity is None or (isinstance(activity, ast.Constant) and not activity.value):
            hits.append(node.lineno)
    return hits


class ThemeEntryGuardTests(unittest.TestCase):
    def test_recipes_launch_thememanager_with_an_activity(self):
        found = recipes_730()
        self.assertTrue(found, "recipes/ 下一份机型脚本都没找到")
        for path in found:
            rel = path.relative_to(ROOT)
            with self.subTest(recipe=str(rel)):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                self.assertEqual(monkey_shells_730(tree), [], f"{rel}: 用 monkey 拉起 {THEME}")
                self.assertEqual(bare_starts_730(tree), [], f"{rel}: 不带 activity 的 Phone.start")


class ThemeFallbackBehaviourTests(unittest.TestCase):
    """兜底分支的两种结局：已装则直达代理标签页，没装则跳过本段而不是记失败。"""

    def load(self, path, themestore, thememanager):
        p = phone_mock()
        p.locked = lambda: False
        p.tree.return_value.iter.return_value = []
        p.texts.return_value = []
        paths = {"com.miui.themestore": themestore, THEME: thememanager}

        def shell(command, timeout=None):
            for package, output in paths.items():
                if command == f"pm path {package}":
                    return SimpleNamespace(output=output, exit_code=0)
            return SimpleNamespace(output="", exit_code=0)
        p.d.shell.side_effect = shell
        out = io.StringIO()
        scope, _ = load_recipe(p, path, only="主题", out=out)
        return p, out.getvalue(), scope

    def test_installed_thememanager_is_launched_directly(self):
        for path in (ROOT / "recipes/xiaomi-24129PN74C/recipe.py",
                     ROOT / "recipes/xiaomi-24090RA29C/recipe.py"):
            with self.subTest(recipe=path.parent.name):
                p, _, _ = self.load(path, "", "package:/system/app/ThemeManager/ThemeManager.apk")
                # 只比对拉起那一步：往后的「我的 → 齿轮」与开关校验由 #906 的用例守
                p.d.shell.assert_any_call(f"pm path {THEME}")
                p.start.assert_called_once_with(THEME, DIRECT)

    # 缺失主题管理包时按跳过收尾的那条判据由 #906 / #902 一起守（覆盖全部脚本），这里不再重复。


# ---------- 来源 tests/test_theme_settings_landing_906.py ----------
#   主题段进设置页要校验落点（#906）。
#   
#   0.4.x 上报库里「停在 thememanager 首页、整页 0 个标题 0 个开关」与「设置页本来就少一项」
#   同形：`go()` / `gear()` 的返回值被丢掉，`off()` 又把空页当成功收尾。用例护住三层：
#   
#   - 所有小米 / 红米脚本的主题段都不再有未被消费的 `go()` / `gear()` 返回值，点名开关走
#     `require_switches()` / `close_named()`，也不再经主题商店冷启动（AST 守卫，一份都不能漏）；
#   - 导航没到设置页 / 设置页上一个点名开关都没读到时整段失败，报错带页面现场；
#   - 导航正常时输出与改动前逐字一致（不多打一行提示）。
#   
#   真机缺口：这里只验到「失败会响亮地失败」，验不到 OS3.0.3xx 上「我的 → 齿轮」之后到底能不能
#   进设置页——那要等一次真实运行（票面「验证缺口」）。


THEME_906 = "com.android.thememanager"
STORE_906 = "com.miui.themestore"
INSTALLED_906 = "package:/system/app/ThemeManager/ThemeManager.apk"
FOCUS_906 = f"{THEME_906}/.ThemeResourceProxyTabActivity"
SWITCH_906 = "每次联网时通知"
PRIVACY_906 = "个性化推荐"

# 主题首页：底部一个「我的」标签（y > 85% 屏高），「我的」页右上角是 desc=设置 的齿轮。
PAGE_906 = """<hierarchy rotation="0">
<node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
<node class="android.widget.ImageView" content-desc="设置" bounds="[950,180][1040,260]" clickable="true"/>
<node class="android.widget.TextView" text="我的" bounds="[0,2180][270,2380]" clickable="true"/>
</node>
</hierarchy>"""

EMPTY_906 = """<hierarchy rotation="0">
<node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]"/>
</hierarchy>"""


def injected_step_1210(name):
    """注入面里 `name` 的实现函数节点；没有这个名字返回 None（#1210）。

    源码先过 `fixtures.normalize()`：`g["X"]` 折回 `X`，下面按裸名找 go / gear / require_switches 的守卫
    才认得出注入实现里那几个调用。"""
    source = recipe_source.injected_sources().get(name)
    if source is None:
        return None
    factory = next((node for node in ast.parse(fixtures.normalize(source)).body
                    if isinstance(node, ast.FunctionDef)), None)
    if factory is None:
        return None
    return next((node for node in factory.body if isinstance(node, ast.FunctionDef)), None)


def effective_step_body(node, defines=frozenset()):
    """段体的有效 AST：脚本本地写的那份，或它转调的注入实现（#1210 起段体只留一行调用）。

    `defines` 是这份脚本的模块级函数名：本地定义覆盖注入版，那种情况拿到的仍是脚本自己那份。"""
    body = node.body
    if len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Call):
        func = body[0].value.func
        if isinstance(func, ast.Name) and func.id not in defines:
            return injected_step_1210(func.id) or node
    return node


def theme_steps_906():
    """[(路径, 段函数)]：所有带 `@step("主题")` 的小米 / 红米脚本段；段体搬进注入面的给实现本身。"""
    found = []
    for path in sorted((ROOT / "recipes").glob("*/recipe*.py")):
        if entries.family(path.parent.name.split("-", 1)[0]) != "xiaomi":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defines = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "step"
                        and dec.args and getattr(dec.args[0], "value", None) == "主题"):
                    found.append((path, effective_step_body(node, defines)))
    return found


def unconsumed_906(fn):
    """段里返回值被丢掉的 `go()` / `gear()` 所在行号（#906）。

    算「消费」的只有三种落点：if/while 的判据、赋值/返回、交给 require() 系断言。
    """
    parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
    bad = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in {"go", "gear"}:
            continue
        cur, parent = node, parents.get(node)
        while isinstance(parent, (ast.BoolOp, ast.UnaryOp, ast.Compare, ast.IfExp)):
            cur, parent = parent, parents.get(parent)
        consumed = ((isinstance(parent, (ast.If, ast.While)) and cur is parent.test)
                    or isinstance(parent, (ast.Assign, ast.Return))
                    or (isinstance(parent, ast.Call)
                        and getattr(parent.func, "id", "") in {"require", "close_named",
                                                               "require_switches"}))
        if not consumed:
            bad.append(node.lineno)
    return bad


def called_names_906(fn):
    return {getattr(n.func, "id", "") for n in ast.walk(fn) if isinstance(n, ast.Call)}


class ThemeLandingGuardTests(unittest.TestCase):
    def test_every_theme_step_consumes_go_and_gear(self):
        steps = theme_steps_906()
        self.assertGreaterEqual(len(steps), 15, "主题段的机型脚本少找了")
        for path, fn in steps:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                self.assertEqual(unconsumed_906(fn), [], f"{path.name}: 丢了导航的返回值")

    def test_every_theme_step_verifies_the_named_switch(self):
        for path, fn in theme_steps_906():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                self.assertTrue(called_names_906(fn) & {"require_switches", "close_named"},
                                f"{path.name}: 点名开关没有校验")

    def test_theme_steps_launch_the_manager_directly(self):
        """#906：不再经主题商店冷启动。落点被系统转走时由 start_or_skip 收成跳过（#902）。"""
        for path, fn in theme_steps_906():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                literals = {n.value for n in ast.walk(fn)
                            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                self.assertNotIn(STORE_906, literals, f"{path.name}: 还在冷启动主题商店")


class ThemeSettingsLandingTests(unittest.TestCase):
    def phone(self, page=PAGE_906, state=None, nav=True):
        """主题首页 + 「我的」标签可点；state 是设置页上读到的开关（{标题: 是否开着}）。"""
        p = phone_mock()
        p.W, p.H = 1080, 2400
        p.locked = lambda: False
        p.screen.focus = lambda: FOCUS_906
        p.screen.tree.return_value = ET.fromstring(page)
        texts = [("我的", (0, 2180, 270, 2380), ET.fromstring(page))] if page is PAGE_906 else []
        p.screen.texts.return_value = texts
        rows = dict(state or {})

        def shell(command, timeout=None):
            return SimpleShell(INSTALLED_906 if command == f"pm path {THEME_906}" else "")
        p.d.shell.side_effect = shell
        p.switches.side_effect = lambda *a, **k: [(name, on, (900, 500)) for name, on in rows.items()]

        def fake_off(*a, only=None, **k):
            for name in only or ():
                if name in rows:
                    rows[name] = False
        p.off.side_effect = fake_off
        p.go.return_value = nav
        p.tab.return_value = nav
        p.tap.return_value = nav
        p.find.return_value = (900, 150) if nav else None
        p.entry.return_value = True
        # 页面现场用真实实现：报错文案正是这条用例要护住的东西；包一层 Mock 好数调用次数。
        p.screen._page_diagnosis = lambda: fast.Screen._page_diagnosis(p.screen)
        p.page_evidence = Mock(side_effect=lambda titles=(): fast.Screen.page_evidence(p.screen, list(titles)))
        return p

    def test_zero_named_switches_fails_the_step_with_page_evidence(self):
        for path, _ in theme_steps_906():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                p = self.phone(state={})
                out = io.StringIO()
                scope, _ = load_recipe(p, path, only="主题", out=out)
                self.assertEqual(scope["FAILED_STEPS"], ["主题"])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                p.off.assert_not_called()
                text = out.getvalue()
                self.assertIn("未识别全部目标开关", text)
                self.assertIn(FOCUS_906, text)
                self.assertIn("当次读到 0 个开关", text)

    def test_navigation_that_never_reaches_the_settings_page_fails_the_step(self):
        for path, _ in theme_steps_906():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                p = self.phone(page=EMPTY_906, state={SWITCH_906: True}, nav=False)
                out = io.StringIO()
                scope, _ = load_recipe(p, path, only="主题", out=out)
                self.assertEqual(scope["FAILED_STEPS"], ["主题"])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                p.off.assert_not_called()
                text = out.getvalue()
                self.assertIn(FOCUS_906, text)
                self.assertIn("当次读到 0 个开关", text)

    def test_navigation_to_the_settings_page_keeps_the_output_unchanged(self):
        for path, _ in theme_steps_906():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                p = self.phone(state={SWITCH_906: True, PRIVACY_906: True})
                out = io.StringIO()
                scope, _ = load_recipe(p, path, only="主题", out=out)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                # 与改动前逐字一致：不多打行，失败才用的页面现场也不去读（时长行与脚本末尾的台账行不算）
                section = out.getvalue().split("== 主题", 1)[1]
                self.assertNotIn("✗", section)
                self.assertNotIn("  · ", section)
                p.page_evidence.assert_not_called()
                self.assertEqual(p.off.call_args_list[0].kwargs["page"], "主题·设置")


class ThemeUnreachableStillSkippedTests(unittest.TestCase):
    def test_missing_thememanager_is_skipped_not_failed(self):
        """没有主题管理包的机器仍按跳过收尾，不算失败（#730 / #902 的口径不变）。"""
        for path, _ in theme_steps_906():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                p = phone_mock()
                p.locked = lambda: False
                p.d.shell = Mock(return_value=SimpleShell(""))
                out = io.StringIO()
                scope, _ = load_recipe(p, path, only="主题", out=out)
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertIn("本机没有主题管理包，跳过", out.getvalue())
                p.d.shell.assert_any_call(f"pm path {THEME_906}")
                p.start.assert_not_called()


class SimpleShell:
    """`p.d.shell` 的返回形状：只要 output / exit_code。"""

    def __init__(self, output=""):
        self.output, self.exit_code = output, 0


# ---------- 来源 tests/test_theme_unreachable_902.py ----------
#   主题商店缺失、主题页被系统转走时按跳过收尾（#902）。
#   
#   没有主题商店的小米 / 红米机型上，主题管理包的代理页会被系统导去应用商店详情页或桌面。
#   `Phone.start` 等不到前台时抛 RuntimeError，段体要把这一档记成跳过（入口不可达），而不是
#   未完成；落点在别的 App 时仍是未完成，保留 #547 的落点诊断。


THEME_902 = "com.android.thememanager"
STORE_902 = "com.miui.themestore"
MARKET_902 = "com.xiaomi.market/com.xiaomi.market.ui.detail.AppDetailActivityInner"
LAUNCHER_902 = "com.miui.home/.launcher.Launcher"
OTHER_902 = "com.miui.securitycenter/com.miui.securityscan.activity.MainActivity"


def theme_recipes_902():
    """带 `@step("主题")` 的机型脚本：一份都不能漏，否则「所有共用这段入口的脚本一起改」就没守住。"""
    found = []
    for path in sorted((ROOT / "recipes").glob("*/recipe*.py")):
        if entries.family(path.parent.name.split("-", 1)[0]) != "xiaomi":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "step"
                        and dec.args and getattr(dec.args[0], "value", None) == "主题"):
                    found.append(path)
    return found


class ThemeUnreachableTests(unittest.TestCase):
    def run_theme(self, path, landing, store=""):
        p = phone_mock()
        p.locked = lambda: False
        installed = {STORE_902: store, THEME_902: "package:/system/app/ThemeManager/ThemeManager.apk"}

        def shell(command, timeout=None):
            for package, output in installed.items():
                if command == "pm path " + package:
                    return SimpleNamespace(output=output, exit_code=0)
            return SimpleNamespace(output="", exit_code=0)

        p.d.shell.side_effect = shell
        # 落点只认 `Phone.start` 报错里带着的那份；抛错之后再读前台有窗口期，故意让它读成别的。
        p.screen.focus = lambda: "com.example.stale/.Main"
        p.start.side_effect = RuntimeError(
            f"{THEME_902} 没有进入前台，跳过本段（停在 {landing}；标题 5 个、开关 0 个）")
        out = io.StringIO()
        scope, _ = load_recipe(p, path, only="主题", out=out)
        return scope, out.getvalue(), p

    @staticmethod
    def manager_only():
        """只装了主题管理包、没有主题商店：脚本会走代理页兜底。"""
        def shell(command, timeout=None):
            installed = command == "pm path " + THEME_902
            return SimpleNamespace(output="package:/system/app/ThemeManager/ThemeManager.apk"
                                   if installed else "", exit_code=0)
        return shell

    def test_store_detail_page_landing_is_skipped(self):
        """主题商店缺失 + 落在应用商店详情页：跳过，理由里带落点。"""
        scope, out, _ = self.run_theme(ROOT / "recipes/xiaomi-24129PN74C/recipe.py", MARKET_902)
        self.assertEqual(scope["SKIPPED_STEPS"], ["主题"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("com.xiaomi.market", out)

    def test_every_theme_recipe_skips_when_the_store_page_takes_over(self):
        """所有共这段入口的小米 / 红米脚本一起改：商店详情页落点哪一份都不能记成未完成。"""
        recipes = theme_recipes_902()
        self.assertGreaterEqual(len(recipes), 15, "主题段的机型脚本少找了")
        for path in recipes:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, out, _ = self.run_theme(path, MARKET_902)
                self.assertEqual(scope["SKIPPED_STEPS"], ["主题"])
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertIn("com.xiaomi.market", out)

    def test_launcher_landing_is_skipped_too(self):
        """桌面落点与被导去应用商店是同一档：主题页根本打不开。"""
        for path in theme_recipes_902():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, out, _ = self.run_theme(path, LAUNCHER_902)
                self.assertEqual(scope["SKIPPED_STEPS"], ["主题"])
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertIn("com.miui.home", out)

    def test_another_app_taking_over_stays_unfinished(self):
        """落点是别的 App（例如开屏广告顶掉）不是「入口不可达」：仍按未完成上报，落点留在理由里。"""
        for path in theme_recipes_902():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, out, _ = self.run_theme(path, OTHER_902)
                self.assertEqual(scope["FAILED_STEPS"], ["主题"])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                self.assertIn("未完成", out)
                self.assertIn("com.miui.securitycenter", out)

    def test_launch_error_that_is_not_a_landing_mismatch_stays_unfinished(self):
        """「无法打开 / 没装」不是落点不对：那时前台可能只是桌面，不能当成入口不可达的证据。"""
        p = phone_mock()
        p.locked = lambda: False
        p.screen.focus = lambda: LAUNCHER_902
        p.d.shell.side_effect = self.manager_only()
        p.start.side_effect = RuntimeError(f"无法打开 {THEME_902}：** No activities found to run")
        out = io.StringIO()
        scope, _ = load_recipe(p, ROOT / "recipes/xiaomi-24129PN74C/recipe.py", only="主题", out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["主题"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertIn("No activities found", out.getvalue())

    def test_disconnect_is_not_reported_as_an_unreachable_entry(self):
        """断线交还引擎整轮停下，不能被当成「入口不可达」收成跳过。"""
        p = phone_mock()
        p.locked = lambda: False
        p.screen.focus = lambda: LAUNCHER_902
        p.d.shell.side_effect = self.manager_only()
        p.start.side_effect = adb_link.DeviceLost("device offline")
        with self.assertRaises(adb_link.DeviceLost):
            load_recipe(p, ROOT / "recipes/xiaomi-24129PN74C/recipe.py", only="主题", out=io.StringIO())

    def test_installed_store_does_not_change_the_launch(self):
        """主题商店在不在都直达代理页（#906），不再经商店冷启动过一次重定向过渡窗。

        商店路径只在 #730 的兜底里出现过；现在统一成一条，落点被转走仍按跳过收尾。"""
        for path in theme_recipes_902():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                _, _, p = self.run_theme(path, MARKET_902,
                                         store="package:/system/app/ThemeStore/ThemeStore.apk")
                self.assertEqual(p.start.call_args_list[0].args[0], THEME_902)
                self.assertNotIn(STORE_902, [call.args[0] for call in p.start.call_args_list])


if __name__ == "__main__":
    unittest.main()
