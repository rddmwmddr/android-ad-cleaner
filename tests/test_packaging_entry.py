"""打包入口指向的文件必须存在、能 import、并给出 `main`。

`gui/windows.spec`、`gui/build_mac.sh`、`gui/version.py` 里的路径都是字符串，写错了本地全绿、
只有真打包才暴露——而 `build-windows.yml` 不守 PR（#391）。这里只读文件与语法树，不跑打包。
"""
import ast
import io
import re
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fixtures import RESOLVE_ERROR      # noqa: E402  （跑单个文件时 PYTHONPATH=tests）
from gui import app, launch             # noqa: E402  （ROOT 要先上 sys.path）


def spec_entry():
    """windows.spec 里交给 Analysis 的那份脚本。"""
    src = (ROOT / "gui" / "windows.spec").read_text(encoding="utf-8")
    m = re.search(r'Analysis\(\[\s*os\.path\.join\(ROOT,\s*"gui",\s*"([^"]+)"\)', src)
    return m.group(1) if m else ""


def mac_entry():
    """build_mac.sh 里交给 pyinstaller 的那份脚本（行尾重定向到日志）。"""
    src = (ROOT / "gui" / "build_mac.sh").read_text(encoding="utf-8")
    m = re.search(r"(?m)^\s*(gui/[\w./-]+\.py)\s+>/dev/null", src)
    return m.group(1)[len("gui/"):] if m else ""


VERSION_READERS = ("gui/version.py", "gui/build_mac.sh", "gui/upload_baidu.sh")


def version_source(rel):
    """这一处从哪个文件里读版本号。"""
    src = (ROOT / rel).read_text(encoding="utf-8")
    m = re.search(r"""open\(\s*['"]([^'"]*[\w.]+\.py)['"]""", src) \
        or re.search(r'os\.path\.join\(.*?"([\w.]+\.py)"\)', src)
    return m.group(1) if m else ""


def defines_main(name):
    tree = ast.parse((ROOT / "gui" / name).read_text(encoding="utf-8"))
    return any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)


