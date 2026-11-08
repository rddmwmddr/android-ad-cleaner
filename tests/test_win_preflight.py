"""Windows 启动失败归因：缺 WebView2 / 程序文件带 MOTW / 本地 dll 被 .NET 判成远程来源 / 其他
（#228、#597）；以及免安装版启动时旧名安装还在的检测（#872）。

注册表读取与 ADS 探测都从外面注入，所以这套判定在 macOS 上也能跑。
"""
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import RESOLVE_ERROR
from gui import winpreflight

# 三处实际存在的注册表位置，按报告者给出的路径写死，不从被测代码里取。
KEY_64 = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
KEY_32 = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
KEY_USER = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
VERSION = "156.0.3414.50"

DLLS = (("pythonnet", "runtime", "Python.Runtime.dll"),
        ("clr_loader", "ffi", "dlls", "amd64", "ClrLoader.dll"))

WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

# 五路归因各来一次：(webview2 状态, 带 MOTW 的 dll, 错误原文)
ATTRIBUTIONS = (
    ("missing", (), None),
    ("installed", ("x",), None),
    ("installed", (), RESOLVE_ERROR),
    ("unknown", (), None),
    ("installed", (), None),
)


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
    def read(*_args):
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

    def advice(self, state, blocked=(), error=None, copied=None):
        from gui import app
        error = error or RuntimeError("loading Python.Runtime.dll failed")
        return app.startup_advice(state, blocked, error, winpreflight.load_rejected(error), copied)

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


class CopyNoteTests(unittest.TestCase):
    """#811：弹窗之前先替用户复制好；复制不进去时退回按 Ctrl+C。"""

    def advice(self, state, blocked, error, copied):
        from gui import app
        error = RuntimeError(error or "loading Python.Runtime.dll failed")
        return app.startup_advice(state, blocked, error, winpreflight.load_rejected(error), copied)

    def test_every_attribution_says_the_text_is_already_copied(self):
        for state, blocked, error in ATTRIBUTIONS:
            with self.subTest(state=state, blocked=blocked, error=error):
                text, _ = self.advice(state, blocked, error, copied=True)
                self.assertIn("已复制", text)
                self.assertIn("粘贴", text)
                self.assertNotIn("Ctrl+C", text)

    def test_every_attribution_falls_back_to_ctrl_c_when_the_copy_failed(self):
        for state, blocked, error in ATTRIBUTIONS:
            with self.subTest(state=state, blocked=blocked, error=error):
                text, _ = self.advice(state, blocked, error, copied=False)
                self.assertIn("Ctrl+C", text)
                self.assertNotIn("已复制", text)

    def test_without_a_copy_attempt_the_text_is_left_alone(self):
        text, _ = self.advice("installed", (), None, copied=None)
        self.assertNotIn("Ctrl+C", text)
        self.assertNotIn("已复制", text)


