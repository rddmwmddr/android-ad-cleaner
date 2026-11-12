"""引擎注入的机型脚本前导（#838）：段包装、跳过出口、失败台账、锁屏中止与失败现场。

只断言外部行为——装载一份脚本、跑、看台账与退出码；不断言段包装内部调用了谁。
脚本夹具不写本地前导，用的就是注入的那一份（#839 迁移之后真实脚本长这样）。

「整页关闭的段落」也在这里：`skip_in_safe_mode()` 是前导给整页关闭提供的那一个出口，
它在一份脚本里怎么用（段首第一句）、安全模式下跳过什么、非安全模式下照旧做什么，
都是这个出口的契约（#909、#947）。
"""
import ast
import contextlib
import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adapt
import adb_link
import fast
import recipe_kit
from fixtures import (EMPTY_PAGE, Clock, fake_phone, install_clock, load_recipe,
                      phone_mock, phone_stub)

# 三段的骨架：甲跑完、乙按脚本怎么写怎么跑、丙永远不该被执行（锁屏场景）
SECTIONS = '''
CALLS = []

@step("甲")
def _a():
    CALLS.append("甲")

@step("乙")
def _b():
    BODY

@step("丙")
def _c():
    CALLS.append("丙")
'''


def phone(**fields):
    """phone_stub 补上段首锁屏与收尾台账要用的两项；默认不锁屏。"""
    p = phone_stub("S")
    p.locked = lambda *_a, **_k: False
    for name, value in fields.items():
        setattr(p, name, value)
    return p


def write_recipe(directory, body='CALLS.append("乙")'):
    path = Path(directory, "recipe.py")
    path.write_text(SECTIONS.replace("BODY", body), encoding="utf-8")
    return path


def locked_after(allowed):
    """前 `allowed` 次读锁屏返回假，之后返回真——不往测试夹具加参数，覆盖假设备的实例属性。"""
    calls = {"n": 0}

    def locked(*_a, **_k):
        calls["n"] += 1
        return calls["n"] > allowed

    return locked, calls


