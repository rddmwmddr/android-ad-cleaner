"""文档与单一来源一致：ADR 字段表（#467）、品牌连点表（#654）、官网共享样式（#653）、教程截图 alt（#655）、站点与侧栏图标同源（#669）、ADR 索引（#624）、静态检查目标（#624）、手机版措辞的宿主边界（#732）、adapt 的 -s 写法（#740）、Windows USB 提示三分支（#785）、贡献入口不复述规则（#851）、agent 手册的挂起顺序（#981）、配置类四条规则与 pyproject / .coveragerc 对拍（#1300）。"""
import configparser
import re
import sys
import tomllib
import unittest
from dataclasses import fields
from pathlib import Path

from gui import app, standalone
from test_rules_registry import ANCHOR as RULE_ANCHOR  # 同一份锚点口径，别再抄一份

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import channel_policy as policy
import run
from devtools import gen_adr_index as adr_index
from devtools import gen_brand_taps as gen
from devtools import gen_site_css as site_css
from devtools import release_assets, release_meta

ADR = ROOT / "docs/adr/0006-channel-classification.md"
ADR_INDEX = ROOT / "docs/adr/README.md"
CLAUDE = ROOT / "CLAUDE.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
REPEAT_WINDOW = 40
ENTRY_DOCS = ("CLAUDE.md", "CODING_STANDARDS.md", "docs/agents/", "CONTEXT.md", "AGENTS.md")
ADR_NAME = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
ADR_ROW = re.compile(r"^- \[(\d{4})\]\(([^)]+)\) — (.*)$")
BRAND_TAP_TARGETS = {"html", "readme", "dev_doc"}
TUTORIAL_PAGE = ROOT / "android-tutorial.html"
TUTORIAL_README = ROOT / "docs/手机版教程/README.md"


def table_fields():
    """ADR-0006 表格第一列里用反引号写出的字段名。"""
    names = []
    for line in ADR.read_text(encoding="utf-8").splitlines():
        cells = line.split("|")
        if len(cells) < 3:
            continue
        first = cells[1].strip()
        if len(first) > 2 and first.startswith("`") and first.endswith("`"):
            names.append(first.strip("`"))
    return names


class JudgementDocTests(unittest.TestCase):
    def test_adr_field_table_matches_channel_judgement(self):
        listed = table_fields()
        self.assertTrue(listed, "ADR-0006 的字段表没被读到，这条守卫会空转")
        self.assertEqual(sorted(listed), sorted(f.name for f in fields(policy.ChannelJudgement)),
                         "字段表与 ChannelJudgement 不一致：新增判定加一行，删判定删行")


class AdrIndexTests(unittest.TestCase):
    """`docs/adr/` 的每一份都被 `docs/adr/README.md` 的索引收录，索引里也没有别的编号（#1299，沿用 #624）。

    索引从 CLAUDE.md 搬过来是为了让每个会话的启动上下文不再背一整份标题清单；搬过来之后
    多一条反向判据：索引里出现的编号必须真有那一份文件，否则清单会单向腐烂。
    """

    def test_index_lists_every_adr_and_nothing_else(self):
        names = sorted(p.name for p in (ROOT / "docs/adr").glob("*.md") if p.name != ADR_INDEX.name)
        self.assertTrue(names, "docs/adr 里没有 ADR，守卫会空转")
        bad = [name for name in names if ADR_NAME.match(name) is None]
        self.assertEqual(bad, [], "ADR 文件名应是 NNNN-slug.md（不合名的会被索引跳过）：" + "、".join(bad))
        numbers = [ADR_NAME.match(name).group(1) for name in names]
        dup = sorted({number for number in numbers if numbers.count(number) > 1})
        self.assertEqual(dup, [], "两份 ADR 用了同一个编号（并行会话抢号），重编号再跑生成器："
                         + "、".join(dup))
        rows = [ADR_ROW.match(line) for line in ADR_INDEX.read_text(encoding="utf-8").splitlines()]
        listed = [(m.group(1), m.group(2), m.group(3)) for m in rows if m]
        self.assertTrue(listed, "docs/adr/README.md 里没读到索引行，守卫会空转")
        expected = [(e.number, e.filename, e.title) for e in adr_index.entries()]
        missing = sorted(set(expected) - set(listed))
        extra = sorted(set(listed) - set(expected))
        self.assertEqual(missing, [], "这些 ADR 没被索引收录（或标题与一级标题不符，跑 "
                         "`python devtools/gen_adr_index.py`）：" + "、".join(
                             f"{number} {filename}" for number, filename, _ in missing))
        self.assertEqual(extra, [], "索引里有不存在的条目（或标题已改，跑 "
                         "`python devtools/gen_adr_index.py`）：" + "、".join(
                             f"{number} {filename}" for number, filename, _ in extra))

    def test_claude_md_points_at_the_index(self):
        """索引搬出启动上下文之后，这一条指针是 agent 找到它的唯一入口。"""
        self.assertIn("docs/adr/README.md", CLAUDE.read_text(encoding="utf-8"),
                      "CLAUDE.md 要留一条指向 docs/adr/README.md 的指针")


