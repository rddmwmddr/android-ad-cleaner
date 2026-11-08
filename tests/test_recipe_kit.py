"""引擎注入的机型脚本前导（#838）：段包装、跳过出口、失败台账与锁屏中止。

只断言外部行为——装载一份脚本、跑、看台账与退出码；不断言段包装内部调用了谁。
脚本夹具不写本地前导，用的就是注入的那一份（#839 迁移之后真实脚本长这样）。
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adapt
import fast
from fixtures import EMPTY_PAGE, Clock, fake_phone, install_clock, load_recipe, phone_stub

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


if __name__ == "__main__":
    unittest.main()
