"""文档与单一来源一致：ADR 字段表（#467）、品牌连点表（#654）、教程截图 alt（#655）、站点与侧栏图标同源（#669）。"""
import re
import sys
import unittest
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import channel_policy as policy
import gen_brand_taps as gen

ADR = ROOT / "docs/adr/0006-channel-classification.md"
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
                             "只改 JSON 一处后跑 python tool/gen_brand_taps.py")

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
        for key, path in gen.TARGETS.items():
            indents = {"start": set(), "end": set()}
            for line in path.read_text(encoding="utf-8").splitlines():
                kind = "start" if line.strip() == gen.START else "end" if line.strip() == gen.END else None
                if kind:
                    indents[kind].add(line[:len(line) - len(line.lstrip())])
            self.assertEqual(indents["start"], indents["end"],
                             f"{path.name} 的 brand-taps 标记缩进不一致")


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

    README_SCREENSHOTS = 19  # 素材图张数：加图时这里、README_ONLY 与 README 一起改
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


class SharedAssetTests(unittest.TestCase):
    def test_site_and_client_use_the_same_logo(self):
        """站点与桌面版侧栏各存一份图标（打包目录不同，必须有副本）；旧树也绿，守的是换图时不会只改一处。"""
        self.assertEqual((ROOT / "gui/web/img/logo.png").read_bytes(),
                         (ROOT / "images/roudai-icon.png").read_bytes(),
                         "两处图标已不一致：换图时把 gui/web/img/logo.png 一并更新")


if __name__ == "__main__":
    unittest.main()
