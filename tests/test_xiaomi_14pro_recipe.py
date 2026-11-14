"""Xiaomi 14 Pro（23116PN5BC）：按型号登记进 13 Ultra 那份 OS3.0.308 脚本（#317）。

2026-10-29 社区实测：报告者手工指定这份脚本并强制安全模式，九段跑通、19 项开关关闭且每步回读，
只有浏览器「搜索设置」一页没命中目标开关（票面列为 out of scope）。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run

RECIPE = ROOT / "recipes/xiaomi/2304FPN6DC/2304FPN6DC.toml"


class Xiaomi14ProRecipeTests(unittest.TestCase):
    def test_fourteen_pro_model_selects_this_recipe_without_safe_mode(self):
        path, reference = run.recipe_for("23116PN5BC", "Xiaomi")
        self.assertEqual(Path(path), RECIPE)
        self.assertFalse(reference)

    def test_registration_keeps_the_recorded_model(self):
        models = run.recipe_meta(RECIPE)["models"]
        self.assertIn("2304FPN6DC", models)
        self.assertIn("23116PN5BC", models)
        self.assertEqual(len(models), 2)

    def test_recorded_build_matches_this_phone(self):
        # 报告者的 ro.build.display.id 是 Android 底包，HyperOS 版本号在 ro.mi.os.version.incremental。
        this_phone = {"build": "BP2A.250605.031.A3", "os": "OS3.0.308.0.WNBCNXM"}
        build = run.recipe_meta(RECIPE)["build"]
        self.assertEqual(build, "OS3.0.308")
        self.assertTrue(run.build_ok(this_phone, build))
        # 18 系列的 OS4 不是这台机的系统：版本对不上时仍要进安全模式。
        self.assertFalse(run.build_ok(this_phone, "OS4.0"))

    def test_recipe_command_runs_this_recipe_without_the_safe_mode_warning(self):
        # 从 getprop 到 cmd_recipe 整条链：型号认出来、HyperOS 版本对得上，就不该提示安全模式，
        # 也不该给子进程加 --ref。
        props = {"ro.product.brand": "Xiaomi",
                 "ro.product.model": "23116PN5BC",
                 "ro.build.display.id": "BP2A.250605.031.A3",
                 "ro.mi.os.version.incremental": "OS3.0.308.0.WNBCNXM",
                 "ro.build.version.release": "16"}

        def fake_sh(serial, cmd):
            return props.get(cmd[len("getprop "):], "") if cmd.startswith("getprop ") else ""

        out = io.StringIO()
        with patch.object(run, "sh", side_effect=fake_sh), \
                patch.object(run, "locked", return_value=False), \
                patch.object(run, "py", return_value=0) as child, \
                contextlib.redirect_stdout(out):
            rc = run.cmd_recipe("SERIAL", [])
        self.assertEqual(rc, 0)
        self.assertNotIn("安全模式", out.getvalue())
        self.assertEqual(child.call_args[0], ("fast.py", "-s", "SERIAL", "run", str(RECIPE)))
        self.assertNotIn("--ref", child.call_args[0])

    def test_registration_adds_no_steps(self):
        self.assertEqual(run.recipe_meta(RECIPE)["steps"],
                         ["系统广告", "应用商店", "手机管家", "下载管理", "主题",
                          "浏览器", "全局搜索", "负一屏", "天气和日历"])


if __name__ == "__main__":
    unittest.main()
