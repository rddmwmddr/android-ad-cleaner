"""Windows 启动失败归因：缺 WebView2 / 程序文件带 MOTW / 本地 dll 被 .NET 判成远程来源 / 其他
（#228、#597）。

注册表读取与 ADS 探测都从外面注入，所以这套判定在 macOS 上也能跑。
"""
import sys
import tempfile
import unittest
from pathlib import Path

from gui import winpreflight

# 报告者给的原文（#597）：clr_loader 按路径加载 Python.Runtime.dll 时被 .NET Framework 拒了。
RESOLVE_ERROR = (
    "RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from "
    r"D:\AndroidAdCleaner\_internal\pythonnet\runtime\Python.Runtime.dll"
)

# 三处实际存在的注册表位置，按报告者给出的路径写死，不从被测代码里取。
KEY_64 = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
KEY_32 = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
KEY_USER = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
VERSION = "156.0.3414.50"

DLLS = (("pythonnet", "runtime", "Python.Runtime.dll"),
        ("clr_loader", "ffi", "dlls", "amd64", "ClrLoader.dll"))


def fake_read(values):
    """values: {(hive, 完整键路径): pv 或异常}；不在表里的键一律当作键不存在。"""
    def read(hive, path):
        value = values.get((hive, path))
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise FileNotFoundError(path)
        return value

    return read


def always_raise(error):
    def read(hive, path):
        raise error

    return read


