"""#690：vocab.py gaps 查漏——只比要关的词条、按 key_of() 归一化、按分组列出，以及 CLI 的退出码。"""
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import vocab


def recipes(**files):
    """{"honor-A1": 源码} → 临时 recipes 目录。"""
    tmp = tempfile.TemporaryDirectory()
    for name, src in files.items():
        folder = Path(tmp.name, name)
        folder.mkdir()
        folder.joinpath("recipe.py").write_text(textwrap.dedent(src), encoding="utf-8")
    return tmp


class GapsTest(unittest.TestCase):
    def gaps(self, **files):
        tmp = recipes(**files)
        self.addCleanup(tmp.cleanup)
        return vocab.gaps(tmp.name, "honor-A1")

    def test_peer_words_missing_from_this_script_are_listed_with_source_and_page(self):
        text = self.gaps(**{
            "honor-A1": 'p.off(only=["甲"], page="音乐·广告推荐")',
            "honor-B2": 'p.off(only=["甲", "乙"], page="音乐·广告推荐")',
        })
        self.assertIn("## 音乐", text)
        self.assertIn("乙", text)
        self.assertIn("honor-B2:1", text)
        self.assertIn("B2", text)
        self.assertIn("音乐·广告推荐", text)
        self.assertNotIn("甲", text)

    def test_spacing_variants_are_not_a_gap(self):
        text = self.gaps(**{
            "honor-A1": 'p.off(only=["WiFi 连接"], page="音乐·页")',
            "honor-B2": 'p.off(only=["WiFi连接"], page="音乐·页")',
        })
        self.assertIn("没有差异", text)
        self.assertNotIn("WiFi", text)

    def test_only_words_meant_to_be_closed_are_compared(self):
        """同页保留项与「要开」的保护类开关不算漏：它们不在这台机上独立成立。"""
        text = self.gaps(**{
            "honor-A1": 'p.off(only=["甲"], page="音乐·页")',
            "honor-B2": 'p.off(only=["甲", "减少广告"], keep=["推送消息"], page="音乐·页")',
        })
        self.assertIn("没有差异", text)
        self.assertNotIn("减少广告", text)
        self.assertNotIn("推送消息", text)

    def test_other_families_are_ignored(self):
        text = self.gaps(**{
            "honor-A1": 'p.off(only=["甲"], page="音乐·页")',
            "xiaomi-M1": 'p.off(only=["乙"], page="商店·设置")',
        })
        self.assertIn("没有差异", text)

    def test_trailing_slash_and_case_do_not_change_the_answer(self):
        """shell 补全会给尾斜杠，macOS 的盘默认大小写不敏感：都得认出同一个目录，不能把本机的词当成漏项。"""
        tmp = recipes(**{"honor-A1": 'p.off(only=["甲"], page="音乐·页")',
                         "honor-B2": 'p.off(only=["甲", "乙"], page="音乐·页")'})
        self.addCleanup(tmp.cleanup)
        exact = vocab.gaps(tmp.name, "honor-A1")
        for variant in ("honor-A1/", "HONOR-a1"):
            self.assertEqual(vocab.gaps(tmp.name, variant), exact, variant)

    def test_script_with_no_readable_words_is_flagged(self):
        text = self.gaps(**{"honor-A1": 'p.off(only=names, page="音乐·页")',
                            "honor-B2": 'p.off(only=["乙"], page="音乐·页")'})
        self.assertIn("一条词条都没读出来", text)

    def test_unresolvable_peer_calls_are_named_not_silently_ignored(self):
        text = self.gaps(**{"honor-A1": 'p.off(only=["甲"], page="音乐·页")',
                            "honor-B2": 'p.off(only=names, page="音乐·页")'})
        self.assertIn("没参与比对", text)
        self.assertIn("`honor-B2/recipe.py:1`", text)

    def test_unknown_folder_and_brand_are_distinct_errors(self):
        tmp = recipes(**{"honor-A1": 'p.off(only=["甲"], page="音乐·页")',
                         "unknownbrand-A1": 'p.off(only=["甲"], page="音乐·页")'})
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(FileNotFoundError):
            vocab.gaps(tmp.name, "honor-NOPE")
        with self.assertRaises(ValueError):
            vocab.gaps(tmp.name, "unknownbrand-A1")

    def test_group_order_follows_the_entry_sheet_and_uncategorized_goes_last(self):
        text = self.gaps(**{
            "honor-A1": 'p.off(only=["甲"], page="音乐·页")',
            "honor-B2": 'p.off(only=["乙"], page="音乐·页")\np.off(only=["丙"], page="没见过·页")',
        })
        self.assertLess(text.index("## 音乐"), text.index("## 未归类"))


class CommandLineTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tool" / "vocab.py"), *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_missing_folder_exits_one_with_stderr(self):
        done = self.run_cli("gaps", "nope")
        self.assertEqual(done.returncode, 1)
        self.assertIn("nope", done.stderr)

    def test_unknown_arguments_print_usage(self):
        done = self.run_cli("gaps")
        self.assertEqual(done.returncode, 1)
        self.assertIn("用法", done.stderr)


if __name__ == "__main__":
    unittest.main()
