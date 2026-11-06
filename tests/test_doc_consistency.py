"""判定字段表与代码双向一致：新增判定漏改 ADR 时红（#467）；品牌连点表与单一来源一致（#654）。"""
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


class TutorialAltTests(unittest.TestCase):
    """页面与 README 的截图 alt 一致（#655）。"""

    README_ONLY = ("10", "12", "15")  # 素材图多于页面用图的部分

    @staticmethod
    def alts(text, pattern):
        import re
        return {m.group(1): m.group(2) for m in re.finditer(pattern, text)}

    def test_tutorial_alts_match_between_page_and_readme(self):
        html = (ROOT / "android-tutorial.html").read_text(encoding="utf-8")
        readme = (ROOT / "docs/手机版教程/README.md").read_text(encoding="utf-8")
        page = self.alts(html, r'手机版教程/img/(\d+)\.jpg[^>]*alt="([^"]*)"')
        docs = self.alts(readme, r'<img src="img/(\d+)\.jpg[^>]*alt="([^"]*)"')
        self.assertTrue(page, "android-tutorial.html 里没读到截图 alt，守卫会空转")
        self.assertTrue(docs, "README 里没读到截图 alt，守卫会空转")
        self.assertEqual(sorted(docs), [f"{n:02d}" for n in range(1, 20)],
                         "README 应覆盖 img/01 到 img/19 全部 19 张")
        self.assertEqual(sorted(page), [n for n in sorted(docs) if n not in self.README_ONLY],
                         "页面用图应为 16 张（10/12/15 仅 README 用）")
        for n in sorted(set(page) & set(docs)):
            self.assertEqual(page[n], docs[n], f"img/{n} 的 alt 在页面与 README 不一致：只改一处即漂移")


if __name__ == "__main__":
    unittest.main()
