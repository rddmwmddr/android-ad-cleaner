"""#888：在临时目录里真正换文件，验证回滚、保留卸载器和新进程健康回执。"""
import json
import os
import plistlib
import stat
import subprocess
import sys
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


class FakeHelper:
    """更新助手的替身：`exit_after` 次 poll 返回 None，之后返回退出码 1。"""

    def __init__(self, *, exit_after=None):
        self.calls = 0
        self.exit_after = exit_after

    def poll(self):
        self.calls += 1
        return None if self.exit_after is None or self.calls <= self.exit_after else 1

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class RecordingChild:
    """新程序的替身：记录终止与等待，`hang_on_terminate` 时第一次 wait 超时。"""

    def __init__(self, *, exit_after=None, hang_on_terminate=False):
        self.polls = 0
        self.exit_after = exit_after
        self.hang_on_terminate = hang_on_terminate
        self.terminated = 0
        self.waits = []
        self.killed = 0

    def poll(self):
        self.polls += 1
        return None if self.exit_after is None or self.polls <= self.exit_after else 1

    def terminate(self):
        self.terminated += 1

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.hang_on_terminate and len(self.waits) == 1:
            raise subprocess.TimeoutExpired('app', timeout or 0)
        return 0

    def kill(self):
        self.killed += 1


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
        self.sleeps = []

    def write_plan(self):
        install.write_json(self.plan_path, self.plan)
        install.write_json(self.plan['handoff'], self.plan)

    def start(self, args, **kwargs):
        self.launches.append((args, kwargs))
        return self.child

    def run_helper(self, *, launch=None, alive=None, attempts=3):
        self.sleeps = []
        return install.apply_update(self.plan_path, alive=alive or (lambda _: False),
                                    sleep=self.sleeps.append, launch=launch or self.start, attempts=attempts)

    def receipt(self):
        return json.loads(Path(self.plan['result']).read_text(encoding='utf-8'))

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
        rc = install.apply_update(self.plan_path, alive=lambda _: False, sleep=self.sleeps.append,
                                  launch=start, attempts=3)
        self.assertEqual(rc, 0)
        self.assertEqual(self.receipt(), {'ok': True, 'version': '0.4.2'})
        self.assertEqual((self.target / 'unins000.exe').read_text(), 'uninstaller')
        self.assertEqual((self.target / 'user.txt').read_text(), 'user file')
        args, kwargs = self.launches[0]
        self.assertEqual(args, [str(self.target / 'AndroidAdCleaner.exe')])
        self.assertEqual(kwargs['cwd'], str(self.target))
        self.assertEqual(kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertFalse(Path(self.plan['handoff']).exists())
        self.assertFalse(Path(self.plan['prepared']).exists(), '成功安装后暂存的程序副本要清掉')
        self.assertFalse(list(self.target.glob('.aac-*')))
        self.child.terminate.assert_not_called()
        self.assertEqual(json.loads(Path(self.plan['ready']).read_text(encoding='utf-8')),
                         {'token': self.plan['token']})
        self.assertEqual(json.loads(Path(self.plan['health']).read_text(encoding='utf-8')),
                         {'token': self.plan['token'], 'version': '0.4.2'})

    def test_new_app_crash_rolls_back_and_relaunches_old(self):
        self.child.poll.return_value = 1
        def start(args, **kwargs):
            self.start(args, **kwargs)
            Path(self.plan['handoff']).unlink(missing_ok=True)   # 父窗口已经取走回执
            return self.child
        self.assertEqual(self.run_helper(launch=start), 1)
        self.assert_old()
        self.assertEqual(self.launches[0][0], [str(self.target / 'AndroidAdCleaner.exe')])
        self.assertEqual(self.launches[0][1]['cwd'], str(self.target))
        self.assertEqual(self.launches[1][0], [str(self.target / 'AndroidAdCleaner.exe')])
        self.assertEqual(self.launches[1][1]['cwd'], str(self.target))
        self.assertEqual(self.launches[1][1]['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertEqual(self.receipt(),
                         {'ok': False, 'version': '0.4.2', 'error': '新版没有正常打开，已恢复原版本'})
        self.assertEqual(self.sleeps, [], '新程序已经退出，不再空等')
        self.assertFalse(Path(self.plan['handoff']).exists())
        self.assertFalse(list(self.target.glob('.aac-*')), '回滚成功后不能把临时目录留在程序目录里')
        self.child.terminate.assert_not_called()

    def test_new_app_hang_is_terminated_before_rollback(self):
        self.child = RecordingChild()
        self.assertEqual(self.run_helper(), 1)
        self.assert_old()
        self.assertEqual(self.child.terminated, 1)
        self.assertEqual(self.child.waits, [15])
        self.assertEqual(self.child.killed, 0)
        self.assertEqual(self.sleeps, [0.5, 0.5, 0.5], '等新版界面确认的轮询间隔')
        self.assertEqual(len(self.launches), 2)

    def test_unresponsive_new_app_is_killed_before_rollback(self):
        self.child = RecordingChild(hang_on_terminate=True)
        self.assertEqual(self.run_helper(), 1)
        self.assertEqual(self.child.killed, 1)
        self.assertEqual(self.child.waits, [15, 15])
        self.assert_old()

    def test_parent_still_alive_never_replaces(self):
        asked, sleeps = [], []
        rc = install.apply_update(self.plan_path, alive=lambda pid: asked.append(pid) or True,
                                  sleep=sleeps.append, launch=self.start, attempts=2)
        self.assertEqual(rc, 1)
        self.assert_old()
        self.assertEqual(self.launches, [])
        self.assertEqual(self.receipt(),
                         {'ok': False, 'version': '0.4.2', 'error': '原程序没有退出，本次更新未安装'})
        self.assertEqual(asked, [1234, 1234, 1234], '最后一次是决定要不要拉起旧程序')
        self.assertEqual(sleeps, [0.5, 0.5])
        self.assertEqual(json.loads(Path(self.plan['ready']).read_text(encoding='utf-8')),
                         {'token': self.plan['token']})

    def test_apply_update_waits_sixty_seconds_by_default(self):
        """默认预算 120 次 × 0.5 秒：父程序一直不退时按这个上限收手。"""
        asked, sleeps = [], []
        rc = install.apply_update(self.plan_path, alive=lambda pid: asked.append(pid) or True,
                                  sleep=sleeps.append, launch=self.start)
        self.assertEqual(rc, 1)
        self.assertEqual(len(asked), 121, '120 次轮询后还要再问一次要不要拉起旧程序')
        self.assertEqual(sleeps, [0.5] * 120)
        self.assertEqual(self.launches, [])

    def test_wrong_health_cannot_commit_new_version(self):
        install.write_json(self.plan['health'], dict(token='b' * 32, version='0.4.2'))
        self.assertEqual(self.run_helper(), 1)
        self.assert_old()
        self.assertEqual(self.receipt(),
                         {'ok': False, 'version': '0.4.2', 'error': '新版没有正常打开，已恢复原版本'})

    def test_confirm_started_writes_health_for_the_running_new_version(self):
        exe = self.target / 'AndroidAdCleaner.exe'
        install.confirm_started(self.work.parent, '0.4.2', str(exe))
        self.assertEqual(json.loads(Path(self.plan['health']).read_text(encoding='utf-8')),
                         {'token': self.plan['token'], 'version': '0.4.2'})

    def test_confirm_started_uses_the_platform_launch_path(self):
        """mac 的新程序在 bundle 里的 Contents/MacOS 下：停在 bundle 根上的同名文件不算启动成功。"""
        target = self.root / 'Applications/Old.app'
        exe = target / 'Contents' / 'MacOS' / 'AndroidAdCleaner'
        install.write_json(Path(self.plan['handoff']),
                           dict(self.plan, platform='darwin', target=str(target), executable='AndroidAdCleaner'))
        install.confirm_started(self.work.parent, '0.4.2', str(exe))
        self.assertEqual(json.loads(Path(self.plan['health']).read_text(encoding='utf-8')),
                         {'token': self.plan['token'], 'version': '0.4.2'})

    def test_success_without_handoff_still_clears_the_staged_copy(self):
        def start(args, **kwargs):
            self.start(args, **kwargs)
            Path(self.plan['handoff']).unlink(missing_ok=True)
            install.write_json(self.plan['health'], {'token': self.plan['token'], 'version': '0.4.2'})
            return self.child
        self.assertEqual(self.run_helper(launch=start), 0)
        self.assertEqual(self.receipt(), {'ok': True, 'version': '0.4.2'})
        self.assertFalse(Path(self.plan['prepared']).exists(), '回执已不在也要把暂存的程序副本清掉')

    def test_failed_recovery_keeps_the_backup_and_reports_where(self):
        self.child.poll.return_value = 1
        backup = self.target / ('.aac-old-' + self.plan['token'])
        with patch.object(install.Replacement, 'rollback', autospec=True, side_effect=OSError('locked')):
            self.assertEqual(self.run_helper(), 1)
        self.assertEqual(self.receipt(), {
            'ok': False, 'version': '0.4.2',
            'error': f'新版没有正常打开，已恢复原版本；恢复未完成：locked。旧程序文件保留在 {backup}'})
        self.assertEqual((backup / 'AndroidAdCleaner.exe').read_text(), 'old')
        self.assertEqual((backup / '_internal/runtime.dll').read_text(), 'old')

    def test_darwin_plan_swaps_the_bundle_and_launches_inside_it(self):
        target = self.root / 'Applications/Old.app'
        info_plist(target)
        prepared = self.work / 'Old.app'
        info_plist(prepared)
        for path, content in ((target, 'old'), (prepared, 'new')):
            exe = path / 'Contents' / 'MacOS' / 'AndroidAdCleaner'
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text(content, encoding='utf-8')
        plan = dict(self.plan, platform='darwin', target=str(target), prepared=str(prepared),
                    executable='AndroidAdCleaner')
        install.write_json(self.plan_path, plan)
        install.write_json(plan['handoff'], plan)
        def start(args, **kwargs):
            self.start(args, **kwargs)
            self.assertEqual((target / 'Contents/MacOS/AndroidAdCleaner').read_text(), 'new')
            install.confirm_started(self.work.parent, '0.4.2', args[0])
            return self.child
        self.assertEqual(self.run_helper(launch=start), 0)
        args, kwargs = self.launches[0]
        self.assertEqual(args, [str(target / 'Contents' / 'MacOS' / 'AndroidAdCleaner')])
        self.assertEqual(kwargs['cwd'], str(target.parent))
        self.assertEqual(self.receipt(), {'ok': True, 'version': '0.4.2'})

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
        """install() 自己回滚后要顺手清掉 .aac-*：这时 _apply_plan 不该再滚一次。"""
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
            self.assertEqual(install.apply_update(self.plan_path, alive=lambda _: False, sleep=self.sleeps.append,
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
        with self.assertRaises(UpdateError) as caught:
            adapter.install(self.root / 'update.zip', '0.4.2')
        self.assertEqual(str(caught.exception), '源码运行时不替换程序，请更新源码或安装正式版')
        self.assert_old()

    def win_archive(self):
        path = self.root / 'update.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/_internal/python.dll', b'runtime')
        return path

    def popen_writing_ready(self, helper=None):
        helper = helper or FakeHelper()
        def popen(args, **kwargs):
            self.launches.append((args, kwargs))
            plan = json.loads(Path(args[2]).read_text(encoding='utf-8'))
            Path(plan['ready']).write_text('{}', encoding='utf-8')
            return helper
        return popen

    def test_win32_install_prepares_helper_plan_and_launch(self):
        """准备段的外部结果：建好助手目录、写对计划、按计划拉起助手——一次装完。"""
        root = self.root / 'a/b/updates'   # 父目录不存在：必须 parents=True 建出来
        adapter = install.DesktopInstaller(root, system='win32',
                                           executable=self.target / 'AndroidAdCleaner.exe',
                                           frozen=True, popen=self.popen_writing_ready())
        with patch.object(install.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), \
                patch.object(install.subprocess, 'DETACHED_PROCESS', 0x8, create=True):
            result = adapter.install(self.win_archive(), '0.4.2')
        self.assertEqual(result, {'exit': True, 'message': '正在退出并安装更新，完成后会自动重新打开'})
        self.assertTrue(root.is_dir(), '嵌套的安装缓存根目录要一次建全')
        args, kwargs = self.launches[0]
        work = Path(args[2]).parent
        plan = json.loads(Path(args[2]).read_text(encoding='utf-8'))
        self.assertEqual(work.parent, root)
        self.assertTrue(work.name.startswith('install-'))
        self.assertEqual(plan, {
            'schema': 1, 'token': plan['token'], 'platform': 'win32', 'target': str(self.target),
            'prepared': str(work / 'extracted' / 'AndroidAdCleaner'), 'version': '0.4.2',
            'parent_pid': os.getpid(), 'executable': 'AndroidAdCleaner.exe',
            'health': str(work / 'healthy.json'), 'ready': str(work / 'ready.json'),
            'result': str(root / 'last-result.json'), 'handoff': str(root / 'handoff.json')})
        self.assertRegex(plan['token'], r'\A[0-9a-f]{32}\Z')
        self.assertEqual(args, [str(work / 'helper' / 'aac-cli.exe'), '--apply-update', str(work / 'plan.json')])
        self.assertTrue((work / 'helper' / 'aac-cli.exe').is_file())
        self.assertTrue((work / 'helper' / 'aac-cli.exe.config').is_file())
        self.assertTrue((work / 'helper' / '_internal' / 'runtime.dll').is_file())
        self.assertEqual(kwargs['creationflags'], 0x08000000 | 0x8)
        self.assertNotIn('start_new_session', kwargs)
        self.assertEqual(kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')

    def test_unsupported_platform_is_refused(self):
        adapter = install.DesktopInstaller(self.root / 'updates', system='linux',
                                           executable=self.target / 'AndroidAdCleaner.exe', frozen=True)
        with self.assertRaises(UpdateError) as caught:
            adapter.install(self.win_archive(), '0.4.2')
        self.assertEqual(str(caught.exception), '当前平台暂不支持应用内安装')

    def test_helper_that_exits_without_ready_reports_the_generic_reason(self):
        class Exited:
            def poll(self):
                return 1

        adapter = install.DesktopInstaller(self.root / 'updates', system='win32',
                                           executable=self.target / 'AndroidAdCleaner.exe',
                                           frozen=True, popen=lambda args, **kwargs: Exited())
        with patch.object(install.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                patch.object(install.subprocess, 'DETACHED_PROCESS', 0, create=True):
            with self.assertRaises(UpdateError) as caught:
                adapter.install(self.win_archive(), '0.4.2')
        self.assertEqual(str(caught.exception), '更新助手未能启动，原程序仍可继续使用')

    def test_helper_timeout_waits_the_full_budget_then_explains(self):
        """助手始终不写 ready：等满 100 次（每次 0.1 秒）才放弃，文案说清楚原程序还能用。"""
        helper = FakeHelper(exit_after=100)   # 第 101 次 poll 才「退出」，把第 100 次与第 101 次区分开
        sleeps = []
        adapter = install.DesktopInstaller(self.root / 'updates', system='win32',
                                           executable=self.target / 'AndroidAdCleaner.exe',
                                           frozen=True, popen=lambda args, **kwargs: helper)
        with patch.object(install.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                patch.object(install.subprocess, 'DETACHED_PROCESS', 0, create=True), \
                patch.object(install.time, 'sleep', lambda seconds: sleeps.append(seconds)):
            with self.assertRaises(UpdateError) as caught:
                adapter.install(self.win_archive(), '0.4.2')
        self.assertEqual(str(caught.exception), '更新助手启动超时，原程序仍可继续使用')
        self.assertEqual(sleeps, [0.1] * 100)


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

    def test_product_directory_keeps_its_exact_name(self):
        prepared = install.safe_extract(self.archive(), self.root / 'extract')
        self.assertEqual(prepared.name, 'AndroidAdCleaner')
        self.assertEqual(prepared, self.root / 'extract' / 'AndroidAdCleaner')

    def test_valid_directory_entry_is_accepted(self):
        """带尾斜杠的目录条目（含顶层 `AndroidAdCleaner/`）是合法的，不能被当成坏路径。"""
        path = self.root / 'dirs.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/', b'')
            zf.writestr('AndroidAdCleaner/_internal/', b'')
            zf.writestr('AndroidAdCleaner/_internal/python.dll', b'runtime')
        prepared = install.safe_extract(path, self.root / 'extract')
        self.assertEqual((prepared / '_internal/python.dll').read_bytes(), b'runtime')

    def test_trailing_x_in_a_filename_is_kept(self):
        """重复判定不能顺手吞掉文件名末尾的 `X`：`aaX` 与 `aa` 是两个不同的文件。"""
        path = self.root / 'x-names.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/_internal/aa', b'one')
            zf.writestr('AndroidAdCleaner/_internal/aaX', b'two')
            zf.writestr('AndroidAdCleaner/_internal/X', b'three')
        prepared = install.safe_extract(path, self.root / 'extract')
        self.assertEqual((prepared / '_internal/aa').read_bytes(), b'one')
        self.assertEqual((prepared / '_internal/aaX').read_bytes(), b'two')
        self.assertEqual((prepared / '_internal/X').read_bytes(), b'three')

    def test_a_component_with_a_space_before_a_trailing_x_is_kept(self):
        """`rstrip("/")` 只剥尾斜杠：`_internal/ X` 是合法文件名，不能被顺带剥掉末尾的 `X`。"""
        path = self.root / 'space-x.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/_internal/ X', b'four')
        prepared = install.safe_extract(path, self.root / 'extract')
        self.assertEqual((prepared / '_internal/ X').read_bytes(), b'four')

    def assert_rejected(self, name, message):
        with self.assertRaises(UpdateError) as caught:
            install.safe_extract(self.archive(name), self.root / 'extract')
        self.assertEqual(str(caught.exception), message)
        self.assertFalse((self.root / 'extract').exists())

    def test_each_rejection_says_what_is_wrong(self):
        """每条拒绝各有各的说法：文案是用户看到的唯一区分，不能被替换成别的分支。"""
        self.assert_rejected('../outside', '更新包包含不安全的文件路径')
        self.assert_rejected('Other/file', '更新包包含不安全的文件路径')
        self.assert_rejected('AndroidAdCleaner/_internal/sub\\x', '更新包包含不安全的文件路径')
        self.assert_rejected('AndroidAdCleaner/unins000.exe', '更新包包含不属于本程序的顶层文件')
        self.assert_rejected('AndroidAdCleaner/_internal/nul.txt', '更新包包含系统保留文件名')

    def test_special_file_mode_is_rejected(self):
        """非普通文件、非目录、非符号链接（如 FIFO）一律当成不安全条目。"""
        info = zipfile.ZipInfo('AndroidAdCleaner/_internal/fifo')
        info.external_attr = (stat.S_IFIFO | 0o644) << 16
        with self.assertRaises(UpdateError) as caught:
            install.safe_extract(self.archive(info), self.root / 'extract')
        self.assertEqual(str(caught.exception), '更新包包含不安全的文件路径')
        self.assertFalse((self.root / 'extract').exists())

    def test_duplicate_entries_are_rejected(self):
        path = self.root / 'dup.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/_internal/python.dll', b'runtime')
            zf.writestr('AndroidAdCleaner/_internal/PYTHON.DLL', b'other')
        with self.assertRaises(UpdateError) as caught:
            install.safe_extract(path, self.root / 'extract')
        self.assertEqual(str(caught.exception), '更新包包含重复文件')
        self.assertFalse((self.root / 'extract').exists())

    def test_duplicate_detection_ignores_a_directory_trailing_slash(self):
        """同一条路径既作为文件又作为带尾斜杠的目录出现时算重复。"""
        path = self.root / 'dup-slash.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/_internal', b'program')
            zf.writestr('AndroidAdCleaner/_internal/', b'')
        with self.assertRaises(UpdateError) as caught:
            install.safe_extract(path, self.root / 'extract')
        self.assertEqual(str(caught.exception), '更新包包含重复文件')

    def test_trailing_x_on_a_component_is_rejected(self):
        """路径校验按 `/` 切分，不能顺带吞掉 `X`：`_internalX/` 仍是本程序之外的顶层。"""
        self.assert_rejected('AndroidAdCleaner/_internalX/', '更新包包含不属于本程序的顶层文件')

    def test_missing_program_files_are_reported(self):
        # 缺一个 exe：四份程序文件不全
        path = self.root / 'missing.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-2]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            zf.writestr('AndroidAdCleaner/_internal/python.dll', b'runtime')
        with self.assertRaises(UpdateError) as caught:
            install.safe_extract(path, self.root / 'extract')
        self.assertEqual(str(caught.exception), '更新包缺少程序文件')
        # 缺 _internal 目录
        path = self.root / 'no-internal.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
        with self.assertRaises(UpdateError) as caught:
            install.safe_extract(path, self.root / 'extract2')
        self.assertEqual(str(caught.exception), '更新包缺少程序文件')

    def test_expanded_size_boundary_is_inclusive(self):
        """恰好等于上限允许，超过才拒绝；`>` 与 `>=` 的差别只在这一点上。"""
        archive = self.archive()
        with zipfile.ZipFile(archive) as zf:
            total = sum(info.file_size for info in zf.infolist())
        with patch.object(install, 'MAX_EXPANDED', total):
            prepared = install.safe_extract(archive, self.root / 'extract')
        self.assertEqual(prepared.name, 'AndroidAdCleaner')
        with patch.object(install, 'MAX_EXPANDED', total - 1), \
                self.assertRaises(UpdateError) as caught:
            install.safe_extract(archive, self.root / 'extract2')
        self.assertEqual(str(caught.exception), '更新包解压后的大小异常')

    def count_archive(self, count, path):
        """`count` 条条目，最后一条是坏顶层路径：越界前就停在校验阶段，不必真解压几万份。"""
        with zipfile.ZipFile(path, 'w') as zf:
            for name in install.WINDOWS_FILES[:-1]:
                zf.writestr('AndroidAdCleaner/' + name, b'program')
            for i in range(count - len(install.WINDOWS_FILES[:-1]) - 1):
                zf.writestr(f'AndroidAdCleaner/_internal/f{i}', b'')
            zf.writestr('AndroidAdCleaner/unins000.exe', b'foreign')
        return path

    def test_entry_count_boundary_is_30000(self):
        """上限 30000 条：30000 条不因条数被拒（走到后面的路径校验），30001 条报大小异常。"""
        at_limit = self.count_archive(30000, self.root / 'at-limit.zip')
        with self.assertRaises(UpdateError) as caught:
            install.safe_extract(at_limit, self.root / 'extract-a')
        self.assertEqual(str(caught.exception), '更新包包含不属于本程序的顶层文件')
        over_limit = self.count_archive(30001, self.root / 'over-limit.zip')
        with self.assertRaises(UpdateError) as caught:
            install.safe_extract(over_limit, self.root / 'extract-b')
        self.assertEqual(str(caught.exception), '更新包解压后的大小异常')

    def test_bad_paths_rejected_before_any_extraction(self):
        names = ['../outside', 'AndroidAdCleaner/../outside', 'AndroidAdCleaner/_internal/../oops',
                 'AndroidAdCleaner/_internal/./x', 'AndroidAdCleaner/_internal//x',
                 'AndroidAdCleaner/unins000.exe', 'AndroidAdCleaner/_internal/nul.txt',
                 'AndroidAdCleaner/_internal/evil:stream', 'AndroidAdCleaner/_internal/a.',
                 'AndroidAdCleaner/_internal/a. ', 'AndroidAdCleaner/_internal\\evil',
                 'AndroidAdCleaner/AAC-CLI.EXE']
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


def info_plist(path, *, identifier=install.BUNDLE_ID, version='0.4.2'):
    (path / 'Contents').mkdir(parents=True, exist_ok=True)
    with (path / 'Contents' / 'Info.plist').open('wb') as stream:
        plistlib.dump({'CFBundleIdentifier': identifier, 'CFBundleShortVersionString': version}, stream)


class ValidatePlanTests(unittest.TestCase):
    """助手动手之前只认这一份计划：格式、宿主、程序路径、状态路径各有各的拒绝文案。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.work = self.root / 'updates/install-test'
        self.work.mkdir(parents=True)
        self.win_target = self.root / 'installed'
        windows_tree(self.win_target, 'old')
        self.win_prepared = self.work / 'prepared'
        windows_tree(self.win_prepared, 'new')
        self.win_plan = dict(
            schema=1, token='a' * 32, platform='win32', target=str(self.win_target),
            prepared=str(self.win_prepared), version='0.4.2', parent_pid=1234,
            executable='AndroidAdCleaner.exe', health=str(self.work / 'healthy.json'),
            ready=str(self.work / 'ready.json'), result=str(self.work.parent / 'last-result.json'),
            handoff=str(self.work.parent / 'handoff.json'))
        self.darwin_target = self.root / 'Applications/Old.app'
        info_plist(self.darwin_target)
        self.darwin_prepared = self.work / 'Old.app'
        info_plist(self.darwin_prepared)
        self.darwin_plan = dict(self.win_plan)
        self.darwin_plan.update(platform='darwin', target=str(self.darwin_target),
                                prepared=str(self.darwin_prepared), executable='program')

    def plan_path(self, plan):
        path = self.work / 'plan.json'
        install.write_json(path, plan)
        return path

    def rejects(self, plan, message):
        with self.assertRaises(UpdateError) as caught:
            install.validate_plan(self.plan_path(plan))
        self.assertEqual(str(caught.exception), message)

    def test_complete_windows_and_darwin_plans_are_accepted(self):
        self.assertEqual(install.validate_plan(self.plan_path(self.win_plan)), self.win_plan)
        self.assertEqual(install.validate_plan(self.plan_path(self.darwin_plan)), self.darwin_plan)

    def test_a_pid_of_one_is_still_a_live_parent(self):
        plan = dict(self.win_plan, parent_pid=1)
        self.assertEqual(install.validate_plan(self.plan_path(plan))['parent_pid'], 1)

    def test_zero_pid_is_rejected(self):
        self.rejects(dict(self.win_plan, parent_pid=0), '更新任务的宿主无效')

    def test_bad_schema_or_token_is_reported_as_a_bad_format(self):
        self.rejects(dict(self.win_plan, schema=2), '更新任务格式无效')
        self.rejects(dict(self.win_plan, token='z' * 32), '更新任务格式无效')
        # 非字符串要在正则之前挡住：re.fullmatch 收到 int 抛的是 TypeError，不是更新任务格式错误
        self.rejects(dict(self.win_plan, token=123), '更新任务格式无效')
        missing = dict(self.win_plan)
        missing.pop('token')
        self.rejects(missing, '更新任务格式无效')

    def test_a_non_integer_pid_is_rejected(self):
        self.rejects(dict(self.win_plan, parent_pid='1234'), '更新任务的宿主无效')

    def test_an_unknown_platform_is_rejected(self):
        self.rejects(dict(self.win_plan, platform='linux'), '更新任务的宿主无效')

    def test_relative_target_is_rejected(self):
        self.rejects(dict(self.win_plan, target='installed'), '更新任务的程序路径无效')

    def test_symlinked_target_is_rejected(self):
        link = self.root / 'linked'
        link.symlink_to(self.win_target, target_is_directory=True)
        self.rejects(dict(self.win_plan, target=str(link)), '更新任务的程序路径无效')

    def test_file_target_is_rejected(self):
        file_target = self.root / 'file.txt'
        file_target.write_text('x', encoding='utf-8')
        self.rejects(dict(self.win_plan, target=str(file_target)), '更新任务的程序路径无效')

    def test_status_and_handoff_paths_outside_work_are_rejected(self):
        expectations = {'health': '更新任务的状态路径无效', 'ready': '更新任务的状态路径无效',
                        'result': '更新任务的状态路径无效', 'handoff': '更新任务的交接路径无效',
                        'prepared': '更新任务的程序路径无效'}
        for key, message in expectations.items():
            with self.subTest(key=key):
                self.rejects(dict(self.win_plan, **{key: str(self.root / 'outside')}), message)

    def test_darwin_target_must_be_our_app(self):
        not_app = self.root / 'NotApp'
        not_app.mkdir()
        self.rejects(dict(self.darwin_plan, target=str(not_app)), '目标不是本产品的 App')

    def test_darwin_target_with_a_foreign_bundle_is_rejected(self):
        foreign = self.root / 'Applications/Foreign.app'
        info_plist(foreign, identifier='com.example.other')
        self.rejects(dict(self.darwin_plan, target=str(foreign)), '目标不是本产品的 App')

    def test_darwin_prepared_must_match_identity_and_version(self):
        wrong_identity = self.work / 'Wrong.app'
        info_plist(wrong_identity, identifier='com.example.other')
        self.rejects(dict(self.darwin_plan, prepared=str(wrong_identity)), '新程序的标识无效')
        wrong_version = self.work / 'WrongVersion.app'
        info_plist(wrong_version, version='0.4.1')
        self.rejects(dict(self.darwin_plan, prepared=str(wrong_version)), '新程序的标识无效')

    def test_windows_plan_with_wrong_executable_is_rejected(self):
        self.rejects(dict(self.win_plan, executable='other.exe'), '目标不是完整的本产品安装目录')

    def test_windows_plan_missing_a_target_file_is_rejected(self):
        (self.win_target / 'aac-cli.exe').unlink()
        self.rejects(self.win_plan, '目标不是完整的本产品安装目录')

    def test_executable_must_be_a_bare_name(self):
        self.rejects(dict(self.darwin_plan, executable='sub/program'), '更新任务的启动文件无效')

    def test_empty_executable_is_rejected(self):
        self.rejects(dict(self.darwin_plan, executable=''), '更新任务的启动文件无效')


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

    def darwin_app(self, root, name='Old.app'):
        target = root / 'Applications' / name
        exe = target / 'Contents/MacOS/AndroidAdCleaner'
        exe.parent.mkdir(parents=True)
        exe.write_text('old', encoding='utf-8')
        return target, exe

    def test_darwin_install_prepares_a_helper_bundle_and_plan(self):
        """mac 准备段：把新包复制成 helper 整包，按 bundle 为 target 写计划并拉起它。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            if str(root).startswith('/Volumes/'):
                self.skipTest('目标落在 /Volumes/ 会先被 translocation 门禁拦下')
            target, exe = self.darwin_app(root)
            prepared = root / 'unused-prepared'
            prepare_calls, run_calls, launches = [], [], []
            def fake_prepare(archive, destination, installed, version):
                prepare_calls.append((archive, destination, installed, version))
                return prepared
            def fake_run(args, **kwargs):
                run_calls.append((args, kwargs))
                return subprocess.CompletedProcess(args, 0)
            def popen(args, **kwargs):
                launches.append((args, kwargs))
                plan = json.loads(Path(args[2]).read_text(encoding='utf-8'))
                Path(plan['ready']).write_text('{}', encoding='utf-8')
                return FakeHelper()
            archive = root / 'update.dmg'
            with patch.object(install, 'prepare_mac', fake_prepare), \
                    patch.object(install.subprocess, 'run', fake_run):
                adapter = install.DesktopInstaller(root / 'updates', system='darwin',
                                                   executable=exe, frozen=True, popen=popen)
                result = adapter.install(archive, '0.4.2')
            self.assertEqual(result, {'exit': True, 'message': '正在退出并安装更新，完成后会自动重新打开'})
            args, kwargs = launches[0]
            work = Path(args[2]).parent
            plan = json.loads(Path(args[2]).read_text(encoding='utf-8'))
            self.assertEqual(prepare_calls, [(archive, work, target, '0.4.2')])
            self.assertEqual(run_calls, [(
                ['/usr/bin/ditto', str(target), str(work / 'helper.app')],
                {'check': True, 'capture_output': True, 'timeout': 180})])
            self.assertEqual(args, [str(work / 'helper.app' / 'Contents' / 'MacOS' / 'AndroidAdCleaner'),
                                    '--apply-update', str(work / 'plan.json')])
            self.assertEqual(plan['target'], str(target))
            self.assertEqual(plan['prepared'], str(prepared))
            self.assertEqual(plan['platform'], 'darwin')
            self.assertEqual(plan['executable'], 'AndroidAdCleaner')
            self.assertTrue(kwargs['start_new_session'])
            self.assertNotIn('creationflags', kwargs)

    @unittest.skipIf(os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0),
                     '需要非 root 的 POSIX 权限位')
    def test_unwritable_install_directory_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            if str(root).startswith('/Volumes/'):
                self.skipTest('目标落在 /Volumes/ 会先被 translocation 门禁拦下')
            target, exe = self.darwin_app(root)
            os.chmod(root / 'Applications', 0o500)
            try:
                with patch.object(install, 'prepare_mac', lambda *a: root / 'p'), \
                        patch.object(install.subprocess, 'run', lambda a, **k: subprocess.CompletedProcess(a, 0)):
                    adapter = install.DesktopInstaller(root / 'updates', system='darwin',
                                                       executable=exe, frozen=True,
                                                       popen=lambda a, **k: FakeHelper())
                    with self.assertRaises(UpdateError) as caught:
                        adapter.install(root / 'update.dmg', '0.4.2')
                self.assertEqual(str(caught.exception),
                                 '当前安装目录不可写，请用管理员权限重新打开后更新，或从官网下载并覆盖安装；备份不受影响')
            finally:
                os.chmod(root / 'Applications', 0o700)

    @unittest.skipIf(os.name == 'nt', 'POSIX 的 /Volumes/ 前缀语义')
    def test_target_under_volumes_is_refused(self):
        adapter = install.DesktopInstaller(
            Path('/tmp/aac-1501-updates'), system='darwin', frozen=True,
            executable=Path('/Volumes/SomeDisk/Old.app/Contents/MacOS/AndroidAdCleaner'))
        with self.assertRaises(UpdateError) as caught:
            adapter.install(Path('/tmp/aac-1501.dmg'), '0.4.2')
        self.assertEqual(str(caught.exception), '请先把 App 放进「应用程序」，再从那里打开并更新')

    @unittest.skipIf(os.name == 'nt', 'POSIX 的 /tmp/ 前缀语义')
    def test_app_translocation_path_is_refused(self):
        adapter = install.DesktopInstaller(
            Path('/tmp/aac-1501-updates'), system='darwin', frozen=True,
            executable=Path('/tmp/AppTranslocation/Old.app/Contents/MacOS/AndroidAdCleaner'))
        with self.assertRaises(UpdateError) as caught:
            adapter.install(Path('/tmp/aac-1501.dmg'), '0.4.2')
        self.assertEqual(str(caught.exception), '请先把 App 放进「应用程序」，再从那里打开并更新')


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


