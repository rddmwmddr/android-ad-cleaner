"""全部机型脚本的 FAILED_STEPS 信号与退出码兜底测试（#583）。

保证：
1. 仓库内每一份机型脚本都显式定义了模块级 FAILED_STEPS。
2. 每一份机型脚本的 step() 装饰器在段内抛异常时，都会把段名追加进 FAILED_STEPS。
3. tool/fast.py 的 run 分支在作用域中预置默认 FAILED_STEPS = []，为未显式声明变量但使用 FAILED_STEPS 的脚本提供默认容器。
4. tool/fast.py 的 run 分支在 FAILED_STEPS 非空时 sys.exit(1)，为空时不报错退出。
"""
import ast
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
import run


class RecipeFailedStepsTests(unittest.TestCase):
    def setUp(self):
        self.recipes = sorted([
            p for p in ROOT.glob("recipes/**/recipe*.py")
            if not p.name.startswith("test_")
        ])

    def test_all_recipes_define_module_level_failed_steps(self):
        """39 份机型脚本都必须显式定义模块级 FAILED_STEPS。"""
        self.assertGreaterEqual(len(self.recipes), 39)
        missing = []
        for recipe_path in self.recipes:
            source = recipe_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(recipe_path))
            defined = False
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "FAILED_STEPS":
                            defined = True
            if not defined:
                missing.append(recipe_path.relative_to(ROOT).as_posix())
        self.assertEqual(missing, [], f"机型脚本缺少模块级 FAILED_STEPS: {missing}")

    def test_all_recipes_step_decorator_records_failed_steps_on_exception(self):
        """每一份机型脚本在段内抛出异常时，段名必须精确记录进 FAILED_STEPS。"""
        for recipe_path in self.recipes:
            meta = run.recipe_meta(str(recipe_path))
            steps = meta.get("steps") or []
            self.assertTrue(steps, f"{recipe_path} 没有解析出 steps")
            target_step = steps[0]

            model_from_dir = recipe_path.parent.name.split("-")[-1]
            build_val = meta.get("build") or "TEST"

            p = MagicMock()
            p.locked.return_value = False
            p.miss = 0
            p.safe_mode = False

            def make_shell(cmd):
                res = Mock()
                if "ro.product.model" in cmd:
                    models = meta.get("models")
                    res.output = models[0] if models else model_from_dir
                elif "ro.build.display.id" in cmd or "ro.mi.os.version.incremental" in cmd:
                    res.output = build_val
                else:
                    res.output = ""
                return res

            p.d.shell.side_effect = make_shell

            scope = {
                "p": p,
                "ONLY": [target_step],
                "CHANGES": {target_step: "测试开关"},
            }

            probe_source = (
                f"\n"
                f"@step('{target_step}')\n"
                f"def _probe_err_replacement():\n"
                f"    raise RuntimeError('boom_probe_failed_step')\n"
            )
            full_src = recipe_path.read_text(encoding="utf-8") + probe_source
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                exec(compile(full_src, str(recipe_path), "exec"), scope)

            failed = scope.get("FAILED_STEPS", [])
            self.assertIn(
                target_step,
                failed,
                f"{recipe_path.relative_to(ROOT)} 在步骤 {target_step} 异常时未能记录进 FAILED_STEPS: {failed}",
            )

    def test_fast_run_prepopulates_default_failed_steps(self):
        """tool/fast.py 的 run 分支为不声明 FAILED_STEPS 但使用该变量的脚本提供默认容器并正常退出 1。"""
        p = MagicMock()
        p.wait_unlocked.return_value = True
        p.changed = []
        p.d.shell.return_value.output = "TEST"
        p.__enter__.return_value = p
        p.__exit__.return_value = None

        fake_recipe = ROOT / "recipes/meizu-MEIZU 21 Pro/recipe.py"
        # 脚本未声明 FAILED_STEPS，但直接引用并 append
        mock_src = "FAILED_STEPS.append('未声明变量直接append')\n"
        with patch.object(fast, "Phone", return_value=p), \
             patch.object(fast.backups, "root_from_env", return_value=""), \
             patch("builtins.open", unittest.mock.mock_open(read_data=mock_src)), \
             patch.object(sys, "argv", ["fast.py", "-s", "dummy", "run", str(fake_recipe)]):
            with self.assertRaises(SystemExit) as ctx:
                fast.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_fast_run_exits_1_when_failed_steps_is_not_empty(self):
        """tool/fast.py 的 run 分支在 FAILED_STEPS 非空时以状态码 1 退出。"""
        p = MagicMock()
        p.wait_unlocked.return_value = True
        p.changed = []
        p.d.shell.return_value.output = "TEST"
        p.__enter__.return_value = p
        p.__exit__.return_value = None

        fake_recipe = ROOT / "recipes/meizu-MEIZU 21 Pro/recipe.py"
        with patch.object(fast, "Phone", return_value=p), \
             patch.object(fast.backups, "root_from_env", return_value=""), \
             patch("builtins.open", unittest.mock.mock_open(read_data="FAILED_STEPS = ['测试段']\n")), \
             patch.object(sys, "argv", ["fast.py", "-s", "dummy", "run", str(fake_recipe)]):
            with self.assertRaises(SystemExit) as ctx:
                fast.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_fast_run_exits_0_when_failed_steps_is_empty(self):
        """tool/fast.py 的 run 分支在 FAILED_STEPS 为空时正常返回（退出码 0）。"""
        p = MagicMock()
        p.wait_unlocked.return_value = True
        p.changed = []
        p.d.shell.return_value.output = "TEST"
        p.__enter__.return_value = p
        p.__exit__.return_value = None

        fake_recipe = ROOT / "recipes/meizu-MEIZU 21 Pro/recipe.py"
        with patch.object(fast, "Phone", return_value=p), \
             patch.object(fast.backups, "root_from_env", return_value=""), \
             patch("builtins.open", unittest.mock.mock_open(read_data="FAILED_STEPS = []\n")), \
             patch.object(sys, "argv", ["fast.py", "-s", "dummy", "run", str(fake_recipe)]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                fast.main()
            self.assertIn("机型脚本跑完", out.getvalue())


if __name__ == "__main__":
    unittest.main()