RUFF_CMD = re.compile(r"ruff[@\w.]* check (.+)")


def ruff_targets(text):
    """把文本里每条 `ruff check <目标>` 的目标清单切出来（到反引号或行末为止）。

    规则集（`F` / `E9` / `B`）已收进 `pyproject.toml`，命令里不再有 `--select`，
    所以这里比的是目标清单而不是整条命令（#994）。"""
    return [line.split("`")[0].split() for line in RUFF_CMD.findall(text)]


class LintCommandTests(unittest.TestCase):
    """静态检查的目标清单在 CLAUDE.md、发版文档、CONTRIBUTING.md 与 CI 四处一致（沿用 #624、#851）：加目录时四处一起改。
    规则集收进 `pyproject.toml` 后命令里不再有 `--select`（#994）：命令里再写会盖掉配置，加进去的规则不生效。"""

    def test_ruff_targets_match_everywhere(self):
        docs = [ROOT / "CLAUDE.md", ROOT / "docs/agents/release.md", ROOT / "CONTRIBUTING.md",
                ROOT / ".github/workflows/test.yml"]
        texts = [(path, path.read_text(encoding="utf-8")) for path in docs]
        for path, text in texts:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertNotIn("--select", text,
                                 "规则集已收进 pyproject.toml，命令里不该再有 --select")
        expected = ruff_targets(texts[0][1])
        self.assertEqual(len(expected), 1, "CLAUDE.md 里应当恰好一条 ruff 命令")
        self.assertIn("tool", expected[0], "目标清单没读到，守卫会空转")
        for path, text in texts[1:-1]:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual(ruff_targets(text), expected)
        ci = ruff_targets(texts[-1][1])
        self.assertEqual(len(ci), 1,
                         "CI 应当恰好一条 ruff 命令（平台无关，只在 lint job 跑），读到 %d 条" % len(ci))
        self.assertEqual(ci, [expected[0]])


def chinese_number(value):
    """1–99 的中文写法：「严格档只给十个纯逻辑模块」那句里的数字要与名单长度对拍。"""
    digits = "零一二三四五六七八九"
    if value < 10:
        return digits[value]
    tens, ones = divmod(value, 10)
    return ("" if tens == 1 else digits[tens]) + "十" + (digits[ones] if ones else "")


class ConfigRuleTests(unittest.TestCase):
    """CLAUDE.md 里四条「配置即判据」的规则与真实配置文件对拍（#1300）。

    这四条原先的 `check` 都指向 CI job，而 job 绿只说明命令跑过了：把 pyproject.toml 的
    `select`、`files` 或 `.coveragerc` 的 `branch` 改坏，`lint` / `types` / `coverage`
    三个 job 照样绿。四条都是守卫用例：旧树也绿，守的是不回退。"""

    def setUp(self):
        self.claude = CLAUDE.read_text(encoding="utf-8")
        self.pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.mypy = self.pyproject["tool"]["mypy"]

    def line(self, rule_id):
        lines = [line for line in self.claude.splitlines()
                 if (found := RULE_ANCHOR.search(line)) and found.group(1) == rule_id]
        self.assertEqual(len(lines), 1, f"CLAUDE.md 里要有且只有一行挂 rule:{rule_id}")
        return lines[0]

    def test_dev_ruff_bugbear_rules(self):
        select = self.pyproject["tool"]["ruff"]["lint"]["select"]
        self.assertEqual(select, ["F", "E9", "B"],
                         "pyproject.toml 的 select 是规则集的唯一定义处：删任一档，那一类错误静默失效")
        self.assertIn("`B`", self.line("dev.ruff.bugbear-rules"),
                      "CLAUDE.md 那一行仍要说明 B（bugbear）类已启用")

    def test_dev_types_narrow_scope_in_config(self):
        self.assertEqual(self.mypy["files"], ["tool"],
                         "mypy 的扫描范围要留在 pyproject.toml 且只扫 tool/，命令里不带路径")
        self.assertEqual(self.mypy["python_version"],
                         (ROOT / ".python-version").read_text(encoding="utf-8").strip(),
                         "python_version 要与 .python-version 同版，换一版结论不等价")
        self.assertIs(self.mypy["check_untyped_defs"], True,
                      "宽松档就是 check_untyped_defs，删掉它类型检查会大面积静默")
        self.assertEqual(self.mypy["disable_error_code"], ["var-annotated"],
                         "宽松档只关 var-annotated（空容器补注解），别的压制一律不做")
        line = self.line("dev.types.narrow-scope-in-config")
        self.assertIn("`[tool.mypy]`", line, "CLAUDE.md 那一行仍要说范围与宽松档参数在 pyproject.toml")
        self.assertIn("`files` 是 `tool/`", line, "CLAUDE.md 那一行仍要写明扫描范围是 tool/")

    def test_dev_types_strict_on_pure_modules(self):
        line = self.line("dev.types.strict-on-pure-modules")
        strict = [entry for entry in self.mypy["overrides"]
                  if "disallow_untyped_defs" in entry]
        self.assertEqual(len(strict), 1,
                         "pyproject.toml 里应恰好有一组严格档 overrides（带 disallow_untyped_defs）")
        entry = strict[0]
        self.assertNotIn("strict", entry,
                         "overrides 里写 strict = true 会被 mypy 当全局设置，只能逐项列 flag")
        names = re.findall(r"`([a-z][a-z0-9_]*)`", line.partition("：")[2].split("，")[0])
        self.assertTrue(names, "CLAUDE.md 那一行没读出严格档名单，守卫会空转")
        self.assertIn(f"只给{chinese_number(len(names))}个", line,
                      f"名单有 {len(names)} 个模块，正文的中文数字要对上")
        self.assertEqual(sorted(names), sorted(entry["module"]),
                         "严格档名单与 CLAUDE.md 不一致：增删模块要两处一起改")

    def test_dev_coverage_two_platform_merge(self):
        config = configparser.ConfigParser()
        config.read(ROOT / ".coveragerc", encoding="utf-8")
        run = config["run"]
        self.assertEqual(run["branch"], "True", "branch = True 才能看见没走到的分支")
        self.assertEqual(run["source"].split(),
                         ["tool", "gui", "android/app/src/main/python/aac_android"],
                         "source 只能是 tool、gui 与手机版替换层")
        self.assertEqual(run["relative_files"], "True",
                         "relative_files = True 是两份数据跨平台合并的前提")
        omit = [item.strip() for item in run["omit"].splitlines() if item.strip()]
        self.assertTrue(omit, "omit 没读到，守卫会空转")
        missing = [item for item in omit if not (ROOT / item).is_file()]
        self.assertEqual(missing, [], "omit 里的每一项都要真实存在：删文件时一并删这一行")
        self.assertNotIn("fail_under", config["report"],
                         "覆盖率不设阈值：加了 fail_under 会长期误伤只在 Windows 走到的分支")
        line = self.line("dev.coverage.two-platform-merge")
        self.assertIn("`branch=True`", line, "CLAUDE.md 那一行要与 .coveragerc 的 branch 一致")
        self.assertIn("`source=tool,gui,android/app/src/main/python/aac_android`", line,
                      "CLAUDE.md 那一行要与 .coveragerc 的 source 一致")


