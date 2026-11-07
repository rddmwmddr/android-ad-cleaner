"""机型脚本必须消费 p.setting() 的返回值（#776）。

fast.Phone.setting() 在搜索框没打开 / 输入失败 / 没搜到 / 结果没打开时只是
say("✗ …跳过") 再返回 False，不抛异常。脚本丢掉这个返回值，本段就静悄悄地什么都
没做：FAILED_STEPS 为空，退出码 0，结果页按「成功」处理，用户只能翻完整日志才发现。

判据分两层：形状走 AST（返回值有没有落进 `if not` / `require` / `bool` / `return` /
带 else 的 `if`），行为用假 Phone 驱动那几段（setting 失败时该进 FAILED_STEPS）。
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from fixtures import load_recipe, phone_mock

ROOT = Path(__file__).resolve().parents[1]

# 返回值落进这些调用就算检查过：bool 由外层结构再判，require 自己 raise。
CHECKING_CALLS = ("bool", "require")


def recipes():
    return sorted((ROOT / "recipes").glob("*/recipe*.py"))


def tree_of(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_name(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_setting(node):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setting"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "p")


def unchecked_setting_calls(tree):
    """返回 [(行号, 源码片段)]：返回值没人检查的 p.setting() 调用。"""
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    bad = [(node.lineno, ast.unparse(node)) for node in ast.walk(tree)
           if _is_setting(node) and not _consumes(node, parents)]
    return sorted(bad)


def _consumes(call, parents):
    """这次调用的返回值会不会被上层拿去判：逐层向上看它落在哪种结构里。"""
    node, negated = call, False
    parent = parents.get(node)
    while parent is not None:
        if (isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not)
                and parent.operand is node):
            node, negated = parent, True
        elif (isinstance(parent, ast.Call) and _call_name(parent.func) in CHECKING_CALLS
                and any(arg is node for arg in parent.args)):
            if _call_name(parent.func) == "require":
                return True                      # require 拿到 False 会自己 raise
            node = parent
        elif isinstance(parent, ast.Return):
            return True
        elif isinstance(parent, ast.If) and parent.test is node:
            # `if not <失败>` 自带失败分支；`if <成功>:` 要 else 才算有兜底。
            return negated or bool(parent.orelse)
        else:
            return False
        parent = parents.get(node)
    return False


# setting() 丢了就整段没做的七段（八处调用：PNM 与 2512BPNDAC 与 V2303A 各两处）。
# 第三项是该段第一个 setting() 的关键词：断言落在「这一段为什么没做成」上，
# 光看 FAILED_STEPS 非空分不清真报出了入口丢失，还是后面偶然撞上别的异常。
FAILING_SEGMENTS = [
    ("honor-PNM-AN10", "YOYO", "新闻资讯"),
    ("honor-PNM-AN10", "魔法画报", "魔法画报"),
    ("oneplus-PHK110", "广告跟踪", "设备标识与广告"),
    ("redmi-23049RAD8C", "系统广告", "系统广告"),
    ("xiaomi-2512BPNDAC", "系统广告", "广告服务"),
    ("vivo-V2303A", "系统广告", "广告与隐私"),
    ("vivo-V2303A", "阅图锁屏", "锁屏设置"),
]


# 一加脚本的 step 先读型号与版本，对不上就整段不跑（RESULTS 记 version_mismatch）。
BUILD_GATED = {"oneplus-PHK110": ("PHK110", "PHK110_16.0.5.1201")}


def recipe_of(name):
    return ROOT / "recipes" / name / "recipe.py"


class TheGuardItself(unittest.TestCase):
    """守卫要能红：喂几种写法，确认哪些算检查、哪些不算。"""

    def flagged(self, source):
        return [line for line, _ in unchecked_setting_calls(ast.parse(source))]

    def test_bare_call_is_unchecked(self):
        self.assertEqual(self.flagged('p.setting("系统广告")\n'), [1])

    def test_if_without_else_is_unchecked(self):
        self.assertEqual(self.flagged('if p.setting("系统广告"):\n    p.off()\n'), [1])

    def test_assignment_is_unchecked(self):
        self.assertEqual(self.flagged('ok = p.setting("系统广告")\n'), [1])

    def test_consumed_forms_are_checked(self):
        for source in (
            'if not p.setting("系统广告"):\n    raise RuntimeError("x")\n',
            'if p.setting("系统广告"):\n    p.off()\nelse:\n    pass\n',
            'require(p.setting("系统广告"), "x")\n',
        ):
            with self.subTest(source=source):
                self.assertEqual(self.flagged(source), [])

    def test_if_not_without_raise_still_passes(self):
        """守卫只看返回值有没有被拿去判，判不出 `if not` 里写的是 raise 还是 return。

        这条限制写在测试里而不是靠读者猜：把 `raise` 退回 `return` 不会让这一层返红，
        拦住它的是 `SegmentFailsWhenSettingFails` 与 `FallbackFailingTooFailsTheSegment`
        那几条行为用例。"""
        self.assertEqual(self.flagged('if not p.setting("系统广告"):\n    return\n'), [])


class EverySettingCallIsChecked(unittest.TestCase):
    def test_recipes_consume_the_return_value(self):
        found = recipes()
        self.assertTrue(found, "recipes/ 下一份机型脚本都没找到")
        for path in found:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                bad = unchecked_setting_calls(tree_of(path))
                self.assertEqual(
                    bad, [],
                    "\n".join(f"{path.relative_to(ROOT)}:{line} 丢了 p.setting() 的返回值：{src}"
                              for line, src in bad),
                )


class SegmentFailsWhenSettingFails(unittest.TestCase):
    def run_step(self, recipe, name):
        p = phone_mock()
        p.locked = lambda *a, **k: False
        p.setting = lambda *a, **k: False
        if recipe in BUILD_GATED:
            model, build = BUILD_GATED[recipe]
            p.d.shell = lambda cmd, timeout=60: SimpleNamespace(
                output=model if "ro.product.model" in cmd else build, exit_code=0)
        scope, out = load_recipe(p, recipe_of(recipe), only=[name])
        return scope, out.getvalue()

    def test_failed_setting_reaches_failed_steps(self):
        for recipe, name, keyword in FAILING_SEGMENTS:
            with self.subTest(recipe=recipe, step=name):
                scope, text = self.run_step(recipe, name)
                self.assertEqual(scope["FAILED_STEPS"], [name], text)
                self.assertIn(f"✗ 未完成：没搜到「{keyword}」", text)

    def test_a_miss_on_the_first_gate_does_not_skip_the_second(self):
        """「广告服务」与「系统广告」是两个互不依赖的总闸：一条搜不到，另一条照关。"""
        p = phone_mock()
        p.locked = lambda *a, **k: False
        p.setting = Mock(side_effect=[False, True])
        scope, out = load_recipe(p, recipe_of("xiaomi-2512BPNDAC"), only=["系统广告"])
        text = out.getvalue()
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"], text)
        self.assertEqual([c.kwargs["page"] for c in p.off.call_args_list], ["系统·系统广告"])

    def test_second_search_in_the_same_segment_is_checked_too(self):
        """2512BPNDAC 的「系统广告」连着搜两次：第一处通了，第二处没搜到照样要记失败。"""
        p = phone_mock()
        p.locked = lambda *a, **k: False
        p.setting = Mock(side_effect=[True, False])
        scope, out = load_recipe(p, recipe_of("xiaomi-2512BPNDAC"), only=["系统广告"])
        text = out.getvalue()
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"], text)
        self.assertIn("✗ 未完成：没搜到「系统广告」", text)


class SuccessPathUnchanged(unittest.TestCase):
    """重排后成功路径点的是同样几处开关（旧树也绿，守的是这次重排不误伤）。

    这四条是「`if p.setting(...):` 里那一整段」被提出来的地方——提错缩进就会漏拨，
    而失败分支的用例照样绿。
    """

    CASES = [
        ("redmi-23049RAD8C", "系统广告",
         [call(only=["个性化广告推荐"], page="系统·广告服务"),
          call(only=["系统工具广告"], page="系统·系统工具广告")]),
        ("xiaomi-2512BPNDAC", "系统广告",
         [call(only=["个性化广告推荐"], page="系统·广告服务"),
          call(only=["系统工具广告"], page="系统·系统广告")]),
        ("vivo-V2303A", "系统广告",
         [call(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")]),
        ("vivo-V2303A", "阅图锁屏",
         [call(only=["阅图锁屏", "锁屏横滑进入阅图"], page="阅图锁屏")]),
    ]

    def test_setting_success_keeps_the_same_clicks(self):
        for recipe, step, expected in self.CASES:
            with self.subTest(recipe=recipe, step=step):
                p = phone_mock()
                p.locked = lambda *a, **k: False
                p.setting = lambda *a, **k: True
                scope, text = load_recipe(p, recipe_of(recipe), only=[step])
                self.assertEqual(scope["FAILED_STEPS"], [], text)
                self.assertEqual(p.off.call_args_list, expected)


def unlocked_phone():
    """假 Phone：锁屏读成 False，其余交给 Mock。"""
    p = phone_mock()
    p.locked = lambda *a, **k: False
    return p


class FallbackStaysSilent(unittest.TestCase):
    """兜底走通时本段仍算成功（旧树也绿，守的是这次重排不回退）。"""

    def test_pmx110_search_hit_opens_page(self):
        p = unlocked_phone()
        p.setting = lambda *a, **k: True
        scope, _ = load_recipe(p, recipe_of("oppo-PMX110"))
        scope["page"], scope["row"], scope["system_settings"] = Mock(), Mock(), Mock()
        scope["ad_id_page"]()
        scope["page"].assert_called_once_with("设备标识与广告")
        scope["system_settings"].assert_not_called()

    def test_pmx110_search_miss_walks_the_menu(self):
        p = unlocked_phone()
        p.setting = lambda *a, **k: False
        scope, _ = load_recipe(p, recipe_of("oppo-PMX110"))
        scope["page"], scope["row"], scope["system_settings"] = Mock(), Mock(), Mock()
        scope["ad_id_page"]()
        scope["page"].assert_not_called()
        scope["system_settings"].assert_called_once()
        self.assertEqual(scope["row"].call_count, 2)

    def test_redmi_search_hit_skips_the_menu(self):
        p = unlocked_phone()
        p.setting = lambda *a, **k: True
        scope, _ = load_recipe(p, recipe_of("redmi-25060RK16C"), only=["系统广告"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.d.shell.assert_not_called()
        self.assertGreaterEqual(p.off.call_count, 1)

    def test_redmi_search_miss_walks_the_menu(self):
        p = unlocked_phone()
        p.setting = lambda *a, **k: False
        scope, _ = load_recipe(p, recipe_of("redmi-25060RK16C"), only=["系统广告"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.d.shell.assert_called_once_with("am start -f 0x10008000 -a android.settings.SETTINGS")

    def xiaomi_phone(self, search_hits):
        """close_named 前后各读一次开关，第二次读到已关才算核对通过。"""
        p = unlocked_phone()
        p.setting = lambda *a, **k: search_hits
        p.switches.side_effect = [[("个性化广告推荐", True, (0, 0))],
                                  [("个性化广告推荐", False, (0, 0))]]
        p.scroll_more.return_value = False
        return p

    def test_xiaomi_search_hit_skips_the_deeplink(self):
        p = self.xiaomi_phone(search_hits=True)
        scope, text = load_recipe(p, recipe_of("xiaomi-24129PN74C"), only=["系统广告"])
        self.assertEqual(scope["FAILED_STEPS"], [], text)
        p.d.shell.assert_not_called()

    def test_xiaomi_search_miss_uses_the_deeplink(self):
        p = self.xiaomi_phone(search_hits=False)
        scope, text = load_recipe(p, recipe_of("xiaomi-24129PN74C"), only=["系统广告"])
        self.assertEqual(scope["FAILED_STEPS"], [], text)
        p.d.shell.assert_called_once_with(
            "am start -f 0x10008000 -n com.android.settings/.ad.AdServiceSettings")


class FallbackFailingTooFailsTheSegment(unittest.TestCase):
    """设置搜索失败、兜底菜单也走不通时本段要记失败（#819）。

    `if not p.setting(...):` 里那几处兜底原本只是裸 `return` / `break`：段内一项没做，
    FAILED_STEPS 为空、退出码 0、结果页标「成功」。#776 的 AST 守卫只看返回值有没有被
    拿去判，区分不出兜底那一支写的是 raise 还是 return，拦住它们的是这几条行为用例。
    """

    def test_redmi_menu_fallback_failing_too_fails_the_segment(self):
        p = unlocked_phone()
        p.setting = lambda *a, **k: False
        p.entry = lambda *a, **k: False
        scope, out = load_recipe(p, recipe_of("redmi-25060RK16C"), only=["系统广告"])
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"], out.getvalue())
        self.assertIn("✗ 未完成：没找到「广告服务」入口", out.getvalue())

    def test_honor_menu_fallback_failing_too_fails_the_segment(self):
        p = unlocked_phone()
        p.setting = lambda *a, **k: False
        p.start = Mock(side_effect=RuntimeError("没有这个页面"))
        p.tap = Mock(return_value=False)
        scope, out = load_recipe(p, recipe_of("honor-PNM-AN10"), only=["广告跟踪"])
        self.assertEqual(scope["FAILED_STEPS"], ["广告跟踪"], out.getvalue())
        self.assertIn("✗ 未完成：没找到「广告与隐私」入口", out.getvalue())
        # 先落到「设置搜索失败 → 菜单三步」那一支，再从第一步失败出来；
        # 只断言 FAILED_STEPS 的话，把菜单链整段删成无条件 raise 也照样绿。
        p.d.shell.assert_called_once_with("am start -f 0x10008000 -a android.settings.SETTINGS")
        self.assertEqual(p.tap.call_args_list, [call("隐私和安全", exact=True)])


if __name__ == "__main__":
    unittest.main()
