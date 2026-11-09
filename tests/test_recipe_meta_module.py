"""配方元数据解析住在中立模块里（#915）：非 CLI 代码 import 它时不背 CLI 入口的副作用。

`tool/run.py` 一 import 就注入路径、导 adb 依赖、把 stdout/stderr 重配成 UTF-8、解析备份根目录。
验证台账（#914）要读每份脚本声明的 `BUILD`，不该为了一个正则拉起整个命令行。

import 纯净性用子进程测（仿 `tests/test_gui_import.py`）：测的是「导入这个模块本身做了什么」。
PYTHONIOENCODING 钉成 gbk:strict，是为了让「重配过编码」这件事可观测——UTF-8 的 CI 上默认值恰好也是 utf-8。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import recipe_meta  # noqa: E402
import run  # noqa: E402

# 引擎侧的重依赖与 CLI 入口：中立模块一个都不该碰到
BLOCKED = ("adbutils", "uiautomator2", "adb_link", "fast", "backups", "run", "events", "host", "reader", "wait")

CODE = """
import json, os, sys

BLOCKED = %r

class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"blocked for the purity check: {name}", name=name)
        return None

sys.meta_path.insert(0, Blocker())
sys.path.insert(0, os.path.join(os.getcwd(), "tool"))
before = list(sys.path)
import recipe_meta
print(json.dumps({"path_changed": sys.path != before,
                  "loaded": sorted(m for m in BLOCKED if m in sys.modules),
                  "encoding": [sys.stdout.encoding, sys.stderr.encoding],
                  "errors": [sys.stdout.errors, sys.stderr.errors]}))
""" % (list(BLOCKED),)


class ImportPurityTests(unittest.TestCase):
    def run_import(self):
        env = dict(os.environ, PYTHONIOENCODING="gbk:strict", AAC_BACKUPS="")
        done = subprocess.run([sys.executable, "-c", CODE], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_import_pulls_no_engine_dependency_and_no_cli_side_effect(self):
        seen = self.run_import()
        self.assertEqual(seen["loaded"], [], "import recipe_meta 拉起了引擎 / CLI 侧的模块")
        self.assertFalse(seen["path_changed"], "import recipe_meta 改了 sys.path")
        self.assertEqual(seen["encoding"], ["gbk", "gbk"], "import recipe_meta 重配了输出流编码")
        # stderr 的错误策略由解释器定成 backslashreplace，不吃 PYTHONIOENCODING 的 strict
        self.assertEqual(seen["errors"], ["strict", "backslashreplace"], "import recipe_meta 重配了输出流错误策略")


class ParseTests(unittest.TestCase):
    """解析结果仍是系统 build、机型列表、段名三样，与搬运前逐字相同。"""

    def parse(self, src):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "recipe.py")
            path.write_text(src, encoding="utf-8")
            return recipe_meta.recipe_meta(path)

    def test_three_declared_fields(self):
        self.assertEqual(self.parse(
            'BUILD = "PMX110_17.0.0.116(CN01)"\n'
            'MODELS = ["PMX110", "PMX110T"]\n'
            '@step("商店")\n'
            '@step("主题")\n'), {
            "build": "PMX110_17.0.0.116(CN01)",
            "models": ["PMX110", "PMX110T"],
            "steps": ["商店", "主题"],
        })

    def test_missing_declarations_are_empty_not_errors(self):
        self.assertEqual(self.parse('print("hi")\n'), {"build": "", "models": [], "steps": []})

    def test_only_line_initial_step_decorators_count(self):
        # 迁移前就是 `^@step`：段包装里的同名调用、缩进的注释行都不算段名
        self.assertEqual(self.parse('@step("真段")\n    @step("缩进的不算")\n')["steps"], ["真段"])


class SingleDefinitionTests(unittest.TestCase):
    def test_run_reuses_the_neutral_function(self):
        self.assertIs(run.recipe_meta, recipe_meta.recipe_meta,
                      "CLI 入口又自己定义了一份解析（#915）")


if __name__ == "__main__":
    unittest.main()
