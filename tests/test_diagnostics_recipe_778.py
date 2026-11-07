"""#778：诊断里的「机型脚本」一行要分清「借用同品牌参考脚本」和「系统版本不同」。

`recipe_ok` 由 `(not ref) and build_ok(...)` 得出，借用参考脚本时恒为假——那是给检测页与手机版
切安全模式用的。诊断直接拿它说「不一致」，于是每台没有专用脚本的机型都被报成版本对不上。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tool"))

from fixtures import FakeRunner
from gui import app
import run

INFO = {"brand": "meizu", "model": "MEIZU 21 Note", "name": "MEIZU 21 Note",
        "build": "Flyme 12.6.0.0A", "os": "", "android": "15"}


def status(**fields):
    st = {"info": INFO, "recipe": None, "recipe_ref": False, "recipe_build": "", "recipe_ok": True,
          "fold_open": False, "locked": False, "input_blocked": False}
    st.update(fields)
    return st


class RecipeLineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)

    def diagnostics(self, st):
        api = app.Api(self.directory.name, runner=FakeRunner(runs=(json.dumps(st), "", 0)))
        # 认成连着这台机：省掉没设备时才走的 USB 枚举（真去问系统）
        api.last_devices = "List of devices attached\ntest\tdevice\n"
        self.assertEqual(api.status("test"), st)
        return api.diagnostics()

    def test_borrowed_reference_script_is_not_reported_as_a_version_mismatch(self):
        # 版本与实机完全一致（build_ok 为真），只是因为借了同品牌的脚本
        st = status(recipe="recipes/meizu-MEIZU 21 Pro/recipe.py", recipe_ref=True,
                    recipe_build="Flyme 12.6.0.0A", recipe_ok=False)
        self.assertTrue(run.build_ok(INFO, st["recipe_build"]))
        line = self.diagnostics(st)
        self.assertIn("- 机型脚本：recipes/meizu-MEIZU 21 Pro/recipe.py"
                      "（同品牌参考脚本，录制版本 Flyme 12.6.0.0A）", line)
        self.assertNotIn("不一致", line)

    def test_borrowed_reference_script_without_a_recorded_version(self):
        line = self.diagnostics(status(recipe="recipes/meizu-MEIZU 21 Pro/recipe.py", recipe_ref=True))
        self.assertIn("（同品牌参考脚本，录制版本 未标）", line)
        self.assertNotIn("不一致", line)

    def test_own_script_keeps_the_version_comparison(self):
        line = self.diagnostics(status(recipe="recipes/meizu-MEIZU 21 Note/recipe.py",
                                       recipe_build="Flyme 12.6.0.0A"))
        self.assertIn("- 机型脚本：recipes/meizu-MEIZU 21 Note/recipe.py（录制版本 Flyme 12.6.0.0A，一致）", line)
        self.assertNotIn("参考", line)

    def test_own_script_with_a_different_version_still_says_so(self):
        line = self.diagnostics(status(recipe="recipes/meizu-MEIZU 21 Note/recipe.py",
                                       recipe_build="Flyme 12.5.0.0A", recipe_ok=False))
        self.assertIn("（录制版本 Flyme 12.5.0.0A，不一致）", line)

    def test_no_script_stays_no_script(self):
        self.assertIn("- 机型脚本：无", self.diagnostics(status()))


if __name__ == "__main__":
    unittest.main()