class PackagingEntryTests(unittest.TestCase):
    def test_windows_spec_entry_exists_and_defines_main(self):
        name = spec_entry()
        self.assertTrue(name, "windows.spec 里找不到 Analysis([... gui/<文件>.py ...])")
        self.assertTrue((ROOT / "gui" / name).exists(), f"gui/{name} 不存在")
        self.assertTrue(defines_main(name), f"gui/{name} 里没有 main()，打包出来的程序没有入口")

    def test_mac_build_entry_exists_and_defines_main(self):
        name = mac_entry()
        self.assertTrue(name, "build_mac.sh 里找不到 pyinstaller 的入口脚本")
        self.assertTrue((ROOT / "gui" / name).exists(), f"gui/{name} 不存在")
        self.assertTrue(defines_main(name), f"gui/{name} 里没有 main()，打包出来的程序没有入口")

    def test_both_packaging_entries_package_the_same_file(self):
        self.assertEqual(spec_entry(), mac_entry(), "Windows 与 Mac 打了不同的入口文件")

    def test_every_version_reader_reads_the_same_file(self):
        sources = {rel: version_source(rel) for rel in VERSION_READERS}
        self.assertTrue(all(sources.values()), f"有读取处没认出来：{sources}")
        names = {Path(v).name for v in sources.values()}
        self.assertEqual(len(names), 1, f"版本号从多个文件读：{sources}")
        name = names.pop()
        src = (ROOT / "gui" / name).read_text(encoding="utf-8")
        self.assertRegex(src, r'(?m)^VERSION = "([^"]+)"', f"gui/{name} 里没有 VERSION，版本号会读空")

    def test_entry_module_imports_without_a_window(self):
        """启动模块在没装 pywebview 的机器上也要能 import：窗口库只在 main() 里才加载。"""
        import importlib
        module = importlib.import_module("gui." + Path(spec_entry()).stem)
        self.assertTrue(callable(getattr(module, "main", None)))

    def assert_entry_forwards_cli(self, *argv):
        """以子进程跑一种启动方式：命令行必须真的转到 `tool/run.py`。

        `--cli` 是打包后子进程的调用形状；这条同时守住 `__main__` 转发有没有被删掉
        （删掉时进程以 0 退出、什么都不打印），以及入口模块在无父包时的 import 兜底。
        """
        r = subprocess.run([sys.executable, *argv, "--cli", "run.py", "--help"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        self.assertEqual(r.returncode, 0, f"{' '.join(argv)} 退出码 {r.returncode}：{r.stderr[-800:]}")
        self.assertIn("tool/run.py", r.stdout, f"{' '.join(argv)} 没有转发到 tool/run.py")

    def test_module_entry_forwards_cli(self):
        self.assert_entry_forwards_cli("-m", "gui.app")

    def test_app_script_entry_forwards_cli(self):
        self.assert_entry_forwards_cli("gui/app.py")

    def test_launch_script_entry_forwards_cli(self):
        self.assert_entry_forwards_cli("gui/launch.py")


CLI_EXE = "/opt/AndroidAdCleaner/aac-cli.exe"
WINDOW_EXE = "/opt/AndroidAdCleaner/AndroidAdCleaner.exe"
PYTHON_EXE = "/usr/local/bin/python3.12"


def launch_once(argv, executable, start_error=None):
    """跑一次入口：返回（退出码, stdout, stderr, 假 webview, 转发到的 cli_main, 未接住的异常）。

    `start_error` 让假 webview 在 `start()` 时抛出，模拟打包件起不来；此时 `main()` 会把异常
    抛回来（`--smoke-gui` 打完诊断行就 re-raise）。
    """
    webview = types.SimpleNamespace(create_window=Mock(), start=Mock(side_effect=start_error))
    out, err = io.StringIO(), io.StringIO()
    code = crash = None
    with tempfile.TemporaryDirectory() as directory, \
         patch.dict(sys.modules, {"webview": webview}), \
         patch.object(sys, "argv", ["launch.py", *argv]), \
         patch.object(sys, "executable", executable), \
         patch.object(app, "data_dir", return_value=directory), \
         patch.object(app, "find_adb", return_value=None), \
         patch.object(app, "cli_main") as cli_main, \
         redirect_stdout(out), redirect_stderr(err):
        try:
            launch.main()
        except SystemExit as stop:
            code = stop.code
        except Exception as error:      # 启动失败被 re-raise，交给调用方断言
            crash = error
    return code, out.getvalue(), err.getvalue(), webview, cli_main, crash


class CliProgramDispatchTests(unittest.TestCase):
    """#573：`aac-cli.exe --help` 以前进了窗口分支，命令行零输出、进程挂住。

    两个 exe 共用 `gui/launch.py`，可执行文件基名是唯一的区别；这里用假的 webview 与假的可执行
    文件名驱动 `main()`，不装窗口库、不连手机。
    """

    def assert_usage(self, text):
        for form in ("aac-cli --cli run.py --help",
                     "aac-cli --cli run.py devices",
                     "aac-cli --cli run.py -s <序列号> check"):
            self.assertIn(form, text, f"用法说明里少了这一种调用：{form}")

    def test_cli_program_help_prints_usage_and_exits_zero(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                code, out, err, webview, _, _ = launch_once([flag], CLI_EXE)
                self.assertEqual(code, 0, err)
                self.assert_usage(out)
                self.assertEqual(err, "")
                webview.create_window.assert_not_called()
                webview.start.assert_not_called()

    def test_cli_program_without_prefix_prints_usage_to_stderr_and_fails(self):
        for argv in ([], ["devices"], ["-s", "ABC123", "check"]):
            with self.subTest(argv=argv):
                code, out, err, webview, _, _ = launch_once(argv, CLI_EXE)
                self.assertTrue(code, f"{argv} 应当以非零退出码结束，实际 {code}")
                self.assert_usage(err)
                self.assertEqual(out, "")
                webview.create_window.assert_not_called()
                webview.start.assert_not_called()

    def test_cli_program_still_forwards_with_the_prefix(self):
        code, out, err, webview, cli_main, _ = launch_once(["--cli", "run.py", "--help"], CLI_EXE)
        self.assertIsNone(code, err)
        cli_main.assert_called_once_with()
        webview.create_window.assert_not_called()

    def test_the_packaging_smoke_flags_still_open_the_window(self):
        """`gui/smoke_test.py` 用 `aac-cli.exe --smoke-gui` 起隐藏窗口做打包冒烟，
        那一步在 `build-windows.yml` 里挡着发版产物；这两个开关不能变成用法错。"""
        for flag in ("--smoke-gui", "--debug"):
            with self.subTest(flag=flag):
                self.assertEqual(launch.dispatch([flag], CLI_EXE), "window")
                # 退出码由冒烟结论决定，这里断言的是「进了窗口分支、没打用法」。
                _, out, err, webview, _, _ = launch_once([flag], CLI_EXE)
                self.assertEqual(out, "")
                self.assertNotIn("aac-cli --cli run.py", err)
                webview.create_window.assert_called_once()

    def test_window_program_without_arguments_still_opens_the_window(self):
        code, _, err, webview, cli_main, _ = launch_once([], WINDOW_EXE)
        self.assertIsNone(code, err)
        cli_main.assert_not_called()
        webview.create_window.assert_called_once()
        webview.start.assert_called_once()

    def test_source_entry_keeps_the_interpreter_behaviour(self):
        """以解释器运行时没有两个 exe 的区别：只有 `--cli` 才转发，其它照旧起窗口。"""
        code, out, err, webview, cli_main, _ = launch_once(["--cli", "run.py", "--help"], PYTHON_EXE)
        self.assertIsNone(code, err)
        self.assertEqual(out, "")
        cli_main.assert_called_once_with()

        code, out, err, webview, cli_main, _ = launch_once(["--help"], PYTHON_EXE)
        self.assertIsNone(code, err)
        self.assertEqual(out, "")
        webview.create_window.assert_called_once()


class SmokeStartupLineTests(unittest.TestCase):
    """#597：启动异常时 `--smoke-gui` 打的那一行要带上归因，远程诊断才分得清是哪一类失败。

    打包件起不来时用户只能贴这一行；归因漏传给 `describe()` 时这里会红。
    """

    def smoke_line(self, error):
        with patch.object(app, "IS_WIN", True):
            _, out, _, _, _, crash = launch_once(["--smoke-gui"], CLI_EXE, start_error=error)
        self.assertIs(crash, error)
        self.assertIn("startup: ", out)
        return out

    def test_line_names_the_load_rejection(self):
        self.assertIn("load=unresolved", self.smoke_line(RuntimeError(RESOLVE_ERROR)))

    def test_line_stays_off_the_load_branch_for_other_errors(self):
        self.assertIn("load=no", self.smoke_line(RuntimeError("WebView2 runtime not found")))


if __name__ == "__main__":
    unittest.main()
