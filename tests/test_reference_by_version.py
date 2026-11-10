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

    def test_a_finer_recording_beats_a_matching_pinned_reference(self):
        # #969 的本质：设备 OS4.0.5.0 以固定参考的 OS4.0 开头，旧代码到此为止；
        # 同族里录在同一个 OS4.0.5.0 上的脚本从来进不了候选。
        write_recipe(self.root, "xiaomi-SAME", "OS4.0.5.0", 9)
        self.assertEqual(Path(self.pick("OS4.0.5.0.XPKCNXM")[0]).parent.name, "xiaomi-SAME")

    def test_a_family_script_as_coarse_as_the_reference_is_not_picked(self):
        """旧树也绿，守的是不回退：同族里另一份也只录到 OS4.0，与固定参考等长，对这台机同样贴。

        目录名字母序（xiaomi-COARSE2 排在 xiaomi-M154FF 前）不参与决定（#969）。
        """
        write_recipe(self.root, "xiaomi-COARSE2", "OS4.0", 9)
        self.assertEqual(Path(self.pick("OS4.0.5.0.XPKCNXM")[0]).parent.name, "xiaomi-M154FF")

    def test_among_equally_specific_scripts_more_steps_wins(self):
        write_recipe(self.root, "xiaomi-FEW", "OS3.0.308.0", 9)
        write_recipe(self.root, "xiaomi-MANY", "OS3.0.308.0", 12)
        self.assertEqual(Path(self.pick("OS3.0.308.0.WNBCNXM")[0]).parent.name, "xiaomi-MANY")

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

    def test_a_script_recorded_on_the_android_base_is_never_picked(self):
        # #942：底包是跨机型共享的 Android 构建号，同一代的小米机都报同一个。
        # 录了底包的脚本若参与同版本挑选，任何同代小米机都会被它命中。
        write_recipe(self.root, "xiaomi-ONBASE", "BP2A.250605.031", 10)
        path, reference = self.pick("BP2A.250605.031.A3", os_="OS3.0.500.0.WNBCNXM")
        self.assertEqual(Path(path).parent.name, "redmi-COARSE")
        self.assertTrue(reference)

    def test_scripts_on_the_same_base_with_different_roms_do_not_pick_each_other(self):
        write_recipe(self.root, "xiaomi-ONBASE", "BP2A.250605.031", 10)
        path, _ = self.pick("BP2A.250605.031.A3", os_="OS3.0.308.0.WNBCNXM")
        self.assertEqual(Path(path).parent.name, "xiaomi-NEW3")

    def test_the_same_rom_is_still_matched_when_the_base_differs(self):
        # 底包只决定落在哪个字段上比：两台机底包不同、ROM 相同，仍挑同一份脚本（#942）。
        a, _ = self.pick("BP2A.250605.031.A3", os_="OS3.0.308.0.WNBCNXM")
        b, _ = self.pick("CP2A.260605.016", os_="OS3.0.308.0.WNBCNXM")
        self.assertEqual(Path(a).parent.name, "xiaomi-NEW3")
        self.assertEqual(Path(b).parent.name, "xiaomi-NEW3")

    def test_an_unlabelled_script_never_matches_an_unlabelled_device(self):
        """旧树也绿，守的是不回退：空核心不能变成「匹配一切」。"""
        write_recipe(self.root, "xiaomi-UNLABELLED", "", 10)
        path, _ = self.pick("")
        self.assertEqual(Path(path).parent.name, "xiaomi-M154FF")


class XiaomiVersionCoreTests(unittest.TestCase):
    """小米的 ro.build.display.id 可能是 Android 底包，那一段不能当版本核心（#942）。"""

    def test_the_android_base_is_not_a_version_core(self):
        self.assertEqual(run.version_core("BP2A.250605.031", "xiaomi"), "")
        self.assertEqual(run.version_core("BP2A.250605.031.A3", "xiaomi"), "")
        self.assertEqual(run.version_core("CP2A.260605.016", "xiaomi"), "")
        # Android 12/13 的底包是三字母 + 一位数字，形状比 BP2A 短一档。
        self.assertEqual(run.version_core("SKQ1.210908.001", "xiaomi"), "")
        self.assertEqual(run.version_core("TKQ1.221114.001", "xiaomi"), "")

    def test_a_hyperos_version_is_still_a_core(self):
        """旧树也绿，守的是不回退：别把 ROM 版本号也当成底包吃掉。"""
        self.assertEqual(run.version_core("OS3.0.307.0.WOCCNXM", "xiaomi"), "OS3.0.307.0.WOCCNXM")
        self.assertEqual(run.version_core("OS3.0", "xiaomi"), "OS3.0")
        self.assertEqual(run.version_core("V816.0.1.0.UMCCNXM", "xiaomi"), "V816.0.1.0.UMCCNXM")


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

    def test_a_same_length_family_script_does_not_beat_the_pinned_reference(self):
        """旧树也绿，守的是不回退：固定参考只录到 16，同族里也写 16 的脚本不比它更贴。

        保固定参考——否则按目录名字母序（vivo-V2309A 排在 vivo-V2547DA 前）会被挑到
        一份纯属意外的脚本上（#969）。
        """
        write_recipe(self.root, "vivo-V2309A", "PD9999_A_16", 8)
        path, reference = self.pick("PD9999_A_16.1.0")
        self.assertEqual(Path(path).parent.name, "vivo-V2547DA")
        self.assertTrue(reference)

    def test_picks_the_script_recorded_on_an_aosp_build(self):
        # #580：Android 17 起 vivo 有的机器直接报 AOSP 平台构建号，没有机型前缀可切。
        write_recipe(self.root, "vivo-V2303A", "CP2A.260605.016", 7)
        path, reference = self.pick("CP2A.260605.016")
        self.assertEqual(Path(path).parent.name, "vivo-V2303A")
        self.assertTrue(reference)

    def test_the_aosp_build_id_is_not_pinned_to_one_generation(self):
        # 首字母跟着 Android 大版本走，下一代换个字母还得认得出。
        write_recipe(self.root, "vivo-V2303A", "CP2A.260605.016", 7)
        write_recipe(self.root, "vivo-V2400A", "DP2A.270105.001", 7)
        self.assertEqual(Path(self.pick("DP2A.270105.001")[0]).parent.name, "vivo-V2400A")

    def test_aosp_build_with_release_keys_matches_the_recorded_one(self):
        write_recipe(self.root, "vivo-V2303A", "CP2A.260605.016", 7)
        path, reference = self.pick("CP2A.260605.016(release-keys)")
        self.assertEqual(Path(path).parent.name, "vivo-V2303A")
        self.assertTrue(reference)

    def test_unmatched_aosp_build_falls_back_to_the_pinned_reference(self):
        self.assertEqual(Path(self.pick("CP2A.999999.999")[0]).parent.name, "vivo-V2547DA")

    def test_version_core_of_each_vivo_build_shape(self):
        self.assertEqual(run.version_core("PD2547D_A_17.1.10.2.W10", "vivo"), "17.1.10.2.W10")
        self.assertEqual(run.version_core("CP2A.260605.016", "vivo"), "CP2A.260605.016")
        self.assertEqual(run.version_core("DP2A.270105.001", "vivo"), "DP2A.270105.001")
        self.assertEqual(run.version_core("CP2A.260605.016(release-keys)", "vivo"), "CP2A.260605.016")
        # 裸机型名与空值都不是版本核心；空核心不参与比对，否则会命中同族一切脚本。
        self.assertEqual(run.version_core("V2303A", "vivo"), "")
        self.assertEqual(run.version_core("", "vivo"), "")
        # 只对 vivo 放宽，其他家族照旧要求机型名标记。
        self.assertEqual(run.version_core("CP2A.260605.016", "oppo"), "")


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