class StartupFailedWiringTests(unittest.TestCase):
    """`startup_failed` 先复制、后弹窗，并且只在缺运行时那一路开官网。"""

    class Verdict:
        def __init__(self, state, blocked=()):
            self.state, self.blocked = state, blocked

        def webview2_state(self):
            return self.state

        def blocked_files(self, root):
            return tuple(self.blocked)

        def load_rejected(self, error):
            return winpreflight.load_rejected(error)

    class Clipboard:
        """假剪贴板：记下写进去的内容；error 非空时模拟被别的程序占着。"""

        def __init__(self, log, error=None):
            self.log, self.error = log, error

        def __call__(self, text):
            self.log.append(("copy", text))
            if self.error is not None:
                raise self.error

    def run_with(self, state, blocked=(), error=None, clipboard_error=None):
        from gui import app
        log, opened = [], []
        error = RuntimeError(error) if error else RuntimeError("boom")
        app.startup_failed(error, preflight=self.Verdict(state, blocked),
                           notify=lambda text: log.append(("notify", text)),
                           open_url=opened.append, clipboard=self.Clipboard(log, clipboard_error))
        shown = [text for kind, text in log if kind == "notify"]
        return log, shown, opened

    def test_blocked_verdict_reaches_the_dialog_without_opening_the_site(self):
        _, shown, opened = self.run_with("installed", blocked=("x",))
        self.assertEqual(len(shown), 1)
        self.assertIn("解除锁定", shown[0])
        self.assertEqual(opened, [])

    def test_missing_verdict_opens_the_webview2_page(self):
        _, shown, opened = self.run_with("missing")
        self.assertIn("Evergreen Bootstrapper", shown[0])
        self.assertEqual(opened, [WEBVIEW2_URL])

    def test_load_rejection_reaches_the_dialog(self):
        _, shown, opened = self.run_with("installed", error=RESOLVE_ERROR)
        self.assertEqual(len(shown), 1)
        self.assertIn("AndroidAdCleaner.exe.config", shown[0])
        self.assertEqual(opened, [])

    def test_the_dialog_text_is_on_the_clipboard_before_it_appears(self):
        log, shown, _ = self.run_with("installed", blocked=("x",))
        self.assertEqual([kind for kind, _ in log], ["copy", "notify"])
        self.assertEqual(log[0][1], shown[0])
        self.assertIn("已复制", shown[0])

    def test_all_five_verdicts_copy_exactly_what_the_dialog_shows(self):
        for state, blocked, error in ATTRIBUTIONS:
            with self.subTest(state=state, blocked=blocked, error=error):
                log, shown, _ = self.run_with(state, blocked, error)
                self.assertEqual([kind for kind, _ in log], ["copy", "notify"])
                self.assertEqual(log[0][1], shown[0])

    def test_a_busy_clipboard_still_shows_the_dialog_with_the_ctrl_c_hint(self):
        log, shown, _ = self.run_with("installed", blocked=("x",),
                                      clipboard_error=OSError("剪贴板被占用"))
        self.assertEqual(len(shown), 1)
        self.assertIn("Ctrl+C", shown[0])
        self.assertIn("Unblock-File", shown[0])

    def test_a_busy_clipboard_still_opens_the_site_for_a_missing_runtime(self):
        _, shown, opened = self.run_with("missing", clipboard_error=OSError("剪贴板被占用"))
        self.assertIn("Evergreen Bootstrapper", shown[0])
        self.assertEqual(opened, [WEBVIEW2_URL])

    def test_a_clipboard_that_fails_another_way_does_not_swallow_the_dialog(self):
        """收容集合是整个 Exception：窗口版没有控制台，弹窗是用户唯一看得到的东西。"""
        _, shown, _ = self.run_with("installed", blocked=("x",),
                                    clipboard_error=UnicodeEncodeError(
                                        "utf-16-le", "\ud800", 0, 1, "孤立代理项"))
        self.assertEqual(len(shown), 1)
        self.assertIn("Ctrl+C", shown[0])


# 旧产品名与 0.4.0 起的名字；旧安装项写在哪个视图取决于当时的权限与 Inno 的架构设置，
# 所以按键名把四处可能的位置都写死，不从被测代码里取。
OLD_PRODUCT = "安卓去广告"
NEW_PRODUCT = "肉呆去广告"
# Inno 的 UninstallDisplayName 默认是 AppVerName（AppName + 版本），旧版没有覆写它，
# 所以真实注册表里读到的是带版本后缀的串，不是产品名本身。
OLD_DISPLAY = OLD_PRODUCT + " 版本 0.3.2"
NEW_DISPLAY = NEW_PRODUCT + " 版本 0.4.0"
OLD_APP_ID = "{6C1E3F2A-8B7D-4E55-9A41-AAC0ADC1EA01}_is1"
OLD_USER = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + OLD_APP_ID
OLD_USER_WOW = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + OLD_APP_ID
OLD_MACHINE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + OLD_APP_ID
OLD_MACHINE_WOW = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + OLD_APP_ID

PORTABLE_DIR = r"C:\Users\me\Desktop\AndroidAdCleaner"
INSTALLED_DIR = r"C:\Program Files\AndroidAdCleaner"