class BrandTapsDocTests(unittest.TestCase):
    """三处「连点 7 下」品牌表与单一来源一致（#654）。"""

    def test_target_set_is_frozen(self):
        self.assertEqual(set(gen.TARGETS), BRAND_TAP_TARGETS,
                         "TARGETS 的键变了：增删渲染目标要同时改 BRAND_TAP_TARGETS，"
                         "否则下面的逐字对拍会静默漏掉那个文件")

    def test_brand_tap_tables_match_single_source(self):
        rendered = gen.render_all()
        self.assertEqual(set(rendered), BRAND_TAP_TARGETS)
        for key, path in gen.TARGETS.items():
            text = path.read_text(encoding="utf-8")
            gen.check_markers(text, len(rendered[key]), path.name)
            self.assertEqual(gen.replace_regions(text, rendered[key]), text,
                             f"{path.name} 的品牌表与 docs/手机版教程/brand-taps.json 不一致："
                             "只改 JSON 一处后跑 python devtools/gen_brand_taps.py")

    def test_marker_count_mismatch_raises(self):
        text = gen.TARGETS["readme"].read_text(encoding="utf-8")
        gen.check_markers(text, 1, "readme")
        with self.assertRaises(ValueError, msg="多出一对标记时 check_markers 没报错"):
            gen.check_markers(text + "\n" + gen.START + "\n" + gen.END + "\n", 1, "readme")
        with self.assertRaises(ValueError, msg="少一对标记时 check_markers 没报错"):
            gen.check_markers(text.replace(gen.START, "", 1).replace(gen.END, "", 1), 1, "readme")

    def test_render_keeps_the_table_headers(self):
        rendered = gen.render_all()
        self.assertIn("<th>品牌</th><th>在哪儿连点 7 下</th>", rendered["html"][0])
        self.assertTrue(rendered["readme"][0].startswith("| 品牌 | 在哪儿连点 7 下 |"),
                        "README 表头被静默改掉了")
        self.assertTrue(rendered["dev_doc"][0].startswith("| 品牌 | 路径 |"),
                        "00 文档第一张表的表头被静默改掉了")
        self.assertTrue(rendered["dev_doc"][1].startswith("| 品牌 | 在哪儿连点 7 下 |"),
                        "00 文档第二张表的表头被静默改掉了")

    def test_end_marker_indent_matches_start(self):
        for path in gen.TARGETS.values():
            indents = {"start": set(), "end": set()}
            for line in path.read_text(encoding="utf-8").splitlines():
                kind = "start" if line.strip() == gen.START else "end" if line.strip() == gen.END else None
                if kind:
                    indents[kind].add(line[:len(line) - len(line.lstrip())])
            self.assertEqual(indents["start"], indents["end"],
                             f"{path.name} 的 brand-taps 标记缩进不一致")