class RealXiaomiRecipeBuildTests(unittest.TestCase):
    """真实脚本的录制值要有区分力：回退成只剩大版本会让同族机型误借（#942）。"""

    def test_redmi_note_12_turbo_records_the_full_hyperos_version(self):
        path = str(ROOT / "recipes/redmi-23049RAD8C/recipe.py")
        self.assertEqual(run.recipe_meta(path)["build"], "OS3.0.5.0")


class CheckLineTests(unittest.TestCase):
    """check 的「机型脚本」一行要同时给出录制版本和设备版本。"""

    INFO = {"brand": "Xiaomi", "model": "ZZZ0000", "name": "Xiaomi ZZZ",
            "build": "OS3.0.308.0.WNBCNXM", "os": "OS3.0.308.0.WNBCNXM", "android": "16"}

    def check_output(self, recorded, name="xiaomi-M154FF", brand="Xiaomi"):
        with tempfile.TemporaryDirectory() as root:
            write_recipe(root, name, recorded, 9)
            recipe = str(Path(root, "recipes", name, "recipe.py"))
            out = io.StringIO()
            with patch.object(run, "ROOT", root), \
                 patch.object(run, "info", return_value=dict(self.INFO, brand=brand)) as info, \
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
        self.assertNotIn("非固定参考", out)

    def test_a_family_script_is_marked_as_not_the_pinned_reference(self):
        # 换到同族更贴的那份时要说清楚，报告者才知道要不要手动补入口（#969）。
        out = self.check_output("OS3.0.308", name="xiaomi-2512BPNDAC")
        self.assertIn("（同族同版本，非固定参考）", out)
        self.assertIn("录制版本 OS3.0.308，这台 OS3.0.308.0.WNBCNXM（相同）", out)

    def test_a_family_without_a_pinned_reference_is_not_marked(self):
        """旧树也绿，守的是不回退：三星 / 华为没有 REFERENCE 键，走的是「取同品牌第一份」。

        那条路没比过版本，不能标「同族同版本」（#969）。
        """
        out = self.check_output("One UI 4", name="samsung-SM9760", brand="Samsung")
        self.assertNotIn("非固定参考", out)

    def test_the_suffix_comes_from_the_real_pick(self):
        # 端到端：真跑 recipe_for，固定参考 OS4.0 命中后仍换成录在 OS4.0.5.0 上的同族脚本（#969）。
        device = dict(self.INFO, build="OS4.0.5.0.XPKCNXM", os="OS4.0.5.0.XPKCNXM")
        with tempfile.TemporaryDirectory() as root:
            write_recipe(root, "xiaomi-M154FF", "OS4.0", 9)
            write_recipe(root, "xiaomi-2512BPNDAC", "OS4.0.5.0", 9)
            out = io.StringIO()
            with patch.object(run, "ROOT", root), \
                 patch.object(run, "info", return_value=device), \
                 patch.object(run, "locked", return_value=False), \
                 patch.object(run, "input_blocked", return_value=False), \
                 patch.object(run, "ad_packages", return_value=[]), \
                 patch.object(run, "quickapps", return_value=[]), \
                 patch.object(run, "sh", return_value=""), \
                 patch.object(sys, "argv", ["run.py", "-s", "test", "check"]), \
                 contextlib.redirect_stdout(out):
                run.main()
        text = out.getvalue()
        picked = str(Path("recipes", "xiaomi-2512BPNDAC", "recipe.py"))
        self.assertIn(f"{picked}（同族同版本，非固定参考）", text)
        self.assertIn("这台 OS4.0.5.0.XPKCNXM（相同）", text)

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
