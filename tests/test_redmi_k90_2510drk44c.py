"""REDMI K90 基础款（2510DRK44C）：按型号登记进 18 Pro Max 那份 OS4.0 脚本（#929）。

2026-11-10 社区实测（Issue #929）：报告者借这份参考脚本跑通九段中的八段、关 16 项，挂起
`com.miui.systemAdSolution` 后主题段补关 2 项，累计 18 项。本仓库没有这台机器、未在真机复跑，
所以用例只护住三件事：选得到这份脚本、版本对得上、登记不改变开关决策。
"""
import ast
import tomllib
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run

RECIPE = ROOT / "recipes/xiaomi/M154FF/M154FF.toml"


class RedmiK90BaseRecipeTests(unittest.TestCase):
    def test_this_model_selects_the_recipe_without_safe_mode(self):
        path, reference = run.recipe_for("2510DRK44C", "Redmi")
        self.assertEqual(Path(path).parent.name, "M154FF")
        self.assertFalse(reference)

    def test_registration_keeps_the_other_recorded_models(self):
        models = run.recipe_meta(RECIPE)["models"]
        self.assertIn("2510DRK44C", models)
        self.assertIn("M154FF", models)
        self.assertIn("2608BPX34C", models)
        self.assertEqual(len(models), 3)

    def test_recorded_build_matches_this_phone(self):
        """旧树也绿，守的是登记后不进安全模式：BUILD 的 `OS4.0` 前缀要罩住这台的 `OS4.0.5.0`。"""
        this_phone = {"build": "CP2A.260605.016", "os": "OS4.0.5.0.XPKCNXM"}
        build = run.recipe_meta(RECIPE)["build"]
        self.assertEqual(build, "OS4.0")
        self.assertTrue(run.build_ok(this_phone, build))

    def test_recipe_command_runs_this_recipe_without_the_safe_mode_warning(self):
        props = {"ro.product.brand": "Redmi",
                 "ro.product.model": "2510DRK44C",
                 "ro.build.display.id": "CP2A.260605.016",
                 "ro.mi.os.version.incremental": "OS4.0.5.0.XPKCNXM",
                 "ro.build.version.release": "17"}

        def fake_sh(serial, cmd):
            return props.get(cmd[len("getprop "):], "") if cmd.startswith("getprop ") else ""

        out = io.StringIO()
        with patch.object(run, "sh", side_effect=fake_sh) as sh, \
                patch.object(run, "locked", return_value=False) as locked, \
                patch.object(run, "py", return_value=0) as child, \
                contextlib.redirect_stdout(out):
            rc = run.cmd_recipe("SERIAL", [])
        self.assertEqual(rc, 0)
        self.assertNotIn("安全模式", out.getvalue())
        self.assertEqual(child.call_args[0], ("fast.py", "-s", "SERIAL", "run", str(RECIPE)))
        self.assertNotIn("--ref", child.call_args[0])
        # 型号与锁屏状态都经这两个桩读出来；它们若不再被调用，上面的断言就退化成对着旧路径自证。
        sh.assert_called()
        locked.assert_called()

    def test_registration_adds_no_steps(self):
        """旧树也绿，守的是登记不往这份共享脚本里添段：同底包的另两台会跟着多跑一段。"""
        self.assertEqual(run.recipe_meta(RECIPE)["steps"],
                         ["系统广告", "应用商店", "手机管家", "下载管理", "主题",
                          "浏览器", "全局搜索", "负一屏", "天气和日历"])

    def test_every_off_call_is_scoped_to_named_switches(self):
        """旧树也绿，守的是这份共享脚本的不变式，也是「登记等价于当本型号脚本跑」的前提：
        每一处 `p.off()` 都点名开关，没有整页全关（数据里缺 `only` 或写了 `page_wide`）。"""
        data = tomllib.loads(RECIPE.read_text(encoding="utf-8"))
        unscoped = [op["page"] for segment in data["segment"] for op in _walk(segment.get("ops", []))
                    if op.get("kind") in ("off", "off_required")
                    and ("only" not in op or op.get("page_wide"))]
        self.assertEqual(unscoped, [])
        # 扫完数据，例外函数里那几段也要守同一件事（主题 / 下载管理在 code= 里）。
        exception = (RECIPE.parent / (RECIPE.stem + ".py")).read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(exception)):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "off"):
                continue
            only = next((k.value for k in n.keywords if k.arg == "only"), None)
            self.assertIsNotNone(only, f"例外函数第 {n.lineno} 行的 off() 没有点名目标")
            self.assertFalse(isinstance(only, ast.Constant) and only.value is None, n.lineno)


def _walk(ops):
    """展开带分支的 op（if_entry / if_lib_any …）里的子表。"""
    for op in ops:
        yield op
        yield from _walk(op.get("ops", []))
        yield from _walk(op.get("else_ops", []))


if __name__ == "__main__":
    unittest.main()