class SiteCssTests(unittest.TestCase):
    """官网两页的共享样式与 site.css 一致（#653）。"""

    def test_target_set_is_frozen(self):
        self.assertEqual(set(site_css.TARGETS), {"home", "tutorial"},
                         "TARGETS 的键变了：增删渲染目标要同时改这里，否则下面的逐字对拍会静默漏掉那页")

    def test_both_pages_carry_the_shared_block(self):
        css = site_css.load_css()
        self.assertIn("--paper:", css, "site.css 里没读到调色板，守卫会空转")
        for path in site_css.TARGETS.values():
            with self.subTest(page=path.name):
                text = path.read_text(encoding="utf-8")
                site_css.check_markers(text, path.name)
                self.assertEqual(site_css.replace_region(text, css), text,
                                 f"{path.name} 的共享样式与 site.css 不一致：跑 python devtools/gen_site_css.py")

    def test_appearance_rules_live_only_in_the_shared_block(self):
        """旧树也绿，守的是共享规则不在页面里留副本：标记区外逐字相同的声明会盖掉 site.css 的改动。"""
        shared = [line for line in site_css.load_css().splitlines()
                  if line.strip() and not line.strip().startswith(("/*", "}"))]
        self.assertGreater(len(shared), 20, "共享块没读到规则行，守卫会空转")
        for path in site_css.TARGETS.values():
            outside = site_css.replace_region(path.read_text(encoding="utf-8"), "")
            with self.subTest(page=path.name):
                self.assertEqual([line for line in shared if line in outside], [],
                                 f"{path.name} 的标记区外还有共享规则的副本：跑一次生成器就会漂移")

    def test_reading_page_hooks_its_differences(self):
        """差异值只由 :root.reading 给出：类名掉了或用到了首页上，版心与栏高会一起串。"""
        self.assertIn(":root.reading", site_css.load_css())
        for key, path in site_css.TARGETS.items():
            html_tag = re.search(r"<html[^>]*>", path.read_text(encoding="utf-8"))
            self.assertIsNotNone(html_tag, f"{path.name} 的第一行不是 <html>")
            with self.subTest(page=path.name):
                self.assertEqual('class="reading"' in html_tag.group(0), key == "tutorial",
                                 f"{path.name} 的 <html> 带错了 reading 类：版心、栏高与顶栏 gap 会串页")

    def test_pages_stay_self_contained(self):
        """机主服务器上的副本是单文件（standalone.py 也只内联），外链样式表在那里取不到。旧树也绿，守的是不回退。"""
        for path in site_css.TARGETS.values():
            text = path.read_text(encoding="utf-8")
            with self.subTest(page=path.name):
                self.assertIsNone(re.search(r"<link[^>]*stylesheet|@import", text),
                                  f"{path.name} 引了外部样式表：共享样式要渲染进 <style>")

    def test_marker_checks_reject_a_broken_pair(self):
        text = site_css.TARGETS["home"].read_text(encoding="utf-8")
        site_css.check_markers(text, "home")
        for broken, why in ((text + "\n" + site_css.START + "\n" + site_css.END + "\n", "多出一对标记"),
                            (text.replace(site_css.START, ""), "少了开始标记"),
                            (text.replace(site_css.START, "@@").replace(site_css.END, site_css.START)
                             .replace("@@", site_css.END), "结束标记在前")):
            with self.subTest(why=why), self.assertRaises(ValueError):
                site_css.check_markers(broken, "home")


