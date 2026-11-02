"""没有本型号脚本时，参考脚本按录制版本在同族里挑（#319）。不用手机。"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run


def write_recipe(root, name, build, steps, filename="recipe.py"):
    d = Path(root, "recipes", name)
    d.mkdir(parents=True, exist_ok=True)
    body = "".join(f'@step("步骤{i}")\n' for i in range(steps))
    Path(d, filename).write_text(f'BUILD = "{build}"\n{body}', encoding="utf-8")


class XiaomiFamilyTests(unittest.TestCase):
    """HyperOS 的录制版本就是 ro.build.display.id / ro.mi.os.version.incremental 的前缀。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        write_recipe(self.root, "xiaomi-M154FF", "OS4.0", 9)
        write_recipe(self.root, "xiaomi-NEW3", "OS3.0.308", 9)
        write_recipe(self.root, "redmi-COARSE", "OS3.0", 9)

    def tearDown(self):
        self._tmp.cleanup()

    def pick(self, build, brand="Xiaomi", os_=None):
        with patch.object(run, "ROOT", self.root):
            return run.recipe_for("ZZZ0000", brand, {"build": build, "os": build if os_ is None else os_})

    def test_picks_the_script_recorded_on_the_same_version(self):
        path, reference = self.pick("OS3.0.308.0.WNBCNXM")
        self.assertEqual(Path(path).parent.name, "xiaomi-NEW3")
        self.assertTrue(reference)

    def test_matches_the_hyperos_version_when_display_id_is_the_android_base(self):
        # 真实小米机型：ro.build.display.id 是 BP2A…，HyperOS 版本号在 ro.mi.os.version.incremental
        path, _ = self.pick("BP2A.250605.031.A3", os_="OS3.0.308.0.WNBCNXM")
        self.assertEqual(Path(path).parent.name, "xiaomi-NEW3")

    def test_a_more_specific_recording_beats_a_coarser_one(self):
        # 两条都能前缀命中；OS3.0.308 比 OS3.0 更贴这台
        self.assertEqual(Path(self.pick("OS3.0.308.0.WNBCNXM")[0]).parent.name, "xiaomi-NEW3")
        # 只有粗录制对得上时用它
        self.assertEqual(Path(self.pick("OS3.0.500.0.WNBCNXM")[0]).parent.name, "redmi-COARSE")

    def test_a_narrower_script_does_not_replace_a_wider_one(self):
        write_recipe(self.root, "xiaomi-NARROW", "OS3.0.308.0", 5)
        self.assertEqual(Path(self.pick("OS3.0.308.0.WNBCNXM")[0]).parent.name, "xiaomi-NEW3")

    def test_falls_back_to_the_pinned_reference_when_no_version_matches(self):
        path, reference = self.pick("OS5.0.1")
        self.assertEqual(Path(path).parent.name, "xiaomi-M154FF")
        self.assertTrue(reference)

    def test_the_pinned_reference_is_kept_when_it_already_matches(self):
        self.assertEqual(Path(self.pick("OS4.0.5.0")[0]).parent.name, "xiaomi-M154FF")

    def test_no_device_info_means_no_version_picking(self):
        with patch.object(run, "ROOT", self.root):
            path, reference = run.recipe_for("ZZZ0000", "Xiaomi")
        self.assertEqual(Path(path).parent.name, "xiaomi-M154FF")
        self.assertTrue(reference)

    def test_version_variants_are_not_candidates(self):
        write_recipe(self.root, "xiaomi-NEW3", "OS3.0.308.0", 9, filename="recipe_v2.py")
        path, _ = self.pick("OS3.0.308.0.WNBCNXM")
        self.assertEqual(Path(path).name, "recipe.py")


