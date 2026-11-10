"""这一段要用的 App 本机没装时按跳过收尾（#908）。

`Phone.start()` 在启动失败、手机确认在线、`pm path` 里没有任何 `package:` 时抛
`recipe_kit.MissingPackage`（`SkipStep` 的子类）：段包装记跳过台账、整轮退出码仍是 0。
同一判定点的另外两种结局不变——包在但拉不起来仍记未完成、断线仍整轮停下。
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adb_link  # noqa: E402
import fast  # noqa: E402
import recipe_kit  # noqa: E402
from fixtures import load_recipe, phone_stub  # noqa: E402

ABSENT = "com.example.absent"
DOWNLOAD = "com.android.providers.downloads.ui"
LAUNCH_FAILED = SimpleNamespace(output="", exit_code=1, stderr="")


def phone(**fields):
    """假 Phone：读屏库那条传输换成 Mock，锁屏判为假（段包装每段读一次）。"""
    p = phone_stub("S", d=Mock(), **fields)
    p.W, p.H = 1080, 1920
    p.locked = lambda *_a, **_k: False
    return p


def absent_shell(commands):
    """启动一律失败、`pm path` 一律空输出；每条 shell 命令记进 `commands`。"""
    def shell(command, timeout=None):
        commands.append(command)
        if command.startswith("pm path"):
            return SimpleNamespace(output="", exit_code=0, stderr="")
        return LAUNCH_FAILED
    return shell


def unlaunchable_shell(commands, activity_error):
    """启动失败、但包确实装着：`pm path` 里有 `package:`。"""
    def shell(command, timeout=None):
        commands.append(command)
        if command.startswith("pm path"):
            return SimpleNamespace(output="package:/system/app/X/X.apk", exit_code=0, stderr="")
        return SimpleNamespace(output=activity_error, exit_code=0, stderr="")
    return shell


def run_report(scope, p):
    """跑引擎的收尾：返回（退出码，打出来的那几行）。"""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        return fast.report_run(scope, p), out.getvalue()


class StartOutcomeTests(unittest.TestCase):
    """`Phone.start()` 的三条分支：没装 / 包在但拉不起来 / 断线。"""

    def test_absent_package_raises_the_skip_type_not_a_failure(self):
        commands = []
        p = phone()
        p.reader.shell = Mock(side_effect=absent_shell(commands))
        with patch.object(adb_link, "detached", return_value=False):
            with self.assertRaises(recipe_kit.MissingPackage) as raised:
                p.start(ABSENT)
        self.assertIsInstance(raised.exception, recipe_kit.SkipStep)     # 段包装按跳过接住
        self.assertIn(ABSENT, str(raised.exception))                     # 让人知道是哪个 App 不在
        self.assertFalse(p.lost)                                         # 与断线不是一档
        self.assertEqual([c for c in commands if c.startswith("pm path")], [f"pm path {ABSENT}"])

    def test_installed_but_unlaunchable_stays_a_failure(self):
        """旧树也绿，守的是不回退：包在但 Activity 不对时仍是未完成，报错带系统原文。"""
        commands = []
        p = phone()
        p.reader.shell = Mock(side_effect=unlaunchable_shell(
            commands, "Error type 3\nError: Activity class does not exist."))
        with patch.object(adb_link, "detached", return_value=False):
            with self.assertRaises(RuntimeError) as raised:
                p.start(ABSENT, ".Main")
        self.assertNotIsInstance(raised.exception, recipe_kit.SkipStep)
        self.assertIn("Activity class does not exist", str(raised.exception))
        self.assertIn(f"pm path {ABSENT}", commands)                     # 装没装的判据真的问过

    def test_disconnect_is_not_the_skip_type(self):
        """旧树也绿，守的是不回退：#293 的断线说明照旧上抛，不会被段包装当跳过收下。"""
        commands = []
        p = phone()
        p.reader.shell = Mock(side_effect=absent_shell(commands))
        with patch.object(adb_link, "detached", return_value=True):
            with self.assertRaises(adb_link.DeviceLost):
                p.start(ABSENT)
        self.assertFalse(issubclass(adb_link.DeviceLost, recipe_kit.SkipStep))
        self.assertTrue(p.lost)
        self.assertIn(f"pm path {ABSENT}", commands)                     # 先问过包在不在，才判成断线


class SectionOutcomeTests(unittest.TestCase):
    def test_missing_package_lands_in_the_skip_ledger(self):
        """段里拉起一个没装的 App：这一段记跳过，后面的段照常跑，整轮收尾返回 0。"""
        script = f'''
LATER = []

@step("甲")
def _a():
    p.start("{ABSENT}")

@step("乙")
def _b():
    LATER.append("乙")
'''
        commands = []
        p = phone()
        p.reader.shell = Mock(side_effect=absent_shell(commands))
        with patch.object(adb_link, "detached", return_value=False), \
                tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, out = load_recipe(p, path, ())
        self.assertEqual(scope["SKIPPED_STEPS"], ["甲"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["LATER"], ["乙"])
        self.assertIn(f"跳过：本机没有安装 {ABSENT}", out.getvalue())
        self.assertIn(f"pm path {ABSENT}", commands)
        code, report = run_report(scope, p)
        self.assertEqual(code, 0)
        self.assertNotIn("未完成步骤", report)

    def test_installed_app_that_will_not_launch_still_fails_the_section(self):
        """旧树也绿，守的是不回退：段级失败与退出码 1 不变，只有「没装」那一档改成跳过。"""
        script = f'''
@step("甲")
def _a():
    p.start("{ABSENT}", ".Main")
'''
        commands = []
        p = phone()
        p.reader.shell = Mock(side_effect=unlaunchable_shell(commands, "** No activities found to run"))
        with patch.object(adb_link, "detached", return_value=False), \
                tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, out = load_recipe(p, path, ())
        self.assertEqual(scope["FAILED_STEPS"], ["甲"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertIn("No activities found", out.getvalue())
        self.assertIn(f"pm path {ABSENT}", commands)
        code, report = run_report(scope, p)
        self.assertEqual(code, 1)
        self.assertIn("未完成步骤：甲", report)


class OpenThenMenuTests(unittest.TestCase):
    """「先试直达、失败再走菜单」的助手：包没装时不能吞成「直达不通，走菜单」（#908）。"""

    def test_reference_recipe_skips_instead_of_falling_back_to_the_menu(self):
        commands = []
        p = phone()
        p.reader.shell = Mock(side_effect=absent_shell(commands))
        with patch.object(adb_link, "detached", return_value=False):
            scope, out = load_recipe(p, ROOT / "recipes/xiaomi-M154FF/recipe.py", only="下载管理")
        self.assertEqual(scope["SKIPPED_STEPS"], ["下载管理"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn(f"本机没有安装 {DOWNLOAD}", out.getvalue())
        # 只发了直达那一条 am start 与一次 pm path：助手放行跳过，没有再退到「我的 → 设置」那条路
        self.assertEqual(len(commands), 2, commands)
        self.assertTrue(commands[0].startswith("am start"))
        self.assertEqual(commands[1], f"pm path {DOWNLOAD}")
        p.d.app_stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