class SiteAssetTests(unittest.TestCase):
    """官网两页的图片引用：能内联进单文件，缓存键两页同步（#1086）。"""

    def test_every_page_image_can_be_inlined(self):
        """图标地址带 ?v= 版本参数后，旧正则要求 .png 紧贴引号，单文件导出会一张都不内联。"""
        text = site_css.TARGETS["home"].read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="((?:images|gui)/[^"]+)"', text)
        self.assertTrue(refs, "index.html 里没读到图片引用，守卫会空转")
        for ref in refs:
            with self.subTest(ref=ref):
                self.assertIsNotNone(standalone.INLINE.fullmatch(f'src="{ref}"'),
                                     f"{ref} 不会被 gui/standalone.py 内联：单文件导出会丢这张图")

    def test_version_query_is_not_part_of_the_inlined_path(self):
        """版本参数只是缓存键，交出去的文件名必须还是磁盘上的那一个。"""
        seen = []

        def uri(path):
            seen.append(path)
            return "DATA"

        out = standalone.inline('<link rel="icon" href="images/roudai-icon.png?v=0.4.3">', uri)
        self.assertEqual(seen, ["images/roudai-icon.png"], "查询串被当成文件名，导出时会去找不存在的文件")
        self.assertEqual(out, '<link rel="icon" href="DATA">')

    def test_cache_key_follows_the_release_version(self):
        """?v= 与 REL.version 同源：发版回填只改一处时，页面自己会自相矛盾（#1221）。旧树也绿，守的是不回退。"""
        version, _ = release_assets.read_page(
            site_css.TARGETS["home"].read_text(encoding="utf-8"))
        self.assertIsNotNone(version, "index.html 里读不出 REL.version，守卫会空转")
        for name, path in site_css.TARGETS.items():
            keys = {m.group(2) for m in release_meta.CACHE_KEY.finditer(
                path.read_text(encoding="utf-8"))}
            with self.subTest(page=name):
                self.assertEqual(keys, {version},
                                 f"{name} 的图标 ?v= 与 REL.version 不是同一个版本")

    def test_both_pages_share_one_cache_key(self):
        """?v= 是缓存键，两页各写一份：只改一页时，另一页的旧 404 照旧生效。"""
        versions = {name: set(re.findall(r'\?v=([^"&\s]+)', path.read_text(encoding="utf-8")))
                    for name, path in site_css.TARGETS.items()}
        home = versions["home"]
        self.assertEqual(len(home), 1, f"首页的版本参数不止一个：{versions}")
        self.assertEqual({name: found for name, found in versions.items() if found != home}, {},
                         f"两页的版本参数不同步：{versions}")


IMG_TAG = re.compile(r"<img\b[^>]*>")
IMG_SRC = re.compile(r"""\bsrc=["'][^"']*?img/(\d{2})\.jpg["']""")
IMG_ALT = re.compile(r"""\balt=["']([^"']*)["']""")


def tutorial_alts(text):
    """按标签读截图编号与 alt：属性顺序、引号风格都无关；同号重复或缺 alt 直接报错，不静默漏检。"""
    alts = {}
    for tag in IMG_TAG.findall(text):
        src = IMG_SRC.search(tag)
        if src is None:
            continue
        number = src.group(1)
        alt = IMG_ALT.search(tag)
        if alt is None or not alt.group(1).strip():
            raise AssertionError(f"img/{number} 没有可用的 alt 属性")
        if number in alts:
            raise AssertionError(f"img/{number} 在同一份文档里出现两次，另一份 alt 不会被比对")
        alts[number] = alt.group(1)
    return alts


class TutorialAltTests(unittest.TestCase):
    """页面与 README 的截图 alt 一致（#655）。"""

    README_SCREENSHOTS = 21  # 素材图张数：加图时这里、README_ONLY 与 README 一起改
    README_ONLY = ("10", "12", "15")  # 素材图多于页面用图的部分

    def page_alts(self):
        return tutorial_alts(TUTORIAL_PAGE.read_text(encoding="utf-8"))

    def readme_alts(self):
        return tutorial_alts(TUTORIAL_README.read_text(encoding="utf-8"))

    def test_guard_reads_both_documents(self):
        self.assertTrue(self.page_alts(), "android-tutorial.html 里没读到截图 alt，守卫会空转")
        self.assertTrue(self.readme_alts(), "README 里没读到截图 alt，守卫会空转")

    def test_readme_covers_every_screenshot(self):
        count = self.README_SCREENSHOTS
        self.assertEqual(sorted(self.readme_alts()), [f"{n:02d}" for n in range(1, count + 1)],
                         f"README 应覆盖 img/01 到 img/{count:02d} 全部 {count} 张")

    def test_page_uses_every_shared_screenshot(self):
        shared = [n for n in sorted(self.readme_alts()) if n not in self.README_ONLY]
        self.assertEqual(sorted(self.page_alts()), shared,
                         f"页面用图应为 {len(shared)} 张，README_ONLY = {self.README_ONLY}："
                         "增删截图时页面、README 与 README_ONLY 要一起改")

    def test_shared_screenshots_have_the_same_alt(self):
        page, docs = self.page_alts(), self.readme_alts()
        for number in sorted(set(page) & set(docs)):
            self.assertEqual(page[number], docs[number],
                             f"img/{number} 的 alt 在页面与 README 不一致：只改一处即漂移")

    def test_helper_reads_reordered_or_single_quoted_tags(self):
        self.assertEqual(tutorial_alts('<img alt="先 alt 后 src" src="docs/手机版教程/img/07.jpg">'),
                         {"07": "先 alt 后 src"},
                         "alt 写在 src 前面时读不到，守卫会把这张图当成缺失")
        self.assertEqual(tutorial_alts("<img src='img/07.jpg' alt='单引号'>"), {"07": "单引号"},
                         "单引号的 src 读不到，新增截图会绕过守卫")

    def test_helper_rejects_missing_or_empty_alt(self):
        for tag in ('<img src="img/20.jpg">',
                    '<img src="img/20.jpg" alt="">',
                    '<img src="img/20.jpg" alt="  ">'):
            with self.subTest(tag=tag), self.assertRaises(AssertionError):
                tutorial_alts(tag)

    def test_helper_rejects_a_number_used_twice(self):
        with self.assertRaises(AssertionError, msg="同一编号出现两次没报错"):
            tutorial_alts('<img src="img/01.jpg" alt="一">\n<img src="img/01.jpg" alt="二">')