class OppoFamilyTests(unittest.TestCase):
    """ro.build.display.id 以型号开头，跨机型要先抽掉型号才能比版本。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        write_recipe(self.root, "oppo-PLP120", "PLP120_16.0.9", 9)
        write_recipe(self.root, "oneplus-PHK110", "PHK110_16.0.5.1201", 5)
        write_recipe(self.root, "oppo-PMX110", "PMX110_17.0.0", 9)

    def tearDown(self):
        self._tmp.cleanup()

    def pick(self, build, brand="OnePlus"):
        with patch.object(run, "ROOT", self.root):
            return run.recipe_for("ZZZ0000", brand, {"build": build, "os": ""})

    def test_a_narrower_script_does_not_replace_the_wider_reference(self):
        path, reference = self.pick("PJX110_16.0.5.1201(CN01)")
        self.assertEqual(Path(path).parent.name, "oppo-PLP120")
        self.assertTrue(reference)

    def test_a_different_patch_level_is_not_the_same_version(self):
        path, reference = self.pick("PJX110_16.0.5.1001(CN01)")
        self.assertEqual(Path(path).parent.name, "oppo-PLP120")
        self.assertTrue(reference)

    def test_picks_a_same_version_script_across_the_family_alias(self):
        path, reference = self.pick("PJD000_17.0.0.100(CN01)")
        self.assertEqual(Path(path).parent.name, "oppo-PMX110")
        self.assertTrue(reference)


class VivoFamilyTests(unittest.TestCase):
    """OriginOS 的版本在 _A_ 之后。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        write_recipe(self.root, "vivo-V2547DA", "PD2547D_A_16", 7)
        write_recipe(self.root, "vivo-V2547A", "PD2547B_A_17.1.10.2", 8)

    def tearDown(self):
        self._tmp.cleanup()

    def pick(self, build):
        with patch.object(run, "ROOT", self.root):
            return run.recipe_for("ZZZ0000", "iQOO", {"build": build, "os": ""})

    def test_compares_the_version_after_the_underscore(self):
        path, reference = self.pick("PD9999_A_17.1.10.2")
        self.assertEqual(Path(path).parent.name, "vivo-V2547A")
        self.assertTrue(reference)

    def test_falls_back_when_the_version_is_not_recorded_anywhere(self):
        self.assertEqual(Path(self.pick("PD9999_A_18")[0]).parent.name, "vivo-V2547DA")


class HonorFamilyTests(unittest.TestCase):
    """荣耀的 BUILD 以机型名开头；参考脚本的 BUILD 还没标。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        write_recipe(self.root, "honor-PNM-AN10", "", 13)
        write_recipe(self.root, "honor-WKL-AN20", "WKL-AN20 11.0.0.111(SP7C00E110R101P7)", 13)

    def tearDown(self):
        self._tmp.cleanup()

    def pick(self, build):
        with patch.object(run, "ROOT", self.root):
            return run.recipe_for("ZZZ0000", "HONOR", {"build": build, "os": ""})

    def test_compares_after_the_model_prefix(self):
        path, reference = self.pick("WKL-AN20 11.0.0.111(SP7C00E110R101P7)")
        self.assertEqual(Path(path).parent.name, "honor-WKL-AN20")
        self.assertTrue(reference)

    def test_an_unlabelled_reference_never_matches(self):
        self.assertEqual(Path(self.pick("PNM-AN10 10.0.0.1")[0]).parent.name, "honor-PNM-AN10")


class MeizuFamilyTests(unittest.TestCase):
    """魅族的版本在 Flyme 之后。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        write_recipe(self.root, "meizu-MEIZU 21 Pro", "Flyme 12.6.0.0A", 8)
        write_recipe(self.root, "meizu-MEIZU 22", "Flyme 13.0.0.0A", 8)

    def tearDown(self):
        self._tmp.cleanup()

    def pick(self, build):
        with patch.object(run, "ROOT", self.root):
            return run.recipe_for("ZZZ0000", "MEIZU", {"build": build, "os": ""})

    def test_compares_the_version_after_the_flyme_prefix(self):
        path, reference = self.pick("M621Q Flyme 13.0.0.0A")
        self.assertEqual(Path(path).parent.name, "meizu-MEIZU 22")
        self.assertTrue(reference)

    def test_falls_back_when_the_version_is_not_recorded_anywhere(self):
        self.assertEqual(Path(self.pick("M621Q Flyme 14.0.0.0A")[0]).parent.name, "meizu-MEIZU 21 Pro")