class RunTests(unittest.TestCase):
    def run_recipe(self, body='CALLS.append("乙")', only=(), **fields):
        p = phone(**fields)
        with tempfile.TemporaryDirectory() as directory:
            path = write_recipe(directory, body)
            scope, out = load_recipe(p, path, only)
        return scope, out.getvalue(), p

    def test_a_clean_run_leaves_both_ledgers_empty(self):
        scope, printed, p = self.run_recipe()
        self.assertEqual(scope["CALLS"], ["甲", "乙", "丙"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertIn("== 甲", printed)
        with patch("builtins.print"):
            self.assertEqual(fast.report_run(scope, p), 0)

    def test_skip_records_the_skipped_ledger_only(self):
        scope, printed, p = self.run_recipe('skip("型号不匹配，跳过")')
        self.assertEqual(scope["SKIPPED_STEPS"], ["乙"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("· 跳过：型号不匹配，跳过", printed)
        with patch("builtins.print"):
            self.assertEqual(fast.report_run(scope, p), 0)

    def test_a_plain_error_lands_in_the_failed_ledger(self):
        scope, printed, p = self.run_recipe('require(False, "入口「设置」没找到")')
        self.assertEqual(scope["FAILED_STEPS"], ["乙"])
        self.assertIn("✗ 未完成：入口「设置」没找到", printed)
        self.assertEqual(scope["CALLS"], ["甲", "丙"])       # 一段失败不中断整批
        with patch("builtins.print"):
            self.assertEqual(fast.report_run(scope, p), 1)

    def test_the_script_defining_its_own_preamble_still_wins(self):
        """迁移之前 40 份脚本都本地定义：注入的名字被覆盖，行为一个字节都不变。

        旧树也绿，守的是不回退：这条用例证明的是「本地定义优先」，注入前它同样成立。
        本地这一份不接异常，所以装载当场就抛出来——注入的那份会接住并记台账。"""
        local = '''
FAILED_STEPS = []

def step(name):
    def decorate(action):
        p.calls.append(name)
        action()
        return action
    return decorate

@step("甲")
def _a():
    p.calls.append("甲")
    raise RuntimeError("本地的段包装不记台账")
'''
        p = phone()
        p.calls = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(local, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "本地的段包装不记台账"):
                load_recipe(p, path, ())
        self.assertEqual(p.calls, ["甲", "甲"])


class SkipStepOverrideTests(unittest.TestCase):
    def test_a_script_that_only_replaces_the_skip_class_still_skips(self):
        """脚本只重定义跳过异常类、仍用注入的段包装：抛的和接的必须是同一个类。"""
        local = '''
class SkipStep(Exception):
    pass

@step("甲")
def _a():
    skip("型号不匹配，跳过")
'''
        p = phone()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(local, encoding="utf-8")
            scope, _ = load_recipe(p, path, ())
        self.assertEqual(scope["SKIPPED_STEPS"], ["甲"])
        self.assertEqual(scope["FAILED_STEPS"], [])


class LockedScreenTests(unittest.TestCase):
    def run_recipe(self, allowed):
        locked, calls = locked_after(allowed)
        p = phone(locked=locked)
        with tempfile.TemporaryDirectory() as directory:
            path = write_recipe(directory)
            scope, out = load_recipe(p, path, ())
        return scope, out.getvalue(), p, calls

    def test_a_locked_screen_halts_the_batch_and_every_later_step_lands_in_one_ledger(self):
        """第二段开始前锁屏：它记未完成，第三段记「未执行」，两份都在 FAILED_STEPS 里。"""
        scope, printed, p, _ = self.run_recipe(allowed=1)
        self.assertEqual(scope["CALLS"], ["甲"])                  # 锁屏之后一段都没跑
        self.assertEqual(scope["FAILED_STEPS"], ["乙", "丙"])
        self.assertEqual(scope["HALTED_STEPS"], ["丙"])
        self.assertIn("✗ 未完成：手机锁屏了", printed)
        self.assertIn("· 未执行：前一段中止了整批", printed)
        with patch("builtins.print"):
            self.assertEqual(fast.report_run(scope, p), 1)

    def test_no_screen_is_read_after_the_halt(self):
        _, _, _, calls = self.run_recipe(allowed=1)
        self.assertEqual(calls["n"], 2, "中止之后仍在读锁屏")

    def test_the_tail_prints_the_halted_steps_on_a_second_line(self):
        """第一行与 failed_steps 事件仍是全部段名，第二行只列中止之后没轮到的那些。"""
        scope = {"FAILED_STEPS": ["乙", "丙"], "HALTED_STEPS": ["丙"]}
        p = phone()
        with patch.dict("os.environ", {"AAC_EVENTS": ""}), patch("builtins.print") as out:
            self.assertEqual(fast.report_run(scope, p), 1)
        self.assertEqual([c.args[0] for c in out.call_args_list],
                         ["未完成步骤：乙、丙", "因中止未执行：丙"])

    def test_a_halt_in_the_first_step_still_prints_both_lines(self):
        scope = {"FAILED_STEPS": ["甲"], "HALTED_STEPS": ["甲"]}
        p = phone()
        with patch.dict("os.environ", {"AAC_EVENTS": ""}), patch("builtins.print") as out:
            self.assertEqual(fast.report_run(scope, p), 1)
        self.assertEqual([c.args[0] for c in out.call_args_list],
                         ["未完成步骤：甲", "因中止未执行：甲"])


class OnlyListTests(unittest.TestCase):
    def test_the_only_list_is_read_when_a_step_is_wrapped(self):
        """装载之后再改名单：段包装被调用时读执行作用域，拿得到新值。"""
        p = phone()
        with tempfile.TemporaryDirectory() as directory:
            path = write_recipe(directory)
            scope, _ = load_recipe(p, path)                       # 不给 only → 一段都不跑
        self.assertEqual(scope["CALLS"], [])
        with contextlib.redirect_stdout(io.StringIO()):
            scope["ONLY"] = ["甲"]
            scope["step"]("甲")(scope["_a"])
        self.assertEqual(scope["CALLS"], ["甲"])
        with contextlib.redirect_stdout(io.StringIO()):
            scope["ONLY"] = []
            scope["step"]("丙")(scope["_c"])
        self.assertEqual(scope["CALLS"], ["甲", "丙"])

    def test_a_step_gated_by_the_only_list_inside_its_body_sees_the_live_value(self):
        """WKL-AN20 那种在段内读 ONLY 自门控的脚本，迁移后仍要读到当前名单。"""
        body = 'CALLS.append("乙" if ONLY == ["乙"] else "门控外")'
        p = phone()
        with tempfile.TemporaryDirectory() as directory:
            path = write_recipe(directory, body)
            scope, _ = load_recipe(p, path, ["乙"])
        self.assertEqual(scope["CALLS"], ["乙"])


class DeviceGuardTests(unittest.TestCase):
    """`guard()`：脚本自己声明「这台机对不上就不跑这一段」，由前导在段入口调用。"""

    GUARDED = '''
CALLS = []

def guard():
    GUARD()


@step("甲")
def _a():
    CALLS.append("甲")

@step("乙")
def _b():
    CALLS.append("乙")
'''

    def run_guarded(self, guard_body):
        p = phone()
        script = self.GUARDED.replace("GUARD()", guard_body)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, out = load_recipe(p, path, ())
        return scope, out.getvalue()

    def test_a_guard_that_skips_leaves_the_failed_ledger_empty(self):
        scope, printed = self.run_guarded('skip("型号不匹配，跳过")')
        self.assertEqual(scope["CALLS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], ["甲", "乙"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("· 跳过：型号不匹配，跳过", printed)

    def test_a_guard_that_raises_lands_in_the_failed_ledger(self):
        scope, printed = self.run_guarded('require(False, "型号或系统版本不符")')
        self.assertEqual(scope["CALLS"], [])
        self.assertEqual(scope["FAILED_STEPS"], ["甲", "乙"])
        self.assertIn("✗ 未完成：型号或系统版本不符", printed)

    def test_a_guard_that_passes_lets_the_step_run(self):
        scope, _ = self.run_guarded("pass")
        self.assertEqual(scope["CALLS"], ["甲", "乙"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])


class SafeModePageWideTests(unittest.TestCase):
    """`skip_in_safe_mode()`：整页关闭的段落在安全模式下一个开关都点不到，按跳过收尾（#909）。"""

    SCRIPT = '''
CALLS = []

@step("甲")
def _a():
    skip_in_safe_mode()
    CALLS.append("甲")
'''

    def run_step(self, safe_mode):
        p = phone(safe_mode=safe_mode)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(self.SCRIPT, encoding="utf-8")
            scope, out = load_recipe(p, path, ())
        return scope, out.getvalue()

    def test_safe_mode_skips_the_step_with_the_page_wide_reason(self):
        scope, printed = self.run_step(True)
        self.assertEqual(scope["CALLS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], ["甲"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("· 跳过：安全模式不做整页全关", printed)

    def test_without_safe_mode_the_step_runs(self):
        """旧树也绿，守的是不回退：出口在非安全模式下必须是惰性的。"""
        scope, printed = self.run_step(False)
        self.assertEqual(scope["CALLS"], ["甲"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertNotIn("跳过", printed)


class StepWrapTests(unittest.TestCase):
    """`wrap()`：脚本声明「这一段在它的界面守卫里跑」，等价于以前每份脚本各写一次 `with safe_ui():`。"""

    WRAPPED = '''
from contextlib import contextmanager

CALLS = []

@contextmanager
def wrap():
    CALLS.append("进入")
    try:
        yield
    finally:
        CALLS.append("离开")


@step("甲")
def _a():
    CALLS.append("甲")
'''

    def test_the_action_runs_inside_the_wrap(self):
        p = phone()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(self.WRAPPED, encoding="utf-8")
            scope, _ = load_recipe(p, path, ())
        self.assertEqual(scope["CALLS"], ["进入", "甲", "离开"])

    def test_a_failure_inside_the_action_leaves_the_wrap(self):
        p = phone()
        script = self.WRAPPED.replace("CALLS.append(\"甲\")", 'require(False, "入口没找到")')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, _ = load_recipe(p, path, ())
        self.assertEqual(scope["CALLS"], ["进入", "离开"])
        self.assertEqual(scope["FAILED_STEPS"], ["甲"])


class FailureDetailTests(unittest.TestCase):
    """`detail()`：失败时再多打一行脚本自己的现场摘要（页面结构、计数器之类）。"""

    def test_the_detail_line_follows_a_failed_step(self):
        script = '''
def detail():
    return "当前页 com.example/.Main；标题 3 个"


@step("甲")
def _a():
    require(False, "入口没找到")
'''
        p = phone()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, out = load_recipe(p, path, ())
        self.assertIn("✗ 未完成：入口没找到\n  · 当前页 com.example/.Main；标题 3 个", out.getvalue())
        self.assertEqual(scope["FAILED_STEPS"], ["甲"])


class ResultsLedgerTests(unittest.TestCase):
    """脚本自带 `RESULTS` 时，前导按同一个结局给它记一条 —— 分段结果台账不该只活在本地副本里。"""

    WITH_RESULTS = '''
CALLS = []
RESULTS = []

@step("甲")
def _a():
    CALLS.append("甲")

@step("乙")
def _b():
    BODY

@step("丙")
def _c():
    CALLS.append("丙")
'''

    def run_results(self, body='CALLS.append("乙")', allowed=None):
        p = phone(**({"locked": locked_after(allowed)[0]} if allowed is not None else {}))
        script = self.WITH_RESULTS.replace("BODY", body)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, _ = load_recipe(p, path, ())
        return scope

    def test_every_step_lands_in_the_ledger_with_its_outcome(self):
        scope = self.run_results('skip("按约定跳过")')
        self.assertEqual(scope["RESULTS"], [("甲", "完成"), ("乙", "跳过"), ("丙", "完成")])

    def test_a_failed_step_is_recorded_as_unfinished(self):
        scope = self.run_results('require(False, "入口没找到")')
        self.assertEqual(scope["RESULTS"], [("甲", "完成"), ("乙", "未完成"), ("丙", "完成")])

    def test_a_halted_step_is_recorded_as_not_executed(self):
        scope = self.run_results(allowed=1)
        self.assertEqual(scope["RESULTS"], [("甲", "完成"), ("乙", "未完成"), ("丙", "未执行")])

    def test_a_step_body_returning_false_is_recorded_as_unfinished(self):
        """四份脚本的段体用 `return False` 表示「这一段没做全」，旧段包装据此记 incomplete。

        迁移前它只影响分段结果、不影响退出码；迁移后照旧，所以这里同时断言两份台账。"""
        scope = self.run_results("return False")
        self.assertEqual(scope["RESULTS"], [("甲", "完成"), ("乙", "未完成"), ("丙", "完成")])
        self.assertEqual(scope["FAILED_STEPS"], [])


class DeviceLostTests(unittest.TestCase):
    def test_a_lost_connection_goes_back_to_the_engine(self):
        """断线不是「这一段没做成」：段包装不记台账，交回引擎整轮停下（ADR-0029）。"""
        script = '''
import adb_link

@step("甲")
def _a():
    raise adb_link.DeviceLost("adb 断了")
'''
        p = phone()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            with self.assertRaises(adb_link.DeviceLost):
                load_recipe(p, path, ())


class InjectionPointTests(unittest.TestCase):
    """三处执行点注入同一份：引擎跑脚本、适配自检、测试装载。这里验前两处，装载由本文件其余用例覆盖。"""

    def test_the_run_branch_injects_the_preamble(self):
        clock = Clock()
        install_clock(fast, clock)
        p = fake_phone(clock=clock, stages=[(0.0, EMPTY_PAGE)])
        out, code = io.StringIO(), 0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "recipe.py")
            path.write_text(SECTIONS.replace('BODY', 'raise RuntimeError("入口「设置」没找到")'),
                            encoding="utf-8")
            with patch.dict(os.environ, {"AAC_BACKUPS": tmp}), contextlib.redirect_stdout(out):
                try:
                    fast.execute(p, "run", [str(path)])
                except SystemExit as error:
                    code = error.code
        self.assertEqual(code, 1)
        self.assertIn("未完成步骤：乙", out.getvalue())

    def test_the_self_check_reads_the_injected_ledger(self):
        p = fake_phone(stages=[(0.0, EMPTY_PAGE)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "草稿.py")
            path.write_text(SECTIONS.replace('BODY', 'raise RuntimeError("入口「设置」没找到")'),
                            encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                report = adapt.check_draft(p, str(path))
        self.assertEqual(report["failed_steps"], ["乙"])


# 安全模式下的整页关闭段落（#909）：`off()` 按设计只关脚本点名的开关，整页关闭的段落
# 在安全模式下一个开关都点不到，段落随后回读「必须全关」就必然把它记成语义错误的失败。
# 现在这类段落在安全模式下一律按跳过结束，非安全模式下的行为与改前一致。

# AST 检测器认得出的形状：不带 `only` 的 `p.off(...)`。它既是检测器的期望集，也是行为用例的一部分。
OFF_CALL_WIDE = [
    ("recipes/oppo-PKT110/recipe.py", "广告跟踪"),
    ("recipes/oppo-PKT110/recipe.py", "应用建议"),
    ("recipes/oppo-PLP120/recipe.py", "广告跟踪"),
    ("recipes/oneplus-PLR110/recipe.py", "广告跟踪"),
    ("recipes/oneplus-PYB110/recipe.py", "广告跟踪"),
    ("recipes/oneplus-PHK110/recipe.py", "广告跟踪"),
    ("recipes/oneplus-PKX110/recipe.py", "广告跟踪"),
    ("recipes/oppo-PKH110/recipe.py", "广告跟踪"),
    ("recipes/realme-RMX3700/recipe.py", "广告跟踪"),
    ("recipes/realme-RMX3700/recipe.py", "应用建议"),
    ("recipes/realme-RMX3888/recipe.py", "广告跟踪"),
    ("recipes/honor-PNM-AN10/recipe.py", "广告跟踪"),
    ("recipes/honor-PNM-AN10/recipe.py", "桌面文件夹"),
    ("recipes/honor-PNM-AN10/recipe.py", "主题"),
]

# AST 认不出的整页关闭：UI 里点「全部关闭」、名单在运行时按整页读出来再点名关（#947）。
# 它们与上面那份同样是整页关闭，行为用例一条都不能少；期望集不含它们，结构断言才不会因此变红。
OTHER_WIDE = [
    ("recipes/honor-CLE-AN00/recipe.py", "广告跟踪"),
    ("recipes/oppo-PMA110/recipe.py", "广告跟踪"),
    ("recipes/oppo-PLG110/recipe.py", "广告跟踪"),
    ("recipes/honor-WKL-AN20/recipe.py", "广告跟踪"),
]

# 整段只做整页关闭的段：安全模式下必须走跳过出口
PAGE_WIDE = OFF_CALL_WIDE + OTHER_WIDE

# 这几份脚本自带 `guard()`：安全模式下它们在段入口就先按「型号 / 版本不同」跳过，
# 走不到整页关闭那一段，跳过原因不是本票这一句。
GUARDED_RECIPES = {
    "recipes/oneplus-PHK110/recipe.py",
    "recipes/oneplus-PKX110/recipe.py",
    "recipes/oppo-PKH110/recipe.py",
    "recipes/realme-RMX3700/recipe.py",
}

# 也有 `guard()`，但漏的那条路正是「同型号同版本 + --ref」：型号守卫会放行，
# 要证明跳过出口生效就得把型号与版本喂对（#947）。
NEEDS_GUARD_SHELL = {"recipes/honor-WKL-AN20/recipe.py"}


def run_recipe_step(device, path, only):
    """装载一份真实脚本并跑给定的段，带回执行作用域与它打印的东西。"""
    scope, out = load_recipe(device, ROOT / path, only)
    return scope, out.getvalue()


class _AnyFocus(str):
    """认任何 Activity 的焦点替身：桩里不抄脚本的 Activity 常量，所以对照用例证明不了落点对不对。

    落点判据由 `page()` / `start` 那批用例守；这里只关心「非安全模式下整页关闭照做」。
    包名部分照原样给，`WKL-AN20` 的页面判据要看 `focus().split("/")[0]`。"""

    def __eq__(self, other):
        return True


def recipe_scope(path):
    """只装载不跑段：脚本的 `MODELS` / `BUILD` 等字面量从这里取，测试不另抄一份。"""
    scope, _ = load_recipe(phone_mock(), ROOT / path, None)
    return scope


def guard_shell(path):
    """喂 `guard()` 的型号与版本。"""
    scope = recipe_scope(path)
    model, build = scope["MODELS"][0], scope["BUILD"]

    def shell(command, timeout=None):
        value = model if "ro.product.model" in command else build
        return SimpleNamespace(output=value, exit_code=0)

    return shell


def touchless(path=None):
    """安全模式下这一段本该一步都不做：所有动作都留在 Mock 上，可以逐个查。

    `path` 在 `NEEDS_GUARD_SHELL` 里时把型号与版本喂对：那支脚本的型号守卫排在段体之前，
    跳过出口要等它放行才轮得到（#947）。"""
    p = phone_mock()
    p.safe_mode = True
    p.locked.return_value = False
    if path in NEEDS_GUARD_SHELL:
        p.d.shell.side_effect = guard_shell(path)
    return p


class SafeModeSkipTests(unittest.TestCase):
    def test_every_page_wide_step_skips_in_safe_mode(self):
        for path, name in PAGE_WIDE:
            with self.subTest(recipe=path, step=name):
                p = touchless(path)
                scope, printed = run_recipe_step(p, path, [name])
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual(scope["SKIPPED_STEPS"], [name])
                if path not in GUARDED_RECIPES:
                    self.assertIn("安全模式不做整页全关", printed)
                p.off.assert_not_called()

    def test_the_run_still_exits_zero(self):
        """跳过台账不参与退出码：这一段没做成，但也没出错。"""
        p = touchless()
        scope, _ = run_recipe_step(p, "recipes/oppo-PKT110/recipe.py", ["广告跟踪"])
        self.assertEqual(fast.report_run(scope, p), 0)

    def test_untitled_switches_are_left_alone_in_safe_mode(self):
        """vivo 的「个性化推荐」页只有无标题开关：自己按坐标点的那条路同样不进安全模式（#909）。

        它不是 `p.off(page=…)`，所以不受引擎那条限制；段落里还关着点名开关，不能整段跳过。"""
        for path in ("recipes/vivo-V2303A/recipe.py",
                     "recipes/vivo-V2547DA/recipe_android17.py"):
            with self.subTest(recipe=path):
                p = touchless()
                p.switches.return_value = [("", True, (1, 2))]
                scope, _ = load_recipe(p, ROOT / path, only=None)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(scope["off_unnamed"]("商店·个性化推荐"), 0)
                self.assertIn("安全模式不做整页全关", out.getvalue())
                p.click.assert_not_called()

    def test_nothing_on_the_page_is_touched_before_the_skip(self):
        """跳过发生在进页之前：不拉起 App、不点入口、不读开关。"""
        for path, name in PAGE_WIDE:
            with self.subTest(recipe=path, step=name):
                p = touchless(path)
                run_recipe_step(p, path, [name])
                p.start.assert_not_called()
                p.switches.assert_not_called()
                p.tap.assert_not_called()
                p.off.assert_not_called()
                if path not in NEEDS_GUARD_SHELL and path not in GUARDED_RECIPES:
                    p.d.shell.assert_not_called()   # 带 guard() 的那几支在段入口读 getprop，不碰页面


class AdTrackingTests(unittest.TestCase):
    """PKT110 的广告跟踪 / 应用建议：安全模式下不再「先声明不关、再判没关掉」。"""

    def make(self):
        state = [("示例应用", True, (1, 2))]
        p = phone_mock()
        p.locked.return_value = False
        p.switches.side_effect = lambda *a, **k: list(state)
        p.scroll_more.return_value = False

        def off(only=None, keep=(), page="", max_screens=40, **kw):
            state[:] = [(t, False, xy) for t, _, xy in state]

        p.off.side_effect = off
        return p, state

    def test_ad_tracking_reports_a_skip_instead_of_a_failure_in_safe_mode(self):
        p, state = self.make()
        p.safe_mode = True
        p.locked.return_value = False
        scope, printed = run_recipe_step(p, "recipes/oppo-PKT110/recipe.py", ["广告跟踪"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], ["广告跟踪"])
        self.assertIn("安全模式不做整页全关", printed)
        p.off.assert_not_called()
        self.assertTrue(state[0][1], "安全模式下不该点开关")

    def test_ad_tracking_still_closes_the_page_without_safe_mode(self):
        """旧树也绿，守的是不回退：跳过出口在非安全模式下必须是惰性的。"""
        p, state = self.make()
        scope, _ = run_recipe_step(p, "recipes/oppo-PKT110/recipe.py", ["广告跟踪"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertEqual(state[0][1], False)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_app_suggestions_reports_a_skip_instead_of_a_failure_in_safe_mode(self):
        p, state = self.make()
        p.safe_mode = True
        p.locked.return_value = False
        scope, printed = run_recipe_step(p, "recipes/oppo-PKT110/recipe.py", ["应用建议"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], ["应用建议"])
        self.assertIn("安全模式不做整页全关", printed)
        self.assertTrue(state[0][1])

    def test_app_suggestions_still_closes_the_page_without_safe_mode(self):
        """旧树也绿，守的是不回退：跳过出口在非安全模式下必须是惰性的。"""
        p, state = self.make()
        scope, _ = run_recipe_step(p, "recipes/oppo-PKT110/recipe.py", ["应用建议"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(state[0][1], False)


class BehaviourUnchangedTests(unittest.TestCase):
    """跳过出口在非安全模式下必须是惰性的：四段仍照原样做整页关闭（#947）。

    这三条用例旧树也绿——它们守的是不回退，不是本票新增的行为。
    """

    def test_cle_an00_still_taps_close_all(self):
        p = phone_mock()
        p.locked.return_value = False
        p.find.return_value = False         # 不点「显示系统程序」，直接开「更多选项」
        p.tap.return_value = True
        p.switches.return_value = []
        scope, _ = run_recipe_step(p, "recipes/honor-CLE-AN00/recipe.py", ["广告跟踪"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.tap.assert_any_call("全部关闭", exact=True, scrolls=0)
        p.confirm.assert_called_once()

    def test_oppo_machines_still_close_the_page_list(self):
        for path, model in (("recipes/oppo-PMA110/recipe.py", "PMA110"),
                            ("recipes/oppo-PLG110/recipe.py", "PLG110")):
            with self.subTest(recipe=path):
                p = self.oppo_phone(path, model)
                scope, _ = run_recipe_step(p, path, ["广告跟踪"])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                self.assertEqual(scope["FAILED_STEPS"], [])
                p.off.assert_called_once()
                self.assertEqual(p.off.call_args.kwargs["only"], ["示例应用"])
                self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    @staticmethod
    def oppo_phone(path, model):
        """广告跟踪段要的页面：标题与焦点恒定，读完一次名单后全关。"""
        scope = recipe_scope(path)
        state = [("示例应用", True, (1, 2))]
        p = phone_mock()
        p.locked.return_value = False
        p.focus.return_value = _AnyFocus("com.android.settings/_")
        p.texts.return_value = [(t, (0, 0), {})
                                for t in ("设置", "隐私与安全", "设备标识与广告", "广告跟踪")]
        p.tree.return_value = ET.fromstring("<hierarchy></hierarchy>")
        p.tap.return_value = True
        p.scroll_more.return_value = False
        p.switches.side_effect = lambda *a, **k: list(state)

        def off(*a, **k):
            state[:] = [(t, False, xy) for t, _, xy in state]

        p.off.side_effect = off

        def shell(command, timeout=None):
            if "ro.product.model" in command:
                return SimpleNamespace(output=model, exit_code=0)
            if "ro.build.display.id" in command:
                return SimpleNamespace(output=scope["BUILD"], exit_code=0)
            return SimpleNamespace(output="", exit_code=0)

        p.d.shell.side_effect = shell
        return p

    def test_wkl_an20_still_closes_the_whole_page(self):
        path = "recipes/honor-WKL-AN20/recipe.py"
        p = phone_mock()
        p.locked.return_value = False
        p.focus.return_value = _AnyFocus("com.hihonor.id/_")
        p.texts.return_value = [("广告与隐私", (0, 0), {"class": "android.widget.TextView"})]
        p.tree.return_value = ET.fromstring("<hierarchy></hierarchy>")
        p.setting.return_value = True
        p.tap.return_value = True
        p.find.side_effect = lambda text, **kw: text == "隐藏系统程序"
        p.scroll_more.return_value = False
        # 脚本的 safe_ui 和 close_named 都会临时改写 `p.switches`：回读要改最初那个 MagicMock
        reads = p.switches
        reads.return_value = [("示例应用", True, (1, 2))]

        def off(*a, **k):
            reads.return_value = [("示例应用", False, (1, 2))]

        p.off.side_effect = off
        p.d.shell.side_effect = guard_shell(path)
        scope, _ = run_recipe_step(p, path, ["广告跟踪"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.off.assert_called_once()
        self.assertEqual(p.off.call_args.kwargs["only"], ["示例应用"])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)


def whole_page_steps(source):
    """段名 → 是否「整段只做整页关闭」。

    整页关闭 = 不带 `only` 的 `p.off(...)`。段体直接调它、或经脚本自己的助手调它都算；
    段里只要还出现带 `only` 的 `p.off`（点名的开关），这一段就不整段都是整页关闭。
    """
    tree = ast.parse(source)
    # 段函数全都叫 `_`，认人只能按节点本身，不能按函数名
    calls, wide, narrow = {}, set(), set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        here = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "off"
                    and isinstance(fn.value, ast.Name) and fn.value.id == "p"):
                if any(kw.arg == "only" for kw in sub.keywords):
                    narrow.add(node)
                else:
                    wide.add(node)
            elif isinstance(fn, ast.Name):
                here.add(fn.id)
        calls[node] = here
    for target in (wide, narrow):
        names = {node.name for node in target}
        growing = True
        while growing:
            growing = False
            for node, here in calls.items():
                if node not in target and here & names:
                    target.add(node)
                    names.add(node.name)
                    growing = True
    steps = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.decorator_list:
            continue
        first = node.decorator_list[0]
        if not (isinstance(first, ast.Call) and isinstance(first.func, ast.Name)
                and first.func.id == "step"):
            continue
        name = first.args[0].value if first.args else node.name
        steps[name] = (node in wide and node not in narrow, node)
    return steps


def first_call_name(node):
    body = node.body[1:] if ast.get_docstring(node) is not None else node.body
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
        fn = first.value.func
        return fn.id if isinstance(fn, ast.Name) else None
    return None


class WholePageStepGuardTests(unittest.TestCase):
    """整页关闭的段落在每份脚本里怎么写：段首第一句就是跳过出口（#909、#947）。"""

    def test_the_detector_follows_calls_into_local_helpers(self):
        """判据自己要立得住：段体经助手间接整页关闭也算，混着点名开关的不算。"""
        indirect = '''
@step("整页关闭")
def _():
    close_page("页")

def close_page(page):
    p.off(page=page)
'''
        mixed = '''
@step("混着")
def _():
    p.off(only=["甲"], page="页")
    p.off(page="页")
'''
        self.assertTrue(whole_page_steps(indirect)["整页关闭"][0])
        self.assertFalse(whole_page_steps(mixed)["混着"][0])

    def test_page_wide_segments_start_with_the_safe_mode_exit(self):
        """整页关闭的段落要把跳过出口写在第一句：写在后面等于先翻页、再判没关掉。"""
        checked = []
        for path in sorted((ROOT / "recipes").rglob("recipe*.py")):
            steps = whole_page_steps(path.read_text(encoding="utf-8"))
            for name, (is_wide, node) in steps.items():
                if not is_wide:
                    continue
                checked.append((str(path), name))
                self.assertEqual(first_call_name(node), "skip_in_safe_mode",
                                 f"{path} 的「{name}」整页关闭，安全模式下要整段跳过")
        self.assertTrue(checked, "一个整页关闭的段都没认出来：判据本身坏了")
        self.assertEqual(sorted(checked), sorted((str(ROOT / p), n) for p, n in OFF_CALL_WIDE),
                         "检测器认得出的整页关闭段变了：期望集要一起更新")


# ---------- 后并入的票号文件：没装、没找到与失败现场 ----------
# ---------- 来源 tests/test_missing_package_908.py ----------
#   这一段要用的 App 本机没装时按跳过收尾（#908）。
#   
#   `Phone.start()` 在启动失败、手机确认在线、`pm path` 里没有任何 `package:` 时抛
#   `recipe_kit.MissingPackage`（`SkipStep` 的子类）：段包装记跳过台账、整轮退出码仍是 0。
#   同一判定点的另外两种结局不变——包在但拉不起来仍记未完成、断线仍整轮停下。


ABSENT_908 = "com.example.absent"
DOWNLOAD_908 = "com.android.providers.downloads.ui"
LAUNCH_FAILED_908 = SimpleNamespace(output="", exit_code=1, stderr="")


def phone_908(**fields):
    """假 Phone：读屏库那条传输换成 Mock，锁屏判为假（段包装每段读一次）。"""
    p = phone_stub("S", d=Mock(), **fields)
    p.W, p.H = 1080, 1920
    p.locked = lambda *_a, **_k: False
    return p


def absent_shell_908(commands):
    """启动一律失败、`pm path` 一律空输出；每条 shell 命令记进 `commands`。"""
    def shell(command, timeout=None):
        commands.append(command)
        if command.startswith("pm path"):
            return SimpleNamespace(output="", exit_code=0, stderr="")
        return LAUNCH_FAILED_908
    return shell


def unlaunchable_shell_908(commands, activity_error):
    """启动失败、但包确实装着：`pm path` 里有 `package:`。"""
    def shell(command, timeout=None):
        commands.append(command)
        if command.startswith("pm path"):
            return SimpleNamespace(output="package:/system/app/X/X.apk", exit_code=0, stderr="")
        return SimpleNamespace(output=activity_error, exit_code=0, stderr="")
    return shell


def run_report_908(scope, p):
    """跑引擎的收尾：返回（退出码，打出来的那几行）。"""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        return fast.report_run(scope, p), out.getvalue()


class StartOutcomeTests(unittest.TestCase):
    """`Phone.start()` 的三条分支：没装 / 包在但拉不起来 / 断线。"""

    def test_absent_package_raises_the_skip_type_not_a_failure(self):
        commands = []
        p = phone_908()
        p.reader.shell = Mock(side_effect=absent_shell_908(commands))
        with patch.object(adb_link, "detached", return_value=False):
            with self.assertRaises(recipe_kit.MissingPackage) as raised:
                p.start(ABSENT_908)
        self.assertIsInstance(raised.exception, recipe_kit.SkipStep)     # 段包装按跳过接住
        self.assertIn(ABSENT_908, str(raised.exception))                     # 让人知道是哪个 App 不在
        self.assertFalse(p.lost)                                         # 与断线不是一档
        self.assertEqual([c for c in commands if c.startswith("pm path")], [f"pm path {ABSENT_908}"])

    def test_installed_but_unlaunchable_stays_a_failure(self):
        """旧树也绿，守的是不回退：包在但 Activity 不对时仍是未完成，报错带系统原文。"""
        commands = []
        p = phone_908()
        p.reader.shell = Mock(side_effect=unlaunchable_shell_908(
            commands, "Error type 3\nError: Activity class does not exist."))
        with patch.object(adb_link, "detached", return_value=False):
            with self.assertRaises(RuntimeError) as raised:
                p.start(ABSENT_908, ".Main")
        self.assertNotIsInstance(raised.exception, recipe_kit.SkipStep)
        self.assertIn("Activity class does not exist", str(raised.exception))
        self.assertIn(f"pm path {ABSENT_908}", commands)                     # 装没装的判据真的问过

    def test_disconnect_is_not_the_skip_type(self):
        """旧树也绿，守的是不回退：#293 的断线说明照旧上抛，不会被段包装当跳过收下。"""
        commands = []
        p = phone_908()
        p.reader.shell = Mock(side_effect=absent_shell_908(commands))
        with patch.object(adb_link, "detached", return_value=True):
            with self.assertRaises(adb_link.DeviceLost):
                p.start(ABSENT_908)
        self.assertFalse(issubclass(adb_link.DeviceLost, recipe_kit.SkipStep))
        self.assertTrue(p.lost)
        self.assertIn(f"pm path {ABSENT_908}", commands)                     # 先问过包在不在，才判成断线


class SectionOutcomeTests(unittest.TestCase):
    def test_missing_package_lands_in_the_skip_ledger(self):
        """段里拉起一个没装的 App：这一段记跳过，后面的段照常跑，整轮收尾返回 0。"""
        script = f'''
LATER = []

@step("甲")
def _a():
    p.start("{ABSENT_908}")

@step("乙")
def _b():
    LATER.append("乙")
'''
        commands = []
        p = phone_908()
        p.reader.shell = Mock(side_effect=absent_shell_908(commands))
        with patch.object(adb_link, "detached", return_value=False), \
                tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, out = load_recipe(p, path, ())
        self.assertEqual(scope["SKIPPED_STEPS"], ["甲"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["LATER"], ["乙"])
        self.assertIn(f"跳过：本机没有安装 {ABSENT_908}", out.getvalue())
        self.assertIn(f"pm path {ABSENT_908}", commands)
        code, report = run_report_908(scope, p)
        self.assertEqual(code, 0)
        self.assertNotIn("未完成步骤", report)

    def test_installed_app_that_will_not_launch_still_fails_the_section(self):
        """旧树也绿，守的是不回退：段级失败与退出码 1 不变，只有「没装」那一档改成跳过。"""
        script = f'''
@step("甲")
def _a():
    p.start("{ABSENT_908}", ".Main")
'''
        commands = []
        p = phone_908()
        p.reader.shell = Mock(side_effect=unlaunchable_shell_908(commands, "** No activities found to run"))
        with patch.object(adb_link, "detached", return_value=False), \
                tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, out = load_recipe(p, path, ())
        self.assertEqual(scope["FAILED_STEPS"], ["甲"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertIn("No activities found", out.getvalue())
        self.assertIn(f"pm path {ABSENT_908}", commands)
        code, report = run_report_908(scope, p)
        self.assertEqual(code, 1)
        self.assertIn("未完成步骤：甲", report)


class OpenThenMenuTests(unittest.TestCase):
    """「先试直达、失败再走菜单」的助手：包没装时不能吞成「直达不通，走菜单」（#908）。"""

    def test_reference_recipe_skips_instead_of_falling_back_to_the_menu(self):
        commands = []
        p = phone_908()
        p.reader.shell = Mock(side_effect=absent_shell_908(commands))
        with patch.object(adb_link, "detached", return_value=False):
            scope, out = load_recipe(p, ROOT / "recipes/xiaomi-M154FF/recipe.py", only="下载管理")
        self.assertEqual(scope["SKIPPED_STEPS"], ["下载管理"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn(f"本机没有安装 {DOWNLOAD_908}", out.getvalue())
        # 只发了直达那一条 am start 与一次 pm path：助手放行跳过，没有再退到「我的 → 设置」那条路
        self.assertEqual(len(commands), 2, commands)
        self.assertTrue(commands[0].startswith("am start"))
        self.assertEqual(commands[1], f"pm path {DOWNLOAD_908}")
        p.d.app_stop.assert_not_called()


# ---------- 来源 tests/test_missing_switch_evidence_903.py ----------
#   #903：机型脚本「点名的开关没出现」的失败行要自带页面证据。
#   
#   HyperOS 3.0.x 上「广告服务」页找不到「个性化广告推荐」，9 份上报只有一句
#   「未识别全部目标开关，未操作」：分不清是改名了、页面是空的，还是页面根本没打开。
#   现在这条失败与入口失败的「停在 …／标题 N 个，开关 M 个／结构 …」同形，末尾按页面顺序
#   列出当次读到的开关标题。守卫的正文只留在 `recipe_kit.require_switches` 一处。


GUARD_903 = "未识别全部目标开关，未操作"
FOCUS_903 = "com.android.settings/.ad.AdServiceSettings"

# 脚本里「关一组点名开关、缺一项就整段不动」的助手；改名或新增时要一起改这里。
ENTRYPOINTS_903 = {"close_named", "close_with_plain_tap", "store_personalization"}

PAGE_903 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.settings" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="广告服务" bounds="[48,96][360,180]" />
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2340]">
{rows}
    </node>
  </node>
</hierarchy>"""


def row_903(title, top, checked=True):
    return (f'      <node class="android.widget.LinearLayout" bounds="[0,{top}][1080,{top + 120}]">'
            f'<node class="android.widget.TextView" text="{title}" bounds="[48,{top + 10}][600,{top + 110}]" />'
            f'<node class="android.widget.Switch" checkable="true" checked="{str(checked).lower()}" '
            f'bounds="[900,{top + 20}][1020,{top + 100}]" /></node>')


def phone_903(*rows):
    page = PAGE_903.format(rows="\n".join(rows))
    return fake_phone(size=(1080, 2340), stages=((0.0, page),), focus=((0.0, FOCUS_903),))


def recipes_903():
    return sorted((ROOT / "recipes").glob("*/recipe*.py"))


class MissingSwitchEvidenceTests(unittest.TestCase):
    def guard_message(self, recipe, names, *rows):
        scope, _ = load_recipe(phone_903(*rows), ROOT / "recipes" / recipe / "recipe.py")
        with self.assertRaises(RuntimeError) as caught:
            scope["close_named"](names, "系统·广告服务")
        return str(caught.exception)

    def test_missing_target_lists_the_switch_titles_in_page_order(self):
        message = self.guard_message("xiaomi-24129PN74C", ["个性化广告推荐"],
                                     row_903("个性化推荐", 320), row_903("广告服务记录", 460))
        self.assertIn(f"系统·广告服务：{GUARD_903}", message)
        self.assertIn(f"停在 {FOCUS_903}", message)
        self.assertIn("标题 1 个，开关 2 个", message)         # 与入口失败行同一份结构摘要
        self.assertIn("当次读到 2 个开关：个性化推荐、广告服务记录", message)

    def test_empty_page_is_distinguishable_from_unmatched_names(self):
        empty = self.guard_message("xiaomi-24129PN74C", ["个性化广告推荐"])
        renamed = self.guard_message("xiaomi-24129PN74C", ["个性化广告推荐"], row_903("个性化推荐", 320))
        self.assertIn("当次读到 0 个开关：无", empty)
        self.assertIn("当次读到 1 个开关：个性化推荐", renamed)

    def test_exact_match_family_reports_the_same_evidence(self):
        message = self.guard_message("vivo-V2417A", ["个性化广告推荐"],
                                     row_903("个性化推荐", 320), row_903("广告推荐", 460))
        self.assertIn(f"系统·广告服务：{GUARD_903}", message)
        self.assertIn("当次读到 2 个开关：个性化推荐、广告推荐", message)

    def test_empty_name_list_is_still_a_failure(self):
        """「整页开关」那条路（honor 的名单取页面上全部标题）一页空着同样是失败，空名单不许放行。"""
        p = phone_903(row_903("个性化推荐", 320))
        scope, _ = load_recipe(p, ROOT / "recipes" / "xiaomi-24129PN74C" / "recipe.py")
        with self.assertRaises(RuntimeError) as caught:
            scope["require_switches"]({"个性化推荐": True}, [], "系统·广告服务")
        self.assertIn(f"系统·广告服务：{GUARD_903}", str(caught.exception))
        self.assertIn("当次读到 1 个开关：个性化推荐", str(caught.exception))

    def test_present_target_keeps_the_old_output_and_builds_no_evidence(self):
        p = phone_903(row_903("个性化广告推荐", 320, checked=False))
        evidence = []
        real = p.page_evidence
        p.page_evidence = lambda *a, **k: evidence.append(a) or real(*a, **k)
        scope, out = load_recipe(p, ROOT / "recipes" / "xiaomi-24129PN74C" / "recipe.py")
        scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        self.assertEqual(evidence, [])
        self.assertIn("回读确认 0 项", out.getvalue())          # 成功路径仍走原来的收尾
        self.assertNotIn(GUARD_903, out.getvalue())

    def test_failure_still_records_the_step_and_the_exit_code(self):
        p = phone_903(row_903("个性化推荐", 320))
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


class SwitchEvidenceSingleSourceTests(unittest.TestCase):
    def test_guard_wording_lives_only_in_recipe_kit(self):
        """文案留在 require_switches 一处：各自复制一份就会再分叉成两种输出形状。"""
        offenders = [path.relative_to(ROOT).as_posix() for path in recipes_903()
                     if GUARD_903 in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])

    def test_switch_group_entrypoints_take_the_guard_from_recipe_kit(self):
        """关一组点名开关的助手都走注入的那份守卫；这三类是脚本里现存的全部入口。"""
        # 魅族的守卫是「目标开关未全部唯一识别」，判据与文案都不同，且另有失败摘要钩子。
        meizu = "meizu-MEIZU 21 Pro/recipe.py"
        missing = []
        for path in recipes_903():
            if path.parent.name + "/" + path.name == meizu:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef) or node.name not in ENTRYPOINTS_903:
                    continue
                called = {n.func.id for n in ast.walk(node)
                          if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                if "require_switches" not in called:
                    missing.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {node.name}")
        self.assertEqual(missing, [])


# ---------- 来源 tests/test_page_evidence_939.py ----------
#   #939：机型脚本「未确认页面」这类失败要先留下页面骨架，再抛原来的错。
#   
#   OPPO 家族参考脚本与一加 15T 的 `page()` 是三段落点判据（包名、Activity、页面标题）的
#   复制品，三段失败都只抛一句错、不留现场：#910 的「未确认页面「游戏中心」」分不清是标题
#   改名了、还是页面根本没加载完。现在失败时先打一行与入口失败同形的
#   「· 「X」没找到；停在 …；结构摘要」，再抛原来的错 —— 报错文案是上报与用例认的那句，
#   逐字不变，现场走那条独立输出行。实现只留在 `recipe_kit.page` 一处。


# 两份复制品的宿主脚本（#939 的改动面）：注入面里叫 `page`，脚本不再自带。
RECIPES_939 = ("oppo-PMX110/recipe.py", "oneplus-PLZ110/recipe.py")
GAME_939 = "com.nearme.gamecenter"
SETTING_PAGE_939 = "com.nearme.gamecenter/com.nearme.gamecenter.setting.SettingActivity"
LAUNCHER_939 = "com.coloros.launcher/.Launcher"
GAME_MAIN_939 = "com.nearme.gamecenter/.MainActivity"

PAGE_939 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.nearme.gamecenter" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="设置" bounds="[48,96][360,180]" />
  </node>
</hierarchy>"""

OTHER_PAGE_939 = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.nearme.gamecenter" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="游戏中心" bounds="[48,96][360,180]" />
  </node>
</hierarchy>"""


def phone_939(focus=SETTING_PAGE_939, screen=PAGE_939, **fields):
    """假设备 + 真的 `say`：`fake_phone` 默认把 `say` 关掉，这里要看现场那一行。"""
    p = fake_phone(size=(1080, 2340), stages=((0.0, screen),), focus=((0.0, focus),), **fields)
    p.log = True
    p.say = fast.Phone.say.__get__(p)
    p.conn.say = fast.Connection.say.__get__(p.conn)      # 现场行走连接基座（ADR-0033）
    return p


class PageEvidenceTests(unittest.TestCase):
    """报错第一句逐字比对：现场必须走独立输出行，不能拼进消息（上报与用例都认那句）。"""

    def run_page(self, recipe, *args, focus=SETTING_PAGE_939, screen=PAGE_939):
        p = phone_939(focus, screen)
        scope, _ = load_recipe(p, ROOT / "recipes" / recipe)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(RuntimeError) as caught:
                scope["page"](*args)
        return str(caught.exception), out.getvalue()

    def test_a_wrong_title_keeps_the_old_message_and_leaves_the_page(self):
        message, printed = self.run_page(RECIPES_939[0], "游戏中心", GAME_939, "SettingActivity")
        self.assertEqual(message, "未确认页面「游戏中心」，未操作开关")
        self.assertIn(f"· 「游戏中心」没找到；停在 {SETTING_PAGE_939}；标题 1 个", printed)

    def test_a_wrong_package_names_the_package_not_the_title(self):
        """落点跑偏时标题往往就在屏上：现场行写缺的那个包名，别把人引去查改名。"""
        message, printed = self.run_page(RECIPES_939[0], "游戏中心", GAME_939, "SettingActivity",
                                         focus=LAUNCHER_939)
        self.assertEqual(message, "未进入目标应用，未操作开关")
        self.assertIn(f"· 「{GAME_939}」没找到；停在 {LAUNCHER_939}；", printed)

    def test_a_wrong_activity_names_the_activity(self):
        message, printed = self.run_page(RECIPES_939[0], "游戏中心", GAME_939, "SettingActivity",
                                         focus=GAME_MAIN_939)
        self.assertEqual(message, "未进入目标设置页，未操作开关")
        self.assertIn(f"· 「SettingActivity」没找到；停在 {GAME_MAIN_939}；", printed)

    def test_a_confirmed_page_prints_no_evidence(self):
        p = phone_939(SETTING_PAGE_939, OTHER_PAGE_939)
        scope, _ = load_recipe(p, ROOT / "recipes" / RECIPES_939[0])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            scope["page"]("游戏中心", GAME_939, "SettingActivity")
        self.assertNotIn("没找到", out.getvalue())

    def test_a_group_of_titles_is_joined_in_the_evidence(self):
        """一段可以给几种等价标题：现场行把这一组都列出来，别只报第一个。"""
        message, printed = self.run_page(RECIPES_939[0], ("游戏中心", "游戏空间"), GAME_939, "SettingActivity")
        self.assertEqual(message, "未确认页面「游戏中心、游戏空间」，未操作开关")
        self.assertIn("· 「游戏中心 / 游戏空间」没找到；", printed)

    def test_both_copies_report_identically(self):
        for recipe in RECIPES_939:
            with self.subTest(recipe=recipe):
                message, printed = self.run_page(recipe, "游戏中心", GAME_939, "SettingActivity")
                self.assertEqual(message, "未确认页面「游戏中心」，未操作开关")
                self.assertIn(f"· 「游戏中心」没找到；停在 {SETTING_PAGE_939}；", printed)


class PageEvidenceSingleSourceTests(unittest.TestCase):
    def test_the_wording_lives_only_in_recipe_kit(self):
        """三句判据各自复制一份就会再分叉成两种输出形状（#939）。"""
        sources = sorted((ROOT / "recipes").glob("*/recipe*.py"))
        sources += [path for name in ("tool", "gui") for path in sorted((ROOT / name).rglob("*.py"))]
        offenders = [path.relative_to(ROOT).as_posix() for path in sources
                     if path != ROOT / "tool" / "recipe_kit.py"
                     and "未操作开关" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])


# ---------- 来源 tests/test_require_installed_899.py ----------
#   OPPO / 一加机型脚本的 require_installed()：没装的包 `pm path` 返回退出码 1、输出为空，
#   那是「没装、跳过本段」，不是「读不出安装状态」（#899，0.4.1 报告 9–10 份）。

RECIPES_899 = ("recipes/oppo-PMX110/recipe.py", "recipes/oneplus-PLZ110/recipe.py")
PACKAGE_899, LABEL_899 = "com.heytap.yoli", "视频"
CALL_899 = f"pm path {PACKAGE_899}"


class RequireInstalledTests(unittest.TestCase):
    def check(self, recipe, output, code):
        """装载脚本并桩住 `pm path`；顺带带回假手机，好断言这条命令确实被发出去。"""
        p = phone_mock()
        p.d.shell = Mock(return_value=SimpleNamespace(output=output, exit_code=code))
        with contextlib.redirect_stdout(io.StringIO()):
            scope, _ = load_recipe(p, ROOT / recipe, only="__none__")
        return scope, p

    def test_installed_passes(self):
        """旧树也绿，守的是不回退：输出里有 `package:` 就放行。"""
        for recipe in RECIPES_899:
            with self.subTest(recipe=recipe):
                scope, p = self.check(recipe, "package:/data/app/x/base.apk\n", 0)
                self.assertIsNone(scope["require_installed"](PACKAGE_899, LABEL_899))
                p.d.shell.assert_called_once_with(CALL_899)

    def test_not_installed_skips_the_segment(self):
        """没装（退出码 1 或 0、输出为空）跳过本段，不记成失败——#899 的修复点。"""
        for recipe in RECIPES_899:
            for code in (1, 0):          # adb shell v2 带回 1；不带回退出码的通道是 0
                with self.subTest(recipe=recipe, code=code):
                    scope, p = self.check(recipe, "", code)
                    with self.assertRaisesRegex(scope["SkipStep"], "本机未安装视频"):
                        scope["require_installed"](PACKAGE_899, LABEL_899)
                    p.d.shell.assert_called_once_with(CALL_899)

    def test_real_error_still_fails(self):
        """旧树也绿，守的是不回退：非 0/1 退出码 + 报错文字仍算读不出。"""
        for recipe in RECIPES_899:
            with self.subTest(recipe=recipe):
                scope, p = self.check(recipe, "Exception occurred while executing 'path'\n", 255)
                with self.assertRaises(Exception) as caught:
                    scope["require_installed"](PACKAGE_899, LABEL_899)
                self.assertNotIsInstance(caught.exception, scope["SkipStep"])
                self.assertIn("无法读取视频安装状态", str(caught.exception))
                p.d.shell.assert_called_once_with(CALL_899)


if __name__ == "__main__":
    unittest.main()