class HostWordingDocTests(unittest.TestCase):
    """引擎照宿主取词之后，讲宿主边界的文档要跟着说，否则后来人按总览会把 `tool/host.py` 当成异物（#732）。

    `CLAUDE.md` 不在名单里：#1320 把它讲宿主取词的那一条搬进了 `docs/ARCHITECTURE.md` 的
    「函数级细节」，它自己不再讲这件事，也就没有「跟着说」的义务。
    """

    NAMING = ("docs/adr/0019-phone-second-execution-host.md", "docs/ARCHITECTURE.md", "CONTEXT.md",
              "android/README.md")

    def test_docs_name_the_wording_seam(self):
        for name in self.NAMING:
            self.assertIn("host.py", (ROOT / name).read_text(encoding="utf-8"),
                          f"{name} 没写清排查提示按宿主取词")

    def test_summary_docs_no_longer_claim_three_differences_only(self):
        """旧树不绿：总览与术语表原写着「差别只有三处」，措辞分叉加进来之后那句话是错的。"""
        for name in ("docs/ARCHITECTURE.md", "CONTEXT.md"):
            self.assertNotIn("差别只有三处", (ROOT / name).read_text(encoding="utf-8"),
                             f"{name} 仍写着宿主差别只有三处")


# 每个 Windows USB 提示：假设备、客户端该说的关键短语、FAQ 那一行该指的步号。
USB_HINT_CASES = (
    (("三星", "Galaxy S25", "OK", False), "没有调试接口", "第 3 步"),
    (("三星", "ADB Interface", "Error", True), "驱动没有装好", "第 5 步"),
    (("三星", "ADB Interface", "OK", True), "adb 没连上", "第 6 步"),
)


def faq_row(text, phrase):
    """FAQ 表格里写着该提示的那一行：三种提示各占一行，「怎么办」在同一行里。"""
    for line in text.splitlines():
        if line.startswith("|") and phrase in line:
            return line
    raise AssertionError(f"docs/06 的表格里没有「{phrase}」这一行")


class UsbHintDocTests(unittest.TestCase):
    """FAQ 节尾要与 Windows 上的三种 USB 提示对得上，别再只写两种（#785）。"""

    def test_faq_maps_every_hint_to_the_client_wording_and_a_step(self):
        faq = (ROOT / "docs/06-常见问题.md").read_text(encoding="utf-8")
        for device, phrase, step in USB_HINT_CASES:
            self.assertIn(phrase, app.usb_hint([device]), f"客户端不再这么说，词表要跟着改：{phrase}")
            self.assertIn(step, faq_row(faq, phrase), f"「{phrase}」那行没指到 {step}")

    def test_multi_phone_wording_stays_in_the_faq_vocabulary(self):
        """多台手机走另一条分支，措辞不同，但用的仍是 FAQ 里那三种（#785）。"""
        faq = (ROOT / "docs/06-常见问题.md").read_text(encoding="utf-8")
        both_off = app.usb_hint([("三星", "Galaxy S25", "OK", False), ("华为", "HUAWEI M30", "OK", False)])
        mixed = app.usb_hint([("三星", "ADB Interface", "OK", True), ("华为", "HUAWEI M30", "Error", True)])
        self.assertIn("三星（没有调试接口）", both_off)
        self.assertIn("华为（没有调试接口）", both_off)
        self.assertIn("三星（调试接口在，但 adb 没连上）", mixed)
        self.assertIn("华为（调试接口的驱动没有装好）", mixed)
        for phrase in ("没有调试接口", "驱动没有装好", "adb 没连上"):
            self.assertIn(phrase, faq, f"docs/06 没写客户端会显示的「{phrase}」")


ADAPT_CALL = re.compile(r"run\.py\s+(?:-s\s+(\S+)\s+)?adapt\s+([a-z]+)")
# 期望词表：survey / explore / check 收 `-s`，gen 不碰手机、不带。实现在 run.ADAPT_SERIAL_SUBS。
ADAPT_COMMANDS = {"survey": True, "explore": True, "gen": False, "check": True}


def adapt_calls(text):
    """文档里的每条 `run.py [-s 序列号] adapt <子命令>` → {子命令: 有没有 -s}。"""
    return {sub: bool(serial) for serial, sub in ADAPT_CALL.findall(text)}   # findall 用 '' 表示未参与的可选组


