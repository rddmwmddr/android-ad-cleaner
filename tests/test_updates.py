"""#888：真实字节下载与状态迁移，所有网络和安装由边界替身接管。"""
import copy
import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from gui import updates

PAYLOAD = b'official-package' * 100


def manifest(version='0.4.2'):
    rows = {}
    for target, suffix in updates.SUFFIXES.items():
        name = f'AndroidAdCleaner-{version}-{suffix}'
        rows[target] = dict(file=name, size=len(PAYLOAD), sha256=hashlib.sha256(PAYLOAD).hexdigest(),
                            sources={k: v + version + '/' + name for k, v in updates.SOURCES.items()})
    return dict(schema=1, version=version, artifacts=rows)


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = manifest()
        self.payload = PAYLOAD
        self.urls = []
        self.installer = Mock()
        self.installer.install.return_value = {'exit': False, 'message': '系统确认'}
        self.saved = []
        self.claim = Mock(return_value='')
        self.release = Mock()
        self.up = updates.Updates('0.4.1', self.tmp.name, self.installer, target='windows',
                                  opener=self.open, save_source=self.saved.append,
                                  claim=self.claim, release=self.release)

    def open(self, req, timeout):
        self.urls.append(req.full_url)
        return io.BytesIO(json.dumps(self.data).encode() if req.full_url == updates.MANIFEST_URL else self.payload)

    def finish(self):
        self.up.worker.join(2)
        self.assertFalse(self.up.worker.is_alive(), '替身没有阻塞网络，更新线程应已结束')
        return self.up.snapshot()

    def available(self):
        self.up.check()
        self.assertEqual(self.finish()['state'], 'available')

    def ready(self):
        self.available()
        self.up.download()
        self.assertEqual(self.finish()['state'], 'ready')

    def test_gitee_default_and_persisted_github_choice(self):
        self.ready()
        self.assertEqual(self.up.path.read_bytes(), PAYLOAD)
        self.assertTrue(self.urls[-1].startswith(updates.SOURCES['gitee']))
        self.up.download('github')
        self.finish()
        self.assertTrue(self.urls[-1].startswith(updates.SOURCES['github']))
        self.assertEqual(self.saved, ['gitee', 'github'])

    def test_same_or_older_release_never_offers_install(self):
        for version in ('0.4.1', '0.3.9'):
            self.data = {'version': version}  # 旧格式仍能判断当前版本
            self.up.check()
            state = self.finish()
            self.assertEqual(state['state'], 'current')
            self.assertFalse(state['can_download'])
            self.assertFalse(state['can_install'])

    def test_legacy_new_release_explains_manual_download(self):
        self.data = {'version': '0.4.2'}
        self.up.check()
        self.assertIn('官网下载', self.finish()['error'])

    def test_failed_check_invalidates_previous_offer(self):
        self.ready()
        self.data = {'version': 'bad'}
        self.up.check()
        state = self.finish()
        self.assertEqual(state['state'], 'error')
        self.assertFalse(state['can_install'])
        self.assertFalse(state['can_download'])

    def test_corrupt_truncated_and_oversize_downloads_cannot_install(self):
        self.available()
        for data in (b'x' * len(PAYLOAD), PAYLOAD[:-1], PAYLOAD + b'x'):
            self.payload = data
            self.up.download()
            state = self.finish()
            self.assertEqual(state['state'], 'error')
            self.assertFalse(state['can_install'])
            self.assertFalse(list(Path(self.tmp.name).glob('*.part')))
        self.installer.install.assert_not_called()

    def test_network_error_removes_partial_download(self):
        self.available()
        class Disconnected(io.BytesIO):
            def read(self, size=-1):
                if self.tell():
                    raise OSError('connection lost')
                return super().read(3)
        self.up.opener = lambda *args, **kwargs: Disconnected(PAYLOAD)
        self.up.download()
        self.assertIn('connection lost', self.finish()['error'])
        self.assertFalse(list(Path(self.tmp.name).glob('*.part')))

    def test_cancel_and_double_click_do_not_start_second_download(self):
        self.available()
        entered, proceed = threading.Event(), threading.Event()
        class Paused(io.BytesIO):
            def read(self, size=-1):
                entered.set()
                if not proceed.wait(2):
                    raise RuntimeError('test did not release download')
                return super().read(size)
        opener = Mock(return_value=Paused(PAYLOAD))
        self.up.opener = opener
        self.up.download()
        self.assertTrue(entered.wait(2))
        self.up.download('github')
        self.up.check()
        self.up.cancel()
        proceed.set()
        self.assertEqual(self.finish()['state'], 'available')
        opener.assert_called_once()
        self.assertFalse(list(Path(self.tmp.name).glob('*.part')))
        self.assertEqual(self.up.snapshot()['source'], 'gitee')

    def test_second_window_cannot_write_the_same_partial_download(self):
        """两个窗口会写同一个 .part：后完成的那份把已经校验通过的成品再写坏。"""
        self.available()
        with updates.file_lock(Path(self.tmp.name) / 'download.lock', '另一个窗口正在下载更新'):
            self.up.download()
            state = self.finish()
        self.assertIn('另一个窗口', state['error'])
        self.assertFalse(list(Path(self.tmp.name).glob('*.part')))
        self.assertFalse(list(Path(self.tmp.name).glob('*.zip')))

    def test_active_phone_job_blocks_install_and_can_retry(self):
        self.ready()
        self.claim.return_value = '请先完成正在运行的任务'
        self.up.install()
        self.assertIn('正在运行', self.finish()['error'])
        self.installer.install.assert_not_called()
        self.release.assert_not_called()
        self.claim.return_value = ''
        self.up.install()
        self.assertEqual(self.finish()['message'], '系统确认')
        self.installer.install.assert_called_once_with(self.up.path, '0.4.2')
        self.release.assert_called_once()

    def test_install_rechecks_download_before_native_adapter(self):
        self.ready()
        self.up.path.write_bytes(b'tampered')
        self.up.install()
        self.assertEqual(self.finish()['state'], 'error')
        self.installer.install.assert_not_called()
        self.release.assert_called_once()

    def test_desktop_handoff_closes_window_and_keeps_job_reserved(self):
        self.ready()
        self.installer.install.return_value = {'exit': True}
        self.up.install()
        self.assertEqual(self.finish()['state'], 'installing')
        self.installer.close.assert_called_once()
        self.release.assert_not_called()
        self.up.check()
        self.assertEqual(self.up.snapshot()['state'], 'installing')

    def test_close_failure_aborts_helper_and_releases_job(self):
        self.ready()
        self.installer.install.return_value = {'exit': True}
        self.installer.close.side_effect = OSError('window did not close')
        self.up.install()
        self.assertIn('window did not close', self.finish()['error'])
        self.installer.abort.assert_called_once()
        self.release.assert_called_once()

    def test_previous_failure_survives_startup_check(self):
        root = Path(self.tmp.name)
        (root / 'last-result.json').write_text('{"ok":false,"error":"已恢复旧版"}', encoding='utf-8')
        other = updates.Updates('0.4.1', root, self.installer, target='windows', opener=self.open)
        other.check()
        other.worker.join(2)
        self.assertEqual(other.snapshot()['previous_error'], '已恢复旧版')


