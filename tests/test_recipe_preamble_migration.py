"""机型脚本不再自带前导（#839）：结构守卫 + 每份脚本三个场景的行为守卫。

结构层：43 份脚本不得再定义前导六个名字，`adapt gen` 生成的草稿同样不得带。
行为层：每份脚本三个场景 —— 跑前锁屏、首段失败、中途锁屏 —— 失败台账非空且退出码 1。
只断言外部行为：装载脚本、驱动段包装、看台账与退出码；不断言段包装内部调用了谁。
"""
import ast
import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adapt
import fast
from fixtures import load_recipe, phone_mock

RECIPES = tuple(sorted(p for p in (ROOT / "recipes").rglob("*.py")
                       if p.name != "test_recipe.py"))               # 43 份：目录里除 test_recipe.py 之外的脚本

# 前导的六个名字，外加 #838 的中止标记与两个新台账 —— 迁到引擎之后脚本一个都不该再定义
LOCAL_PREAMBLE = {
    "ONLY": "段过滤名单",
    "FAILED_STEPS": "失败台账",
    "SKIPPED_STEPS": "跳过台账",
    "HALTED": "中止标记",
    "HALTED_STEPS": "中止台账",
    "step": "段包装",
    "require": "必需入口断言",
    "maybe": "可选入口助手",
    "skip": "跳过出口",
    "SkipStep": "跳过异常类",
}

# 记录在案的例外：脚本相对路径 → 允许保留的名字。迁移完成后为空。
ALLOWED = {}


def defined_names(source, filename="<script>"):
    """脚本顶层定义的名字与 LOCAL_PREAMBLE 的交集。"""
    tree = ast.parse(source, filename)
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
    return names & set(LOCAL_PREAMBLE)


class AnyText(str):
    """认不出的型号 / 版本读数：脚本的 `guard()` 拿它去比对时一律算「对得上」。

    行为守卫只测锁屏与失败记账，不测各家族的型号判据 —— 那些由各机型的用例守着。
    """

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    def __hash__(self):
        return str.__hash__(self)

    def startswith(self, prefix, *args, **kwargs):
        return True

    def strip(self, *args, **kwargs):
        return self


def shell(command, timeout=None):
    return SimpleNamespace(output=AnyText("probe"), exit_code=0)


def probe_phone(locked):
    p = phone_mock()
    p.safe_mode = False
    p.locked = locked
    p.changed = []                 # 脚本尾行会 len(p.changed)；Mock 没有 len
    p.d = SimpleNamespace(shell=shell)
    return p


def probe(path, locked):
    """装载真实脚本（一段都不跑），再把段包装交回调用方驱动。"""
    p = probe_phone(locked)
    scope, _ = load_recipe(p, path)
    scope["ONLY"] = []
    return scope, p


def drive(scope, p, bodies):
    with contextlib.redirect_stdout(io.StringIO()):
        for name, body in bodies:
            scope["step"](name)(body)
        code = fast.report_run(scope, p)
    return code


def _ok(calls, name):
    return lambda: calls.append(name)


def _boom():
    raise RuntimeError("入口「设置」没找到")


class StructureTests(unittest.TestCase):
    def test_recipes_do_not_define_the_preamble(self):
        offenders = {}
        for path in RECIPES:
            key = str(path.relative_to(ROOT))
            found = defined_names(path.read_text(encoding="utf-8"), str(path)) - set(ALLOWED.get(key, ()))
            if found:
                offenders[key] = sorted(found)
        self.assertEqual(offenders, {}, "脚本仍在本地定义前导，应删掉改用引擎注入的那一份")

    def test_the_generated_draft_does_not_carry_a_preamble(self):
        """`adapt gen` 的草稿也交给引擎注入，否则新写的脚本又把本地副本带回来。"""
        draft = adapt.render_draft([("com.example", "设置 > 隐私", ["个性化推荐"])],
                                   "PLP120", "PLP120_16.0.9", "探路.tsv")
        self.assertEqual(defined_names(draft, "草稿.py"), set())


class BehaviourTests(unittest.TestCase):
    """43 份 × 3 个场景：锁屏与段失败都要在失败台账里留下名字，退出码为 1。

    只问「台账非空、退出码 1」。中止之后不读屏、后来的段记「未执行」这些是注入那份前导的
    内部契约，由 `tests/test_recipe_kit.py` 守一次；这里重复断言只会让 43 份一起红，
    看不出是哪一份真的在静默跳过。
    """

    def test_a_locked_screen_before_the_first_step_fails_the_run(self):
        for path in RECIPES:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, p = probe(path, lambda *a, **k: True)
                code = drive(scope, p, [("探针", _ok([], "探针"))])
                self.assertEqual(scope["FAILED_STEPS"], ["探针"])
                self.assertEqual(code, 1)

    def test_a_first_step_failure_fails_the_run_and_the_rest_still_run(self):
        for path in RECIPES:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, p = probe(path, lambda *a, **k: False)
                calls = []
                code = drive(scope, p, [("探针", _boom), ("后段", _ok(calls, "后段"))])
                self.assertEqual(scope["FAILED_STEPS"], ["探针"])
                self.assertEqual(code, 1)
                self.assertEqual(calls, ["后段"], "一段失败不该中断整批")

    def test_a_middle_step_failure_fails_the_run(self):
        for path in RECIPES:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, p = probe(path, lambda *a, **k: False)
                code = drive(scope, p, [("甲", _ok([], "甲")), ("乙", _boom), ("丙", _ok([], "丙"))])
                self.assertEqual(scope["FAILED_STEPS"], ["乙"])
                self.assertEqual(code, 1)

    def test_a_lock_in_the_middle_halts_the_batch(self):
        for path in RECIPES:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                reads = {"n": 0}

                def locked(*_a, **_k):
                    reads["n"] += 1
                    return reads["n"] > 1

                scope, p = probe(path, locked)
                code = drive(scope, p, [("甲", _ok([], "甲")), ("乙", _ok([], "乙")),
                                        ("丙", _ok([], "丙"))])
                self.assertEqual(scope["FAILED_STEPS"], ["乙", "丙"])
                self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
