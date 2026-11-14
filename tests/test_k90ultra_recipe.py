"""REDMI K90 Ultra（M332BF，#374）：机型匹配、版本钉住与四处入口差异。

脚本照社区报告者 @Sin1ery 的实测规格重写，本仓库没有这台机器，未在真机上复跑。
用例只护住「选得到这份脚本」「广告服务与浏览器直达」「只关点名开关」这三件事。
"""
import ast
import tomllib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/xiaomi/M332BF/M332BF.toml"
EXCEPTIONS = ROOT / "recipes/xiaomi/M332BF/M332BF.py"


class K90UltraRecipeTests(unittest.TestCase):
    def setUp(self):
        self.path = RECIPE
        self.source = self.path.read_text(encoding="utf-8")

    def phone(self):
        p = phone_mock()
        p.locked.return_value = False
        return p

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("M332BF", "Redmi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "M332BF")
        meta = run.recipe_meta(path)
        self.assertEqual(meta["models"], ["M332BF"])
        self.assertEqual(meta["build"], "OS4.0.4")
        self.assertEqual(meta["steps"], ["系统广告", "应用商店", "手机管家", "下载管理", "主题",
                                         "浏览器", "全局搜索", "负一屏", "天气和日历"])

    def test_build_accepts_this_phone_and_rejects_a_neighbouring_minor_version(self):
        phone = {"build": "CP2A.260605.016", "os": "OS4.0.4.0.XHPCNXM"}
        self.assertTrue(run.build_ok(phone, "OS4.0.4"))
        self.assertFalse(run.build_ok(phone, "OS4.0.5"))

    def test_ad_service_page_is_opened_without_the_dismiss_pass(self):
        # p.start() 启动后会跑 dismiss()，#374 的开关说明行含「关闭」会被当成弹窗 ✕ 点掉
        p = self.phone()
        load_recipe(p, self.path, ["系统广告"])
        p.d.shell.assert_any_call(
            "am start -f 0x10008000 -n com.android.settings/.ad.AdServiceSettings")
        p.start.assert_not_called()

    def test_ad_service_page_that_does_not_open_fails_the_step(self):
        p = self.phone()
        p.expect_page.return_value = False
        out = io.StringIO()
        scope, _ = load_recipe(p, self.path, ["系统广告"], out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])
        p.off.assert_not_called()
        self.assertIn("广告服务页没有打开", out.getvalue())

    def test_browser_opens_its_settings_page_directly(self):
        # 工具栏齿轮进的是首页编辑面板，主设置页是 BrowserSettingsActivity（#374）
        p = self.phone()
        load_recipe(p, self.path, ["浏览器"])
        self.assertEqual(p.start.call_args_list[0].args,
                         ("com.android.browser", ".BrowserSettingsActivity"))

    def test_every_switch_page_names_the_switches_it_touches(self):
        # 不整页全关：数据里的每一条 off 都点名 only；例外函数里的 p.off 同理。
        data = tomllib.loads(self.source)
        offs = [op for segment in data["segment"] for op in _walk(segment.get("ops", []))
                if op.get("kind") in ("off", "off_required")]
        self.assertTrue(offs)
        for op in offs:
            self.assertIn("only", op, f"{op['page']} 的 off 没有点名目标")
        named = {(op["page"], tuple(op["only"]), tuple(op.get("keep", []))) for op in offs}
        self.assertIn(("系统·广告服务", ("个性化广告推荐",), ()), named)
        self.assertIn(("浏览器·隐私和安全", ("个性化内容推荐", "个性化广告推荐"), ()), named)
        # 主题段整段留在例外函数里：那一条 off 的 only / keep 在源码里点名。
        source = EXCEPTIONS.read_text(encoding="utf-8")
        self.assertIn('p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")', source)
        calls = [n for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "off"]
        for call in calls:
            self.assertTrue({k.arg for k in call.keywords} & {"only", "keep"},
                            f"第 {call.lineno} 行的 off() 没有点名目标")

    def test_theme_gear_matches_the_exact_settings_entry(self):
        # 主题商店的「设置壁纸」也含「设置」，按包含匹配会点进壁纸页（沿用 #305 / #374）。
        # 齿轮实现在家族库的注入面里（#1244），脚本只靠静态 import 声明它用哪个库。
        self.assertIn('p.find("设置", exact=True, edge_ok="tab")',
                      "\n".join(path.read_text(encoding="utf-8")
                                for path in sorted((ROOT / "recipe_lib").glob("*.py"))))
        self.assertIn("import recipe_nav as nav", EXCEPTIONS.read_text(encoding="utf-8"))


def _walk(ops):
    """展开带分支的 op（if_entry / if_lib_any …）里的子表。"""
    for op in ops:
        yield op
        yield from _walk(op.get("ops", []))
        yield from _walk(op.get("else_ops", []))


if __name__ == "__main__":
    unittest.main()