class CheckLineTests(unittest.TestCase):
    """check 的「机型脚本」一行要同时给出录制版本和设备版本。"""

    INFO = {"brand": "Xiaomi", "model": "ZZZ0000", "name": "Xiaomi ZZZ",
            "build": "OS3.0.308.0.WNBCNXM", "os": "OS3.0.308.0.WNBCNXM", "android": "16"}

    def check_output(self, recorded):
        with tempfile.TemporaryDirectory() as root:
            write_recipe(root, "xiaomi-REF", recorded, 9)
            recipe = str(Path(root, "recipes", "xiaomi-REF", "recipe.py"))
            out = io.StringIO()
            with patch.object(run, "ROOT", root), \
                 patch.object(run, "info", return_value=dict(self.INFO)) as info, \
                 patch.object(run, "recipe_for", return_value=(recipe, True)) as recipe_for, \
                 patch.object(run, "locked", return_value=False) as locked, \
                 patch.object(run, "input_blocked", return_value=False) as input_blocked, \
                 patch.object(run, "ad_packages", return_value=[]) as ad_packages, \
                 patch.object(run, "quickapps", return_value=[]) as quickapps, \
                 patch.object(run, "sh", return_value="") as sh, \
                 patch.object(sys, "argv", ["run.py", "-s", "test", "check"]), \
                 contextlib.redirect_stdout(out):
                run.main()
            for stub in (info, recipe_for, locked, input_blocked, ad_packages, quickapps):
                stub.assert_called_once()
            sh.assert_called()
        return out.getvalue()

    def test_same_version_is_stated_as_a_fact(self):
        out = self.check_output("OS3.0.308")
        self.assertIn("录制版本 OS3.0.308", out)
        self.assertIn("这台 OS3.0.308.0.WNBCNXM（相同）", out)
        self.assertIn("recipe --ref", out)

    def test_different_version_says_so(self):
        out = self.check_output("OS4.0")
        self.assertIn("这台 OS3.0.308.0.WNBCNXM（不同）", out)
        self.assertNotIn("（相同）", out)

    def test_unlabelled_reference_says_unlabelled(self):
        out = self.check_output("")
        self.assertIn("录制版本 未标", out)
        self.assertNotIn("（相同）", out)
        self.assertNotIn("（不同）", out)

    def test_unknown_device_version_is_not_called_different(self):
        with tempfile.TemporaryDirectory() as root:
            write_recipe(root, "xiaomi-REF", "OS3.0.308", 9)
            recipe = str(Path(root, "recipes", "xiaomi-REF", "recipe.py"))
            out = io.StringIO()
            unknown = dict(self.INFO, build="", os="")
            with patch.object(run, "ROOT", root), \
                 patch.object(run, "info", return_value=unknown), \
                 patch.object(run, "recipe_for", return_value=(recipe, True)), \
                 patch.object(run, "locked", return_value=False), \
                 patch.object(run, "input_blocked", return_value=False), \
                 patch.object(run, "ad_packages", return_value=[]), \
                 patch.object(run, "quickapps", return_value=[]), \
                 patch.object(run, "sh", return_value=""), \
                 patch.object(sys, "argv", ["run.py", "-s", "test", "check"]), \
                 contextlib.redirect_stdout(out):
                run.main()
        text = out.getvalue()
        self.assertIn("这台版本未读到", text)
        self.assertNotIn("（不同）", text)


if __name__ == "__main__":
    unittest.main()