class ToolsRun:
    """外部工具的替身：记录命令与参数，挂载时按需放好映像内容，并按路径给出签名团队。"""

    def __init__(self, *, teams=None, mount_app=None):
        self.calls = []
        self.teams = teams or {}
        self.mount_app = mount_app

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[:2] == ['/usr/bin/hdiutil', 'attach'] and self.mount_app is not None:
            self.mount_app()
        if args[:2] == ['/usr/bin/codesign', '-dv']:
            team = self.teams.get(args[-1])
            stderr = f'Executable={args[-1]}\n' + (f'TeamIdentifier={team}\n' if team else '')
            return subprocess.CompletedProcess(args, 0, stderr=stderr)
        return subprocess.CompletedProcess(args, 0)

    def kinds(self):
        return [tuple(args[:2]) for args, _ in self.calls]


class PrepareMacTests(unittest.TestCase):
    """DMG 准备段的外部过程：挂载、校验标识 / 版本 / 签名、复制新包、始终卸载。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.archive = self.root / 'update.dmg'
        self.archive.write_bytes(b'dmg')
        self.installed = self.root / 'Applications/Old.app'
        info_plist(self.installed)

    def mount_app(self, work, *, name='Update.app', identifier=install.BUNDLE_ID, version='0.4.2'):
        app = work / 'mount' / name
        info_plist(app, identifier=identifier, version=version)
        return app

    def prepare(self, tools, work=None):
        work = work or self.work
        work.mkdir(parents=True, exist_ok=True)
        return install.prepare_mac(self.archive, work, self.installed, '0.4.2', run=tools)

    def assert_update_steps(self, tools, app):
        attach, verify, assess, signing, installed_signing, ditto, detach = tools.calls
        self.assertEqual(attach[0], ['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint',
                                     str(self.work / 'mount'), str(self.archive)])
        self.assertEqual(attach[1], {'check': True, 'capture_output': True, 'timeout': 90})
        self.assertEqual(verify[0], ['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])
        self.assertEqual(verify[1], {'check': True, 'capture_output': True, 'timeout': 90})
        self.assertEqual(assess[0], ['/usr/sbin/spctl', '--assess', '--type', 'execute', str(app)])
        self.assertEqual(assess[1], {'check': True, 'capture_output': True, 'timeout': 90})
        self.assertEqual(signing[0][-1], str(app))
        self.assertEqual(installed_signing[0][-1], str(self.installed))
        self.assertEqual(ditto[0], ['/usr/bin/ditto', str(app), str(self.work / 'Old.app')])
        self.assertEqual(ditto[1], {'check': True, 'capture_output': True, 'timeout': 180})
        self.assertEqual(detach[0], ['/usr/bin/hdiutil', 'detach', str(self.work / 'mount')])
        self.assertEqual(detach[1], {'check': False, 'capture_output': True, 'timeout': 30})

    def test_prepare_mounts_checks_copies_and_unmounts(self):
        app = self.work / 'mount' / 'Update.app'
        tools = ToolsRun(teams={str(app): 'TEAM1', str(self.installed): 'TEAM1'},
                         mount_app=lambda: self.mount_app(self.work))
        prepared = self.prepare(tools)
        self.assertEqual(prepared, self.work / 'Old.app')
        self.assertEqual([args[0] for args, _ in tools.calls],
                         ['/usr/bin/hdiutil', '/usr/bin/codesign', '/usr/sbin/spctl', '/usr/bin/codesign',
                          '/usr/bin/codesign', '/usr/bin/ditto', '/usr/bin/hdiutil'])
        self.assert_update_steps(tools, app)

    def test_a_missing_or_duplicate_app_is_refused_after_unmounting(self):
        for index, build in enumerate((lambda work: None,
                                       lambda work: (self.mount_app(work), self.mount_app(work, name='Two.app')))):
            work = self.root / f'work-{index}'
            tools = ToolsRun(mount_app=lambda work=work, build=build: build(work))
            with self.subTest(index=index):
                with self.assertRaises(UpdateError) as caught:
                    self.prepare(tools, work)
                self.assertEqual(str(caught.exception), '磁盘映像里没有唯一的应用程序')
                self.assertEqual(tools.kinds()[-1], ('/usr/bin/hdiutil', 'detach'))

    def test_identity_or_version_mismatch_is_refused(self):
        for index, (identifier, version) in enumerate(((install.BUNDLE_ID, '0.4.1'),
                                                       ('com.example.other', '0.4.2'))):
            work = self.root / f'identity-{index}'
            tools = ToolsRun(mount_app=lambda work=work, identifier=identifier, version=version:
                             self.mount_app(work, identifier=identifier, version=version))
            with self.subTest(identifier=identifier, version=version):
                with self.assertRaises(UpdateError) as caught:
                    self.prepare(tools, work)
                self.assertEqual(str(caught.exception), '应用的标识或版本与更新清单不一致')
                self.assertEqual(tools.kinds()[-1], ('/usr/bin/hdiutil', 'detach'))

    def test_a_different_signing_team_is_refused(self):
        app = self.work / 'mount' / 'Update.app'
        tools = ToolsRun(teams={str(app): 'TEAM1', str(self.installed): 'TEAM2'},
                         mount_app=lambda: self.mount_app(self.work))
        with self.assertRaises(UpdateError) as caught:
            self.prepare(tools)
        self.assertEqual(str(caught.exception), '新旧应用的开发者签名不一致')
        self.assertEqual(tools.kinds()[-1], ('/usr/bin/hdiutil', 'detach'))

    def test_attach_failure_leaves_no_detach_call(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args[:2])
            if args[:2] == ['/usr/bin/hdiutil', 'attach']:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0)

        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare(run)
        self.assertEqual(calls, [['/usr/bin/hdiutil', 'attach']])

    @unittest.skipIf(os.name == 'nt', '需要目录符号链接')
    def test_a_symlinked_bundle_is_not_the_mounted_app(self):
        target = self.root / 'Elsewhere'
        target.mkdir()
        link = self.work / 'mount' / 'Linked.app'
        tools = ToolsRun(mount_app=lambda: link.symlink_to(target, target_is_directory=True))
        with self.assertRaises(UpdateError) as caught:
            self.prepare(tools)
        self.assertEqual(str(caught.exception), '磁盘映像里没有唯一的应用程序')


class MacAppTests(unittest.TestCase):
    """bundle 根只从 `…/X.app/Contents/MacOS/<程序>` 这一种形状认出来。"""

    def test_an_executable_inside_a_bundle_resolves_to_its_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp).resolve() / 'Applications' / 'App.app'
            exe = app / 'Contents' / 'MacOS' / 'program'
            self.assertEqual(install.mac_app(exe), app)

    def test_anything_else_is_refused_with_the_install_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in ('App.app/Contents/Other/program', 'App.app/Other/MacOS/program',
                             'App.bundle/Contents/MacOS/program'):
                with self.subTest(path=relative), self.assertRaises(UpdateError) as caught:
                    install.mac_app(root / relative)
                self.assertEqual(str(caught.exception), '请从已安装的 App 中更新')


class BundleInfoTests(unittest.TestCase):
    def test_reads_the_info_plist_inside_the_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'App.app'
            info_plist(app, identifier='com.example.app', version='9.9.9')
            self.assertEqual(install.bundle_info(app),
                             {'CFBundleIdentifier': 'com.example.app', 'CFBundleShortVersionString': '9.9.9'})


class SigningTeamTests(unittest.TestCase):
    def test_reads_the_team_from_codesign_diagnostics(self):
        calls = []

        def run(args, **kwargs):
            calls.append((args, kwargs))
            self.assertEqual(kwargs, {'capture_output': True, 'text': True, 'encoding': 'utf-8',
                                      'errors': 'replace', 'check': True})
            return subprocess.CompletedProcess(args, 0, stderr='Executable=x\nTeamIdentifier=AB12CD34\n')

        self.assertEqual(install.signing_team(Path('/Applications/Old.app'), run=run), 'AB12CD34')
        self.assertEqual(calls[0][0], ['/usr/bin/codesign', '-dv', '--verbose=4',
                                       str(Path('/Applications/Old.app'))])

    def test_a_missing_team_is_reported_as_an_unknown_developer(self):
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stderr='Executable=x\nno team here\n')

        with self.assertRaises(UpdateError) as caught:
            install.signing_team(Path('/Applications/Old.app'), run=run)
        self.assertEqual(str(caught.exception), '无法确认应用签名的开发者')


class WriteJsonTests(unittest.TestCase):
    def test_writes_utf8_json_and_replaces_the_target_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'state.json'
            path.write_text('old', encoding='utf-8')
            data = {'note': '中文', 'n': 1}
            install.write_json(path, data)
            self.assertEqual(path.read_bytes(), json.dumps(data, ensure_ascii=False).encode('utf-8'))
            self.assertEqual(sorted(item.name for item in root.iterdir()), ['state.json'])


class StaleSweepTests(unittest.TestCase):
    """只清一天前的 `install-*` 目录：另一个窗口刚建的那份与普通文件都不能碰。"""

    NOW = 1_700_000_000

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def aged(self, name, seconds, *, directory=True):
        path = self.root / name
        path.mkdir() if directory else path.write_text('x', encoding='utf-8')
        stamp = self.NOW - seconds
        os.utime(path, (stamp, stamp))
        return path

    def sweep(self):
        with patch.object(install.time, 'time', return_value=self.NOW):
            install.sweep_stale(self.root)

    def test_sweeps_only_directories_older_than_a_day(self):
        old = self.aged('install-old', install.STALE_SECONDS + 1)
        fresh = self.aged('install-fresh', 0)
        self.sweep()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists(), '另一个窗口刚建的准备目录不能清')

    def test_the_cutoff_is_exclusive(self):
        boundary = self.aged('install-boundary', install.STALE_SECONDS)
        self.sweep()
        self.assertTrue(boundary.exists(), '恰好一天前的不算「更早」')

    def test_a_plain_file_and_a_lookalike_are_left_alone(self):
        loose = self.aged('install-file', install.STALE_SECONDS + 1, directory=False)
        lookalike = self.aged('update-old', install.STALE_SECONDS + 1)
        self.sweep()
        self.assertTrue(loose.exists())
        self.assertTrue(lookalike.exists())


class HelperErrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def test_the_helper_reason_is_read(self):
        (self.work / install.ERROR_FILE).write_text(
            json.dumps({'error': '另一个窗口正在安装更新，请等它完成后重试'}, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(install._helper_error(self.work), '另一个窗口正在安装更新，请等它完成后重试')

    def test_a_missing_or_malformed_reason_is_empty(self):
        self.assertEqual(install._helper_error(self.work), '')
        for text in ('{}', '{oops', '[1]'):
            (self.work / install.ERROR_FILE).write_text(text, encoding='utf-8')
            with self.subTest(text=text):
                self.assertEqual(install._helper_error(self.work), '')


class StubHelper:
    def __init__(self, *, running=True, hang=False):
        self.running = running
        self.hang = hang
        self.terminated = 0
        self.killed = 0
        self.waits = []

    def poll(self):
        return None if self.running else 1

    def terminate(self):
        self.terminated += 1

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.hang and len(self.waits) == 1:
            raise subprocess.TimeoutExpired('helper', timeout or 0)
        return 0

    def kill(self):
        self.killed += 1


class InstallerOptionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_defaults_come_from_the_running_process(self):
        adapter = install.DesktopInstaller(self.root)
        self.assertEqual(adapter.root, self.root)
        self.assertEqual(adapter.system, sys.platform)
        self.assertEqual(adapter.executable, Path(sys.executable).resolve())
        self.assertIs(adapter.frozen, False)
        self.assertIsNone(adapter.helper)
        self.assertIsNone(adapter.close())
        self.assertIs(adapter.popen, subprocess.Popen)

    def test_explicit_values_win(self):
        calls, popped = [], []
        def close():
            calls.append('closed')
        def popen(args, **kwargs):
            popped.append(args)
        executable = self.root / 'App' / 'program'
        adapter = install.DesktopInstaller(self.root, system='win32', executable=executable,
                                           frozen=True, close=close, popen=popen)
        self.assertEqual(adapter.system, 'win32')
        self.assertEqual(adapter.executable, executable.resolve())
        self.assertIs(adapter.frozen, True)
        self.assertIs(adapter.popen, popen)
        adapter.close()
        self.assertEqual(calls, ['closed'])

    def test_a_frozen_flag_from_the_interpreter_is_used(self):
        with patch.object(install.sys, 'frozen', True, create=True):
            adapter = install.DesktopInstaller(self.root)
        self.assertIs(adapter.frozen, True)

    def test_process_options_detach_the_child_from_three_streams(self):
        options = install.process_options()
        self.assertEqual(set(options), {'stdin', 'stdout', 'stderr', 'env'})
        for key in ('stdin', 'stdout', 'stderr'):
            self.assertIs(options[key], subprocess.DEVNULL)
        self.assertEqual(options['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertEqual(options['env']['PATH'], os.environ['PATH'])


class AbortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adapter = install.DesktopInstaller(Path(self.tmp.name))

    def test_a_running_helper_is_terminated_with_a_bounded_wait(self):
        helper = StubHelper()
        self.adapter.helper = helper
        self.adapter.abort()
        self.assertEqual(helper.terminated, 1)
        self.assertEqual(helper.waits, [10])
        self.assertEqual(helper.killed, 0)

    def test_a_helper_that_ignores_terminate_is_killed(self):
        helper = StubHelper(hang=True)
        self.adapter.helper = helper
        self.adapter.abort()
        self.assertEqual(helper.waits, [10])
        self.assertEqual(helper.killed, 1)

    def test_no_helper_or_an_exited_helper_is_left_alone(self):
        self.adapter.abort()
        helper = StubHelper(running=False)
        self.adapter.helper = helper
        self.adapter.abort()
        self.assertEqual(helper.terminated, 0)


class KernelFunction:
    def __init__(self, result, code=None):
        self.result = result
        self.code = code
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        if self.code is not None:
            args[-1]._obj.value = self.code
        return self.result


class FakeKernel:
    """Win32 kernel32 的替身：OpenProcess / GetExitCodeProcess / CloseHandle 各自可断言。"""

    def __init__(self, *, handle=7, exit_ok=True, code=259):
        self.OpenProcess = KernelFunction(handle)
        self.GetExitCodeProcess = KernelFunction(exit_ok, code=code)
        self.CloseHandle = KernelFunction(None)


class FakeWindll:
    def __init__(self, kernel):
        self.kernel32 = kernel


class ParentAliveTests(unittest.TestCase):
    def test_windows_alive_checks_the_handle_and_still_active_code(self):
        import ctypes
        from ctypes import wintypes
        kernel = FakeKernel(handle=7, code=259)
        self.assertIs(install._alive_windows(4242, kernel), True)
        self.assertEqual(kernel.OpenProcess.calls, [(0x1000, False, 4242)])
        self.assertEqual(kernel.OpenProcess.argtypes, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD])
        self.assertIs(kernel.OpenProcess.restype, wintypes.HANDLE)
        self.assertEqual(kernel.GetExitCodeProcess.argtypes,
                         [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)])
        self.assertEqual(kernel.CloseHandle.argtypes, [wintypes.HANDLE])
        self.assertEqual(kernel.GetExitCodeProcess.calls[0][0], 7)
        self.assertEqual(kernel.CloseHandle.calls, [(7,)])

    def test_windows_dead_processes_report_false(self):
        self.assertIs(install._alive_windows(1, FakeKernel(handle=0)), False)
        self.assertIs(install._alive_windows(1, FakeKernel(code=0)), False)
        self.assertIs(install._alive_windows(1, FakeKernel(exit_ok=False, code=259)), False)

    def test_posix_liveness_uses_signal_zero(self):
        calls = []
        with patch.object(install.os, 'kill', lambda pid, signal: calls.append((pid, signal))):
            self.assertIs(install._alive_posix(4242), True)
        self.assertEqual(calls, [(4242, 0)])

    @unittest.skipIf(os.name == 'nt', 'Windows 上 os.kill(pid, 0) 不是空操作')
    def test_posix_own_pid_is_alive_and_a_dead_pid_is_not(self):
        self.assertIs(install.parent_alive(os.getpid()), True)
        self.assertIs(install.parent_alive(4_000_000), False)

    @unittest.skipIf(os.name == 'nt', 'Windows 上 os.kill(pid, 0) 不是空操作')
    def test_parent_alive_dispatches_to_posix(self):
        with patch.object(install.os, 'kill', lambda pid, signal: None):
            self.assertIs(install.parent_alive(4242), True)

    def test_parent_alive_dispatches_to_windows_when_os_name_is_nt(self):
        import ctypes
        kernel = FakeKernel(handle=0)
        with patch.object(install.os, 'name', 'nt'), \
                patch.object(ctypes, 'windll', FakeWindll(kernel), create=True):
            self.assertIs(install.parent_alive(os.getpid()), False)
        self.assertEqual(kernel.OpenProcess.calls, [(0x1000, False, os.getpid())])


class CopyRemoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_file_is_copied_with_its_bytes(self):
        source = self.root / 'file.txt'
        source.write_text('payload', encoding='utf-8')
        destination = self.root / 'copy.txt'
        install.copy_item(source, destination)
        self.assertEqual(destination.read_text(encoding='utf-8'), 'payload')

    @unittest.skipIf(os.name == 'nt', '需要符号链接')
    def test_a_directory_is_copied_with_its_links_intact(self):
        source = self.root / 'tree'
        source.mkdir()
        (source / 'file').write_text('payload', encoding='utf-8')
        (source / 'link').symlink_to('file')
        destination = self.root / 'copy'
        install.copy_item(source, destination)
        self.assertEqual((destination / 'file').read_text(encoding='utf-8'), 'payload')
        self.assertTrue((destination / 'link').is_symlink())
        self.assertEqual(os.readlink(destination / 'link'), 'file')

    def test_a_directory_tree_is_removed(self):
        tree = self.root / 'tree' / 'nested'
        tree.mkdir(parents=True)
        (tree / 'file').write_text('x', encoding='utf-8')
        install.remove_item(self.root / 'tree')
        self.assertFalse((self.root / 'tree').exists())

    def test_a_missing_entry_is_removed_silently(self):
        install.remove_item(self.root / 'never-there')
        self.assertFalse((self.root / 'never-there').exists())

    @unittest.skipIf(os.name == 'nt', '需要符号链接')
    def test_a_symlink_is_unlinked_without_touching_its_target(self):
        target = self.root / 'target'
        target.mkdir()
        link = self.root / 'link'
        link.symlink_to(target, target_is_directory=True)
        install.remove_item(link)
        self.assertFalse(link.is_symlink())
        self.assertTrue(target.is_dir())