class AdaptCommandDocTests(unittest.TestCase):
    """三处文档（run.py 帮助、AGENTS.md、docs/04）的 adapt 写法要与 dispatch() 一致（#740）。"""

    GUIDES = ("AGENTS.md", "docs/04-给新机型写脚本.md")

    def test_frozen_word_list_matches_the_dispatcher(self):
        """期望词表冻结在上面的 ADAPT_COMMANDS；这条把它钉到实现那份，改 `dispatch()` 漏改这里就红。"""
        self.assertEqual(set(run.ADAPT_SERIAL_SUBS),
                         {sub for sub, serial in ADAPT_COMMANDS.items() if serial})

    def test_help_and_guides_use_the_same_order(self):
        """旧树也绿，守的是不回退：三处文档今天已经一致，改一处漏一处要红。

        钉的是 `-s` 前缀序。`adapt.py` 也接受 `adapt explore -s S`，但文档只写一种，读者才不会跟错。
        """
        sources = {"run.py 帮助": run.__doc__}
        sources.update({name: (ROOT / name).read_text(encoding="utf-8") for name in self.GUIDES})
        for name, text in sources.items():
            with self.subTest(name):
                self.assertEqual(adapt_calls(text), ADAPT_COMMANDS)

    def test_parser_sees_both_orders(self):
        """旧树也绿，守的是不回退：守卫本身要认得出带与不带 -s 两种写法，否则文本改了也照样绿。"""
        text = "run.py -s S adapt survey\nrun.py adapt gen x.tsv\nrun.py adapt --help\n"
        self.assertEqual(adapt_calls(text), {"survey": True, "gen": False})


STEP_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|[^|]*\|$")


def agents_steps(text):
    """AGENTS.md §3 标准流程表 → {步号: 命令}；adapt 那张表另算，不进来。"""
    main = text.split("### 新机型适配辅助")[0]
    return {int(m.group(1)): m.group(2) for m in map(STEP_ROW.match, main.splitlines()) if m}


def step_number(steps, token):
    """命令含 token 的步号；一步没有或不止一步都当文档写错。"""
    hits = [n for n, cmd in steps.items() if token in cmd]
    if len(hits) != 1:
        raise AssertionError("§3 里命令含 %r 的步应恰好一条，实为 %r" % (token, hits))
    return hits[0]


class AgentFlowOrderDocTests(unittest.TestCase):
    """agent 手册的执行顺序跟着客户端 `plan_tasks()` 走：挂起广告组件排在机型脚本之前（#981）。

    顺序本身以 `gui/app.py` 的 `plan_tasks()` 为准——msa 没挂起时它的开屏窗会抢走主题段前台
    （#968），客户端已前置，手册照抄同一顺序，否则跟着手册走的宿主仍会撞上同一个根因。
    """

    def agents_text(self):
        return (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    def test_suspend_precedes_the_recipe(self):
        steps = agents_steps(self.agents_text())
        self.assertLess(step_number(steps, "suspend"), step_number(steps, "recipe"))

    def test_quickapp_off_stays_after_its_detection(self):
        """旧树也绿，守的是不回退：`quickapp off` 消费 `quickapp` 的检测结果，客户端同样不前置。"""
        steps = agents_steps(self.agents_text())
        detect = [n for n, cmd in steps.items() if "quickapp" in cmd and "quickapp off" not in cmd]
        self.assertEqual(len(detect), 1, "§3 应有一行只做 quickapp 检测")
        self.assertLess(detect[0], step_number(steps, "quickapp off"))

    def test_step_numbers_are_contiguous(self):
        """旧树也绿，守的是不回退：某行被解析丢掉时步号会断开，静默漏行要红。"""
        steps = agents_steps(self.agents_text())
        self.assertEqual(sorted(steps), list(range(1, len(steps) + 1)))

    def test_cross_references_point_at_the_rows_they_mean(self):
        """表外按步号引用的两处：硬规则 9 的「§3 第 N 步」、§3 末尾的通用部分区间。"""
        text = self.agents_text()
        steps = agents_steps(text)
        rule = re.search(r"（§3 第 (\d+) 步）", text)
        self.assertIsNotNone(rule, "硬规则 9 应写着「§3 第 N 步」")
        self.assertIn("开发者模式", steps[int(rule.group(1))], "硬规则 9 引到的步不是「提醒关闭开发者模式」")

        span = re.search(r"跑通用部分（第 (\d+) 步与第 (\d+) 到 (\d+) 步", text)
        self.assertIsNotNone(span, "§3 末尾应写着通用部分的步号")
        first, low, high = (int(n) for n in span.groups())
        self.assertTrue({first, low, high} <= set(steps), "通用部分引用了不存在的步号")
        self.assertEqual(first, step_number(steps, "suspend"), "通用部分的第一段应是挂起广告组件")
        self.assertEqual(high, step_number(steps, "quickapp off"), "通用部分应跑到 quickapp off 为止")
        self.assertNotEqual(low, step_number(steps, "recipe"), "机型脚本那一步不属于通用部分")

    def test_docs02_asks_about_suspending_before_running_the_recipe(self):
        text = (ROOT / "docs/02-用AI智能体.md").read_text(encoding="utf-8")
        body = text.split("AI 会依次做这些事：")[1].split("\n## ")[0]
        steps = re.findall(r"^\d+\.\s*(.*)$", body, re.M)
        suspend = [i for i, s in enumerate(steps) if "挂起" in s]
        recipe = [i for i, s in enumerate(steps) if "跑机型脚本" in s]
        self.assertEqual((len(suspend), len(recipe)), (1, 1), "docs/02 的步骤列表应各有一条挂起与跑机型脚本")
        self.assertLess(suspend[0], recipe[0])

    def test_readme_command_block_suspends_before_the_recipe(self):
        """README 的「一次完整的流程」原先没有挂起，照它走会先跑机型脚本、再想起来挂。"""
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        block = text.split("## 一次完整的流程")[1].split("```")[1]
        cmds = [line for line in block.splitlines() if "run.py" in line]
        suspend = [i for i, line in enumerate(cmds) if " suspend " in line]
        recipe = [i for i, line in enumerate(cmds) if " recipe " in line]
        self.assertEqual((len(suspend), len(recipe)), (1, 1), "README 的命令块应各有一条挂起与跑机型脚本")
        self.assertLess(suspend[0], recipe[0])


class SharedAssetTests(unittest.TestCase):
    def test_site_and_client_use_the_same_logo(self):
        """站点与桌面版侧栏各存一份图标（打包目录不同，必须有副本）；旧树也绿，守的是换图时不会只改一处。"""
        self.assertEqual((ROOT / "gui/web/img/logo.png").read_bytes(),
                         (ROOT / "images/roudai-icon.png").read_bytes(),
                         "两处图标已不一致：换图时把 gui/web/img/logo.png 一并更新")


def rule_docs():
    return [CLAUDE, ROOT / "CODING_STANDARDS.md"] + sorted((ROOT / "docs/agents").glob("*.md"))


def flat_text(text):
    """抹掉空白、链接目标、围栏代码块与行内代码：命令与路径本来就该重复写，只比散文。"""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"\]\([^)\s]*\)", "]", text)
    text = re.sub(r"`[^`\n]*`", "", text)
    return re.sub(r"\s+", "", text)