class ManifestTests(unittest.TestCase):
    def test_all_platform_files_are_separate(self):
        self.assertEqual(set(manifest()['artifacts']), {'android-arm64', 'mac-arm64', 'mac-intel', 'windows'})
        for target in manifest()['artifacts']:
            self.assertEqual(updates.artifact(manifest(), target)['version'], '0.4.2')
        self.assertEqual(updates.platform_id('Darwin', 'arm64'), 'mac-arm64')
        self.assertEqual(updates.platform_id('Darwin', 'x86_64'), 'mac-intel')
        self.assertEqual(updates.platform_id('Windows', 'AMD64'), 'windows')
        self.assertEqual(updates.platform_id('Linux', 'x86_64'), '')

    def test_untrusted_urls_filename_size_hash_and_schema_rejected(self):
        for field, value in [('file', '../bad.exe'), ('size', True), ('size', updates.MAX_PACKAGE + 1),
                             ('sha256', 'a' * 63), ('sources', {'gitee': 'http://example.com/a'})]:
            data = copy.deepcopy(manifest())
            data['artifacts']['windows'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(updates.UpdateError):
                updates.artifact(data, 'windows')
        for value in ('0.4.2/bad', '1.2', None):
            with self.assertRaises(updates.UpdateError):
                updates.version_tuple(value)

    def test_https_redirect_cannot_downgrade(self):
        handler = updates.HttpsRedirect()
        req = updates.urllib.request.Request('https://gitee.com/a')
        with self.assertRaises(updates.UpdateError):
            handler.redirect_request(req, None, 302, '', {}, 'http://example.com/file')


class BridgeIntegrationTests(unittest.TestCase):
    def test_update_root_comes_from_client_data(self):
        """更新目录只由 ClientData 给出：各处自己拼一遍，漂移时健康回执永远写不出来。"""
        from gui import app
        with tempfile.TemporaryDirectory() as root:
            api = app.Api(root)
            self.assertEqual(api.updater.root, Path(api.data.updates))

    def test_api_blocks_install_during_real_dispatcher_job(self):
        from types import SimpleNamespace
        from gui import app
        # 用真实的 app.VERSION：「新版」要比它大，写死 0.4.2 的话发 0.4.2 那天就不算新版了
        major, minor, patch = map(int, app.VERSION.split('.'))
        newer = f'{major}.{minor}.{patch + 1}'
        with tempfile.TemporaryDirectory() as root:
            api = app.Api(root)
            api.updater.target = 'windows'
            api.updater.opener = lambda req, **kw: io.BytesIO(json.dumps(manifest(newer)).encode() if req.full_url == updates.MANIFEST_URL else PAYLOAD)
            installer = Mock()
            installer.install.return_value = {'exit': False}
            api.updater.installer = installer
            api.check_update(); api.updater.worker.join(2)
            api.download_update('github'); api.updater.worker.join(2)
            self.assertEqual(api.data.setting('update_source'), 'github')
            api.job = SimpleNamespace(running=True)
            api.install_update(); api.updater.worker.join(2)
            self.assertIn('安装更新', api.update_state()['error'])
            installer.install.assert_not_called()
            api.job.running = False
            api.dispatcher.side = '还原'
            api.install_update(); api.updater.worker.join(2)
            self.assertIn('还原', api.update_state()['error'])
            installer.install.assert_not_called()
            api.dispatcher.side = ''
            api.install_update(); api.updater.worker.join(2)
            installer.install.assert_called_once_with(api.updater.path, newer)
            self.assertEqual(api.dispatcher.side, '')

    def test_updater_helper_dispatch_does_not_open_window_or_run_cli(self):
        from gui import launch
        for executable in ('AndroidAdCleaner.exe', 'aac-cli.exe', '肉呆去广告'):
            self.assertEqual(launch.dispatch(['--apply-update', 'plan.json'], executable), 'update')