def fake_values(values):
    """values: {(hive, 完整键路径, 值名): 值或异常}；不在表里的值一律当作不存在。"""
    def read(hive, path, name):
        value = values.get((hive, path, name))
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise FileNotFoundError(name)
        return value

    return read


def old_entry(hive="HKCU", key=OLD_USER, name=OLD_DISPLAY, path=INSTALLED_DIR):
    """一条卸载项：DisplayName 与安装目录；path=None 时两个目录值都不写。"""
    values = {(hive, key, "DisplayName"): name}
    if path is not None:
        values[(hive, key, "Inno Setup: App Path")] = path
    return values


class OldInstallTests(unittest.TestCase):
    """免安装版启动时，旧产品名的安装是否还留着（#872）。"""

    def present(self, values, exe_dir=PORTABLE_DIR):
        return winpreflight.old_install_present(fake_values(values), exe_dir=exe_dir)

    def test_an_old_install_next_to_a_portable_copy_is_reported(self):
        self.assertTrue(self.present(old_entry()))

    def test_the_same_install_is_found_in_every_registry_view(self):
        for hive, key in (("HKCU", OLD_USER), ("HKCU", OLD_USER_WOW),
                          ("HKLM", OLD_MACHINE), ("HKLM", OLD_MACHINE_WOW)):
            with self.subTest(hive=hive, key=key):
                self.assertTrue(self.present(old_entry(hive=hive, key=key)))

    def test_every_display_name_inno_can_produce_still_matches(self):
        """没下到中文语言包时是英文模板，Inno 6.3 起还可能追加架构 / 安装范围的后缀。"""
        for name in (OLD_DISPLAY, OLD_PRODUCT + " version 0.3.2",
                     OLD_DISPLAY + " (64 位)", OLD_PRODUCT):
            with self.subTest(name=name):
                self.assertTrue(self.present(old_entry(name=name)))

    def test_a_current_install_under_the_new_name_is_not_reported(self):
        self.assertFalse(self.present(old_entry(name=NEW_DISPLAY)))

    def test_no_uninstall_entry_is_not_reported(self):
        self.assertFalse(self.present({}))

    def test_a_reader_that_raises_stays_silent(self):
        self.assertFalse(winpreflight.old_install_present(
            always_raise(OSError("拒绝访问")), exe_dir=PORTABLE_DIR))

    def test_the_installed_copy_running_from_its_own_folder_is_not_reported(self):
        self.assertFalse(self.present(old_entry(), exe_dir=INSTALLED_DIR))

    def test_path_comparison_ignores_case_and_a_trailing_separator(self):
        self.assertFalse(self.present(old_entry(), exe_dir=INSTALLED_DIR.upper() + "\\"))

    def test_install_location_stands_in_when_the_inno_value_is_missing(self):
        values = {("HKCU", OLD_USER, "DisplayName"): OLD_PRODUCT,
                  ("HKCU", OLD_USER, "InstallLocation"): INSTALLED_DIR}
        self.assertTrue(self.present(values))
        self.assertFalse(self.present(values, exe_dir=INSTALLED_DIR))

    def test_an_entry_without_install_folder_still_counts(self):
        """读不出目录就没法证明新版顶掉了它，宁可信其有——提示只是提示，不动任何文件。"""
        self.assertTrue(self.present(old_entry(path=None)))

    def test_a_broken_entry_does_not_hide_a_later_one(self):
        values = {("HKCU", OLD_USER, "DisplayName"): PermissionError("拒绝访问")}
        values.update(old_entry(hive="HKLM", key=OLD_MACHINE))
        self.assertTrue(self.present(values))

    @unittest.skipIf(sys.platform == "win32", "Windows 上默认读取会真读注册表")
    def test_default_reader_does_not_raise_off_windows(self):
        self.assertFalse(winpreflight.old_install_present(exe_dir=PORTABLE_DIR))


if __name__ == "__main__":
    unittest.main()