def ngrams(text, size):
    return {text[i:i + size] for i in range(len(text) - size + 1)}


class ContributingDocTests(unittest.TestCase):
    """CONTRIBUTING.md 只做路由：五步流程、指针表、与 AGENTS.md 的分工（#851）。"""

    @classmethod
    def setUpClass(cls):
        if not CONTRIBUTING.exists():
            raise AssertionError("CONTRIBUTING.md 不存在")
        cls.text = CONTRIBUTING.read_text(encoding="utf-8")

    def test_file_fits_the_line_budget(self):
        """票面 #851 的验收项：全文 ≤ 80 行。"""
        lines = self.text.splitlines()
        self.assertLessEqual(len(lines), 80, "CONTRIBUTING.md 应 ≤ 80 行（票面 #851），实为 %d 行" % len(lines))

    def test_every_linked_path_exists(self):
        links = re.findall(r"\]\(([^)#\s]+)\)", self.text)
        self.assertTrue(links, "没读到任何相对链接，守卫会空转")
        missing = [link for link in links if not (ROOT / link).exists()]
        self.assertEqual(missing, [], "这些指向的文件不存在：" + "、".join(missing))

    def test_does_not_repeat_rule_prose(self):
        """散文与规则文档不重合 ≥40 字（票面 #851）：规则正文一处定义、其余只给指针。"""
        mine = flat_text(self.text)
        self.assertGreaterEqual(len(mine), REPEAT_WINDOW, "正文太短，守卫会空转")
        shared = set()
        for path in rule_docs():
            shared |= ngrams(flat_text(path.read_text(encoding="utf-8")), REPEAT_WINDOW)
        repeated = sorted(w for w in ngrams(mine, REPEAT_WINDOW) if w in shared)
        self.assertEqual(repeated, [],
                         "这些片段与规则文档逐字重合，改成指向：" + "、".join(repeated[:3]))

    def test_five_steps_and_the_audience_boundary(self):
        for step in ("开票", "分支", "提交", "回归", "PR"):
            with self.subTest(step=step):
                self.assertIn(step, self.text, "五步流程缺「%s」" % step)
        self.assertIn("用户侧", self.text, "要写清 AGENTS.md 面向用户侧 agent")
        self.assertIn("人类贡献者", self.text, "要写清本文件面向人类贡献者")

    def test_pointer_table_covers_the_entrypoints(self):
        """只查「规则在哪」那张表：表外顺带提到某个文件不算收录（票面 #851）。"""
        starts = [i for i, line in enumerate(self.text.splitlines()) if line.strip() == "## 规则在哪"]
        self.assertEqual(len(starts), 1, "应有一节「## 规则在哪」")
        table = "\n".join(self.text.splitlines()[starts[0]:])
        for path in ENTRY_DOCS:
            with self.subTest(path=path):
                self.assertIn("](%s)" % path, table, "指针表缺 %s" % path)


if __name__ == "__main__":
    unittest.main()