def make_dlls(root):
    for rel in DLLS:
        path = root.joinpath(*rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


class RegistryStateTests(unittest.TestCase):
    def test_installed_from_the_64bit_key(self):
        self.assertEqual(winpreflight.webview2_state(fake_read({("HKLM", KEY_64): VERSION})),
                         "installed")

    def test_installed_from_the_32bit_key(self):
        self.assertEqual(winpreflight.webview2_state(fake_read({("HKLM", KEY_32): VERSION})),
                         "installed")

    def test_installed_from_the_per_user_key(self):
        self.assertEqual(winpreflight.webview2_state(fake_read({("HKCU", KEY_USER): VERSION})),
                         "installed")

    def test_missing_when_no_key_exists(self):
        self.assertEqual(winpreflight.webview2_state(fake_read({})), "missing")

    def test_unknown_when_every_key_raises(self):
        self.assertEqual(winpreflight.webview2_state(always_raise(PermissionError("拒绝访问"))),
                         "unknown")

    def test_unknown_does_not_hide_a_real_install(self):
        read = fake_read({("HKLM", KEY_64): PermissionError("拒绝访问"),
                          ("HKCU", KEY_USER): VERSION})
        self.assertEqual(winpreflight.webview2_state(read), "installed")

    def test_empty_version_counts_as_missing(self):
        self.assertEqual(winpreflight.webview2_state(fake_read({("HKLM", KEY_64): ""})), "missing")

    @unittest.skipIf(sys.platform == "win32", "Windows 上默认读取会真读注册表")
    def test_default_reader_does_not_raise_off_windows(self):
        self.assertEqual(winpreflight.webview2_state(), "unknown")


class BlockedFilesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

    def test_reports_the_two_load_bearing_dlls(self):
        make_dlls(self.root)
        blocked = winpreflight.blocked_files(str(self.root), detect=lambda p: True)
        self.assertEqual({Path(p).name for p in blocked},
                         {"Python.Runtime.dll", "ClrLoader.dll"})

    def test_ignores_files_without_the_stream(self):
        make_dlls(self.root)
        self.assertEqual(winpreflight.blocked_files(str(self.root), detect=lambda p: False), ())

    def test_does_not_probe_files_that_are_not_there(self):
        probed = []
        winpreflight.blocked_files(str(self.root), detect=lambda p: probed.append(p) or True)
        self.assertEqual(probed, [])

    def test_default_detector_reports_nothing_for_a_plain_file(self):
        make_dlls(self.root)
        self.assertEqual(winpreflight.blocked_files(str(self.root)), ())


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        make_dlls(self.root)

    def test_line_names_both_facts(self):
        line = winpreflight.describe(str(self.root), read=fake_read({("HKLM", KEY_64): VERSION}),
                                     detect=lambda p: True)
        self.assertEqual(line, "webview2=installed motw=yes load=no")

    def test_line_says_no_when_nothing_is_wrong(self):
        line = winpreflight.describe(str(self.root), read=fake_read({}), detect=lambda p: False)
        self.assertEqual(line, "webview2=missing motw=no load=no")

    def test_line_names_the_load_rejection(self):
        line = winpreflight.describe(str(self.root), read=fake_read({("HKLM", KEY_64): VERSION}),
                                     detect=lambda p: False, error=RuntimeError(RESOLVE_ERROR))
        self.assertEqual(line, "webview2=installed motw=no load=unresolved")


class StartupAdviceTests(unittest.TestCase):
    """窗口起不来时用户看到的那段话，以及要不要跳微软官网。"""

    def advice(self, state, blocked=(), error=None):
        from gui import app
        return app.startup_advice(state, blocked, error or RuntimeError("loading Python.Runtime.dll failed"))

    def test_missing_runtime_points_at_the_bootstrap_installer(self):
        text, open_site = self.advice("missing")
        self.assertIn("缺少微软 Edge WebView2 运行时", text)
        self.assertIn("Evergreen Bootstrapper", text)
        self.assertTrue(open_site)

    def test_blocked_files_explain_the_unlock_step_and_stay_off_the_site(self):
        text, open_site = self.advice("installed", blocked=("x",))
        self.assertIn("解除锁定", text)
        self.assertIn("Unblock-File", text)
        self.assertNotIn("缺少微软 Edge WebView2 运行时", text)
        self.assertFalse(open_site)

    def test_unknown_state_says_it_could_not_be_confirmed(self):
        text, open_site = self.advice("unknown")
        self.assertIn("没能确认", text)
        self.assertNotIn("缺少微软 Edge WebView2 运行时", text)
        self.assertFalse(open_site)

    def test_installed_without_blocking_sends_the_error_along(self):
        text, open_site = self.advice("installed")
        self.assertIn("loading Python.Runtime.dll failed", text)
        self.assertIn("issues/new", text)
        self.assertFalse(open_site)

    def test_load_rejection_points_at_the_bundled_config(self):
        """#597：本地 dll 被 .NET 判成远程来源时，别再让用户去提 issue。"""
        text, open_site = self.advice("installed", error=RuntimeError(RESOLVE_ERROR))
        self.assertIn("远程来源", text)
        self.assertIn("AndroidAdCleaner.exe.config", text)
        self.assertNotIn("issues/new", text)
        self.assertNotIn("缺少微软 Edge WebView2 运行时", text)
        self.assertFalse(open_site)

    def test_a_partial_error_text_does_not_land_on_the_load_branch(self):
        """两个子串缺一个就不算这一类，免得把别的 clr 故障也指到 config 上。"""
        for error in ("Failed to resolve WebView2 from somewhere",
                      "Python.Runtime.Loader.Initialize is missing"):
            with self.subTest(error=error):
                text, _ = self.advice("installed", error=RuntimeError(error))
                self.assertIn("issues/new", text)
                self.assertNotIn("AndroidAdCleaner.exe.config", text)

    def test_motw_wins_over_the_load_branch_when_both_apply(self):
        """带 MOTW 的 dll 也会报同一句 resolve 失败；那时该给的是解锁步骤，不是 config。"""
        text, _ = self.advice("installed", blocked=("x",), error=RuntimeError(RESOLVE_ERROR))
        self.assertIn("解除锁定", text)
        self.assertNotIn("AndroidAdCleaner.exe.config", text)


class StartupFailedWiringTests(unittest.TestCase):
    """`startup_failed` 把归因喂给弹窗、并且只在缺运行时那一路开官网。"""

    class Verdict:
        def __init__(self, state, blocked=()):
            self.state, self.blocked = state, blocked

        def webview2_state(self):
            return self.state

        def blocked_files(self, root):
            return tuple(self.blocked)

    def run_with(self, state, blocked=(), error=None):
        from gui import app
        seen, opened = [], []
        app.startup_failed(error or RuntimeError("boom"), preflight=self.Verdict(state, blocked),
                           notify=seen.append, open_url=opened.append)
        return seen, opened

    def test_blocked_verdict_reaches_the_dialog_without_opening_the_site(self):
        seen, opened = self.run_with("installed", blocked=("x",))
        self.assertEqual(len(seen), 1)
        self.assertIn("解除锁定", seen[0])
        self.assertEqual(opened, [])

    def test_missing_verdict_opens_the_webview2_page(self):
        seen, opened = self.run_with("missing")
        self.assertIn("Evergreen Bootstrapper", seen[0])
        self.assertEqual(opened, ["https://developer.microsoft.com/microsoft-edge/webview2/"])

    def test_load_rejection_reaches_the_dialog(self):
        seen, opened = self.run_with("installed", error=RuntimeError(RESOLVE_ERROR))
        self.assertEqual(len(seen), 1)
        self.assertIn("AndroidAdCleaner.exe.config", seen[0])
        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
