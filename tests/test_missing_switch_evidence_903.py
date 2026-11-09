"""#903：机型脚本「点名的开关没出现」的失败行要自带页面证据。

HyperOS 3.0.x 上「广告服务」页找不到「个性化广告推荐」，9 份上报只有一句
「未识别全部目标开关，未操作」：分不清是改名了、页面是空的，还是页面根本没打开。
现在这条失败与入口失败的「停在 …／标题 N 个，开关 M 个／结构 …」同形，末尾按页面顺序
列出当次读到的开关标题。守卫的正文只留在 `recipe_kit.require_switches` 一处。
"""
import ast
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import fake_phone, load_recipe

GUARD = "未识别全部目标开关，未操作"
FOCUS = "com.android.settings/.ad.AdServiceSettings"

# 脚本里「关一组点名开关、缺一项就整段不动」的助手；改名或新增时要一起改这里。
ENTRYPOINTS = {"close_named", "close_with_plain_tap", "store_personalization"}

PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.settings" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="广告服务" bounds="[48,96][360,180]" />
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2340]">
{rows}
    </node>
  </node>
</hierarchy>"""


def row(title, top, checked=True):
    return (f'      <node class="android.widget.LinearLayout" bounds="[0,{top}][1080,{top + 120}]">'
            f'<node class="android.widget.TextView" text="{title}" bounds="[48,{top + 10}][600,{top + 110}]" />'
            f'<node class="android.widget.Switch" checkable="true" checked="{str(checked).lower()}" '
            f'bounds="[900,{top + 20}][1020,{top + 100}]" /></node>')


def phone(*rows):
    page = PAGE.format(rows="\n".join(rows))
    return fake_phone(size=(1080, 2340), stages=((0.0, page),), focus=((0.0, FOCUS),))


def recipes():
    return sorted((ROOT / "recipes").glob("*/recipe*.py"))


class MissingSwitchEvidenceTests(unittest.TestCase):
    def guard_message(self, recipe, names, *rows):
        scope, _ = load_recipe(phone(*rows), ROOT / "recipes" / recipe / "recipe.py")
        with self.assertRaises(RuntimeError) as caught:
            scope["close_named"](names, "系统·广告服务")
        return str(caught.exception)

    def test_missing_target_lists_the_switch_titles_in_page_order(self):
        message = self.guard_message("xiaomi-24129PN74C", ["个性化广告推荐"],
                                     row("个性化推荐", 320), row("广告服务记录", 460))
        self.assertIn(f"系统·广告服务：{GUARD}", message)
        self.assertIn(f"停在 {FOCUS}", message)
        self.assertIn("标题 1 个，开关 2 个", message)         # 与入口失败行同一份结构摘要
        self.assertIn("当次读到 2 个开关：个性化推荐、广告服务记录", message)

    def test_empty_page_is_distinguishable_from_unmatched_names(self):
        empty = self.guard_message("xiaomi-24129PN74C", ["个性化广告推荐"])
        renamed = self.guard_message("xiaomi-24129PN74C", ["个性化广告推荐"], row("个性化推荐", 320))
        self.assertIn("当次读到 0 个开关：无", empty)
        self.assertIn("当次读到 1 个开关：个性化推荐", renamed)

    def test_exact_match_family_reports_the_same_evidence(self):
        message = self.guard_message("vivo-V2417A", ["个性化广告推荐"],
                                     row("个性化推荐", 320), row("广告推荐", 460))
        self.assertIn(f"系统·广告服务：{GUARD}", message)
        self.assertIn("当次读到 2 个开关：个性化推荐、广告推荐", message)

    def test_empty_name_list_is_still_a_failure(self):
        """「整页开关」那条路（honor 的名单取页面上全部标题）一页空着同样是失败，空名单不许放行。"""
        p = phone(row("个性化推荐", 320))
        scope, _ = load_recipe(p, ROOT / "recipes" / "xiaomi-24129PN74C" / "recipe.py")
        with self.assertRaises(RuntimeError) as caught:
            scope["require_switches"]({"个性化推荐": True}, [], "系统·广告服务")
        self.assertIn(f"系统·广告服务：{GUARD}", str(caught.exception))
        self.assertIn("当次读到 1 个开关：个性化推荐", str(caught.exception))

    def test_present_target_keeps_the_old_output_and_builds_no_evidence(self):
        p = phone(row("个性化广告推荐", 320, checked=False))
        evidence = []
        real = p.page_evidence
        p.page_evidence = lambda *a, **k: evidence.append(a) or real(*a, **k)
        scope, out = load_recipe(p, ROOT / "recipes" / "xiaomi-24129PN74C" / "recipe.py")
        scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        self.assertEqual(evidence, [])
        self.assertIn("回读确认 0 项", out.getvalue())          # 成功路径仍走原来的收尾
        self.assertNotIn(GUARD, out.getvalue())

    def test_failure_still_records_the_step_and_the_exit_code(self):
        p = phone(row("个性化推荐", 320))
        scope, _ = load_recipe(p, ROOT / "recipes" / "xiaomi-24129PN74C" / "recipe.py")
        scope["ONLY"] = []                  # 装载时一段没跑，这里手动跑一个伪造段
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            @scope["step"]("伪造段")
            def _():
                scope["close_named"](["个性化广告推荐"], "系统·广告服务")
            code = fast.report_run(scope, p)
        self.assertEqual(scope["FAILED_STEPS"], ["伪造段"])
        self.assertEqual(code, 1)
        self.assertIn("当次读到 1 个开关：个性化推荐", printed.getvalue())


class SingleSourceTests(unittest.TestCase):
    def test_guard_wording_lives_only_in_recipe_kit(self):
        """文案留在 require_switches 一处：各自复制一份就会再分叉成两种输出形状。"""
        offenders = [path.relative_to(ROOT).as_posix() for path in recipes()
                     if GUARD in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])

    def test_switch_group_entrypoints_take_the_guard_from_recipe_kit(self):
        """关一组点名开关的助手都走注入的那份守卫；这三类是脚本里现存的全部入口。"""
        # 魅族的守卫是「目标开关未全部唯一识别」，判据与文案都不同，且另有失败摘要钩子。
        meizu = "meizu-MEIZU 21 Pro/recipe.py"
        missing = []
        for path in recipes():
            if path.parent.name + "/" + path.name == meizu:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef) or node.name not in ENTRYPOINTS:
                    continue
                called = {n.func.id for n in ast.walk(node)
                          if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                if "require_switches" not in called:
                    missing.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {node.name}")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
