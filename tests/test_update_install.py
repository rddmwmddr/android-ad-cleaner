"""#888：在临时目录里真正换文件，验证回滚、保留卸载器和新进程健康回执。"""
import json
import os
import plistlib
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from gui import update_install as install
from gui import update_manifest
from gui.updates import UpdateError


def windows_tree(root, content):
    root.mkdir(parents=True, exist_ok=True)
    for name in install.WINDOWS_FILES[:-1]:
        (root / name).write_text(content, encoding='utf-8')
    (root / '_internal').mkdir()
    (root / '_internal' / 'runtime.dll').write_text(content, encoding='utf-8')


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.target, self.prepared = self.root / 'installed', self.root / 'updates/install-test/prepared'
        windows_tree(self.target, 'old')
        windows_tree(self.prepared, 'new')
        self.work = self.prepared.parent
        self.plan = dict(schema=1, token='a' * 32, platform='win32', target=str(self.target),
                         prepared=str(self.prepared), version='0.4.2', parent_pid=1234,
                         executable='AndroidAdCleaner.exe', health=str(self.work / 'healthy.json'),
                         ready=str(self.work / 'ready.json'), result=str(self.work.parent / 'last-result.json'),
                         handoff=str(self.work.parent / 'handoff.json'))
        self.plan_path = self.work / 'plan.json'
        self.write_plan()
        self.child = Mock()
        self.child.poll.return_value = None
        self.launches = []

    def write_plan(self):
        install.write_json(self.plan_path, self.plan)
        install.write_json(self.plan['handoff'], self.plan)

    def start(self, args, **kwargs):
        self.launches.append((args, kwargs))
        return self.child

    def run_helper(self, **kwargs):
        return install.apply_update(self.plan_path, alive=lambda _: False, sleep=lambda _: None,
                                    launch=self.start, attempts=3, **kwargs)

    def assert_old(self):
        self.assertEqual((self.target / 'AndroidAdCleaner.exe').read_text(), 'old')
        self.assertEqual((self.target / '_internal/runtime.dll').read_text(), 'old')

    def test_success_requires_correct_new_version_and_token(self):
        (self.target / 'unins000.exe').write_text('uninstaller')
        (self.target / 'user.txt').write_text('user file')
        def start(args, **kwargs):
            self.start(args, **kwargs)
            self.assertEqual((self.target / 'AndroidAdCleaner.exe').read_text(), 'new')
            install.confirm_started(self.work.parent, '0.4.2', args[0])
            return self.child
        rc = install.apply_update(self.plan_path, alive=lambda _: False, sleep=lambda _: None, launch=start, attempts=3)
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(Path(self.plan['result']).read_text(encoding='utf-8'))['ok'])
        self.assertEqual((self.target / 'unins000.exe').read_text(), 'uninstaller')
        self.assertEqual((self.target / 'user.txt').read_text(), 'user file')
        self.assertEqual(self.launches[0][1]['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertFalse(Path(self.plan['handoff']).exists())
        self.assertFalse(list(self.target.glob('.aac-*')))
        self.child.terminate.assert_not_called()

    def test_new_app_crash_rolls_back_and_relaunches_old(self):
        self.child.poll.return_value = 1
        self.assertEqual(self.run_helper(), 1)
        self.assert_old()
        self.assertEqual(len(self.launches), 2)
        self.assertIn('恢复', json.loads(Path(self.plan['result']).read_text(encoding='utf-8'))['error'])
        self.assertFalse(list(self.target.glob('.aac-*')), '回滚成功后不能把临时目录留在程序目录里')
        self.child.terminate.assert_not_called()

    def test_new_app_hang_is_terminated_before_rollback(self):
        self.assertEqual(self.run_helper(), 1)
        self.assert_old()
        self.child.terminate.assert_called_once()
        self.child.wait.assert_called_once_with(timeout=15)
        self.assertEqual(len(self.launches), 2)

    def test_unresponsive_new_app_is_killed_before_rollback(self):
        self.child.wait.side_effect = [subprocess.TimeoutExpired('app', 15), 0]
        self.assertEqual(self.run_helper(), 1)
        self.child.kill.assert_called_once()
        self.assert_old()

    def test_parent_still_alive_never_replaces(self):
        rc = install.apply_update(self.plan_path, alive=lambda _: True, sleep=lambda _: None,
                                  launch=self.start, attempts=2)
        self.assertEqual(rc, 1)
        self.assert_old()
        self.assertEqual(self.launches, [])
        self.assertIn('没有退出', json.loads(Path(self.plan['result']).read_text(encoding='utf-8'))['error'])

    def test_wrong_health_cannot_commit_new_version(self):
        install.write_json(self.plan['health'], dict(token='b' * 32, version='0.4.2'))
        self.assertEqual(self.run_helper(), 1)
        self.assert_old()

    def test_old_or_other_executable_cannot_confirm_health(self):
        for version, exe in [('0.4.1', self.target / 'AndroidAdCleaner.exe'),
                             ('0.4.2', self.prepared / 'AndroidAdCleaner.exe')]:
            install.confirm_started(self.work.parent, version, exe)
            self.assertFalse(Path(self.plan['health']).exists())

    def test_partial_replace_failure_restores_all_original_files(self):
        real_replace = os.replace
        calls = []
        def replace(source, dest):
            calls.append((source, dest))
            if str(source).endswith('.aac-new-' + self.plan['token'] + os.sep + 'aac-cli.exe'):
                raise PermissionError('file locked')
            return real_replace(source, dest)
        replacement = install.Replacement(self.target, self.prepared, 'win32', self.plan['token'])
        with patch.object(install.os, 'replace', side_effect=replace) as operation:
            with self.assertRaisesRegex(PermissionError, 'locked'):
                replacement.install()
            self.assertGreater(operation.call_count, 4)
        self.assert_old()
        self.assertEqual((self.target / 'aac-cli.exe').read_text(), 'old')
        self.assertEqual(replacement.new, [])
        self.assertEqual(replacement.old, [])

    def test_failed_replace_cleans_its_own_temporary_directories(self):
        """install() 自己回滚后要顺手清掉 .aac-*：这时 _apply_plan 的 replaced 还是 False。"""
        real_replace = os.replace

        def replace(source, dest):
            if str(source).endswith('.aac-new-' + self.plan['token'] + os.sep + 'aac-cli.exe'):
                raise PermissionError('file locked')
            return real_replace(source, dest)

        replacement = install.Replacement(self.target, self.prepared, 'win32', self.plan['token'])
        with patch.object(install.os, 'replace', side_effect=replace):
            with self.assertRaises(PermissionError):
                replacement.install()
        self.assert_old()
        self.assertFalse(list(self.target.glob('.aac-*')), '回滚成功后不能把临时目录留在程序目录里')

    def test_cleanup_failure_after_health_does_not_rollback(self):
        def start(args, **kwargs):
            install.confirm_started(self.work.parent, '0.4.2', args[0])
            return self.child
        with patch.object(install.Replacement, 'cleanup', autospec=True, side_effect=OSError('cleanup failed')) as cleanup:
            self.assertEqual(install.apply_update(self.plan_path, alive=lambda _: False, sleep=lambda _: None,
                                                 launch=start, attempts=2), 0)
            cleanup.assert_called_once()
        self.assertEqual((self.target / 'AndroidAdCleaner.exe').read_text(), 'new')
        self.child.terminate.assert_not_called()

    def test_plan_cannot_write_receipt_or_health_outside_work(self):
        for key in ('health', 'result', 'ready', 'handoff', 'prepared'):
            original = self.plan[key]
            self.plan[key] = str(self.root / 'outside')
            self.write_plan()
            with self.subTest(key=key), self.assertRaises(UpdateError):
                install.validate_plan(self.plan_path)
            self.plan[key] = original

    def test_second_helper_cannot_replace_or_overwrite_active_handoff(self):
        handoff = Path(self.plan['handoff'])
        handoff.write_text('first helper owns this plan', encoding='utf-8')
        with install.installation_lock(self.work.parent):
            with self.assertRaisesRegex(UpdateError, '另一个窗口'):
                self.run_helper()
            self.assertEqual(handoff.read_text(), 'first helper owns this plan')
            # 父窗口靠这份回执把「另一个窗口在装」说出来，而不是「助手没起来」。
            self.assertIn('另一个窗口', json.loads(
                (self.work / 'error.json').read_text(encoding='utf-8'))['error'])
            self.assert_old()
            self.assertEqual(self.launches, [])
        self.child.poll.return_value = 1
        self.assertEqual(self.run_helper(), 1)
        self.assertEqual(len(self.launches), 2)

    def test_helper_that_exits_before_ready_reports_its_own_reason(self):
        """锁冲突时助手直接退出：父窗口要把它的原因说出来，不能报成「助手没起来」。"""
        archive = self.root / 'update.zip'
        with zipfile.ZipFile(archive, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/_internal/python.dll', b'runtime')

        class Exited:
            def poll(self):
                return 1

        def popen(args, **kwargs):
            plan = json.loads(Path(args[2]).read_text(encoding='utf-8'))
            Path(plan['ready']).parent.joinpath('error.json').write_text(
                json.dumps({'error': '另一个窗口正在安装更新，请等它完成后重试'}, ensure_ascii=False), encoding='utf-8')
            return Exited()

        adapter = install.DesktopInstaller(self.work.parent, system='win32',
                                           executable=self.target / 'AndroidAdCleaner.exe', frozen=True, popen=popen)
        aged = self.work.parent / 'install-yesterday'
        aged.mkdir()
        os.utime(aged, (1, 1))
        before = set(self.work.parent.glob('install-*'))
        # 非 Windows 上这两个常量不存在；测的是父窗口怎么读助手的退出原因，不是进程属性。
        with patch.object(install.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                patch.object(install.subprocess, 'DETACHED_PROCESS', 0, create=True):
            with self.assertRaisesRegex(UpdateError, '另一个窗口'):
                adapter.install(archive, '0.4.2')
        self.assertEqual(set(self.work.parent.glob('install-*')) - before, set(), '助手没接手时准备目录由本进程清掉')
        self.assertFalse(aged.exists(), '开始一次安装时要顺手清掉一天前没收尾的准备目录')

    def test_stale_preparation_directories_are_swept_on_next_start(self):
        root = self.root / 'updates'
        old, fresh = root / 'install-old', root / 'install-fresh'
        old.mkdir(parents=True)
        fresh.mkdir()
        os.utime(old, (1, 1))
        install.sweep_stale(root)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists(), '另一个窗口刚建的准备目录不能清')

    def test_source_mode_rejects_install_without_touching_target(self):
        adapter = install.DesktopInstaller(self.work.parent, system='win32', executable=self.target / 'AndroidAdCleaner.exe', frozen=False)
        with self.assertRaisesRegex(UpdateError, '源码'):
            adapter.install(self.root / 'update.zip', '0.4.2')
        self.assert_old()


class ZipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive(self, extra=None):
        path = self.root / 'update.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/_internal/python.dll', b'runtime')
            if extra is not None:
                if isinstance(extra, str):
                    info = zipfile.ZipInfo()
                    # #888：写入原始坏路径，不能让 Windows 的 ZipInfo 构造先修正它。
                    info.filename = extra
                    extra = info
                zf.writestr(extra, b'evil')
        return path

    def test_real_zip_extracts_only_product_files(self):
        prepared = install.safe_extract(self.archive(), self.root / 'extract')
        self.assertEqual((prepared / '_internal/python.dll').read_bytes(), b'runtime')

    def test_bad_paths_rejected_before_any_extraction(self):
        names = ['../outside', 'AndroidAdCleaner/../outside', 'AndroidAdCleaner/_internal/../oops',
                 'AndroidAdCleaner/_internal/./x', 'AndroidAdCleaner/_internal//x',
                 'AndroidAdCleaner/unins000.exe', 'AndroidAdCleaner/_internal/nul.txt',
                 'AndroidAdCleaner/_internal/evil:stream', 'AndroidAdCleaner/_internal/a. ',
                 'AndroidAdCleaner/_internal\\evil', 'AndroidAdCleaner/AAC-CLI.EXE']
        for name in names:
            with self.subTest(name=name), self.assertRaises(UpdateError):
                install.safe_extract(self.archive(name), self.root / 'extract')
            self.assertFalse((self.root / 'extract').exists())

    def test_symlink_entries_rejected(self):
        info = zipfile.ZipInfo('AndroidAdCleaner/_internal/link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(UpdateError):
            install.safe_extract(self.archive(info), self.root / 'extract')

    def test_windows_normalization_does_not_hide_backslash(self):
        archive = self.archive('AndroidAdCleaner/_internal\\evil')
        with patch.object(zipfile.os, 'sep', '\\'):
            with zipfile.ZipFile(archive) as zf:
                entry = zf.infolist()[-1]
                self.assertEqual(entry.filename, 'AndroidAdCleaner/_internal/evil')
                self.assertEqual(entry.orig_filename, 'AndroidAdCleaner/_internal\\evil')
            with self.assertRaises(UpdateError):
                install.safe_extract(archive, self.root / 'extract')
        self.assertFalse((self.root / 'extract').exists())


class MacTests(unittest.TestCase):
    def test_whole_bundle_replaced_and_restored_with_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / 'App.app', root / 'prepared/App.app'
            for path, version in ((old, '0.4.1'), (new, '0.4.2')):
                (path / 'Contents/MacOS').mkdir(parents=True)
                (path / 'Contents/MacOS/program').write_text(version)
            swap = install.Replacement(old, new, 'darwin', 'a' * 32)
            swap.install()
            self.assertEqual((old / 'Contents/MacOS/program').read_text(), '0.4.2')
            swap.rollback()
            self.assertEqual((old / 'Contents/MacOS/program').read_text(), '0.4.1')

    def test_prepare_checks_bundle_version_signature_and_notarization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commands = []
            def run(args, **kwargs):
                commands.append(args)
                if args[:2] == ['/usr/bin/hdiutil', 'attach']:
                    candidate = root / 'mount/Update.app/Contents'
                    candidate.mkdir(parents=True)
                    with (candidate / 'Info.plist').open('wb') as stream:
                        plistlib.dump(dict(CFBundleIdentifier=install.BUNDLE_ID, CFBundleShortVersionString='0.4.2'), stream)
                return subprocess.CompletedProcess(args, 0, stderr='TeamIdentifier=TEST123\n')
            prepared = install.prepare_mac(root / 'update.dmg', root, root / 'Old.app', '0.4.2', run=run)
            self.assertEqual(prepared, root / 'Old.app')
            self.assertTrue(any(x[:4] == ['/usr/bin/codesign', '--verify', '--deep', '--strict'] for x in commands))
            self.assertTrue(any(x[:4] == ['/usr/sbin/spctl', '--assess', '--type', 'execute'] for x in commands))
            self.assertEqual(commands[-1][:2], ['/usr/bin/hdiutil', 'detach'])


class GeneratorTests(unittest.TestCase):
    def test_public_release_creates_four_valid_artifacts(self):
        from test_updates import manifest
        data = manifest()
        release = dict(tag_name='v0.4.2', assets=[dict(name=x['file'], size=x['size'], digest='sha256:' + x['sha256'])
                                                for x in data['artifacts'].values()])
        self.assertEqual(update_manifest.generate(release), data)
        release['draft'] = True
        with self.assertRaises(ValueError):
            update_manifest.generate(release)
        release['draft'] = False
        release['assets'][0]['digest'] = None
        with self.assertRaises(ValueError):
            update_manifest.generate(release)
