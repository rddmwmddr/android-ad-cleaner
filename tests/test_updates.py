"""#888：真实字节下载与状态迁移，所有网络和安装由边界替身接管。"""
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gui import updates

PAYLOAD = b'official-package' * 100


def manifest(version='0.4.2', payload=PAYLOAD):
    rows = {}
    for target, suffix in updates.SUFFIXES.items():
        name = f'AndroidAdCleaner-{version}-{suffix}'
        rows[target] = dict(file=name, size=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                            sources={k: v + version + '/' + name for k, v in updates.SOURCES.items()})
    return dict(schema=1, version=version, artifacts=rows)


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = manifest()
        self.payload = PAYLOAD
        self.urls = []
        self.requests = []
        self.timeouts = []
        self.installer = Mock()
        self.installer.install.return_value = {'exit': False, 'message': '系统确认'}
        self.saved = []
        self.claim = Mock(return_value='')
        self.release = Mock()
        guard = patch.object(updates, 'open_https', side_effect=AssertionError('测试必须注入 opener，不能走真网络'))
        guard.start()
        self.addCleanup(guard.stop)
        self.up = updates.Updates('0.4.1', self.tmp.name, self.installer, target='windows',
                                  opener=self.open, save_source=self.saved.append,
                                  claim=self.claim, release=self.release)

    def open(self, req, timeout):
        self.urls.append(req.full_url)
        self.requests.append(req)
        self.timeouts.append(timeout)
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


# ---------- 状态、下载进度与安装迁移（变异判据补的断言） ----------


class UpdateStateTests(unittest.TestCase):
    """快照、检查与下载的可观察结局：字段、状态迁移、请求与进度。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = manifest()
        self.payload = PAYLOAD
        self.installer = Mock()
        self.installer.install.return_value = {'exit': False, 'message': '系统确认'}
        self.opened = []
        guard = patch.object(updates, 'open_https', side_effect=AssertionError('测试必须注入 opener，不能走真网络'))
        guard.start()
        self.addCleanup(guard.stop)
        self.up = updates.Updates('0.4.1', self.root, self.installer, target='windows', opener=self.open)

    def open(self, req, timeout):
        self.opened.append((req, timeout))
        if req.full_url == updates.MANIFEST_URL:
            return io.BytesIO(json.dumps(self.data).encode())
        return io.BytesIO(self.payload)

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

    def test_initial_snapshot_and_default_wiring(self):
        self.assertEqual(self.up.snapshot(), {
            'state': 'idle', 'current': '0.4.1', 'version': '', 'source': 'gitee',
            'received': 0, 'size': 0, 'message': '', 'error': '',
            'busy': False, 'can_download': False, 'can_install': False, 'can_cancel': False,
            'notes_url': '',
        })
        self.assertEqual(self.up.opener, self.open)
        default = updates.Updates('0.4.1', self.root, self.installer)
        self.assertEqual(default.target, updates.platform_id())
        self.assertIsNone(default.worker)
        self.assertIsNone(default.offer)
        self.assertIsNone(default.path)
        self.assertEqual(default.claim(), '')
        self.assertIsNone(default.release())
        self.assertIsNone(default.save_source('github'))
        explicit = updates.Updates('0.4.1', self.root, self.installer, target='windows')
        self.assertEqual(explicit.target, 'windows')

    def test_source_is_normalised_to_a_known_channel(self):
        for given, expected in [('github', 'github'), ('gitee', 'gitee'), ('ftp', 'gitee'), (None, 'gitee')]:
            with self.subTest(source=given):
                up = updates.Updates('0.4.1', self.root, self.installer, source=given)
                self.assertEqual(up.snapshot()['source'], expected)

    def test_check_requests_the_manifest_once_with_bounded_read(self):
        sizes = []

        class Bounded(io.BytesIO):
            def read(self, size=-1):
                sizes.append(size)
                return super().read(size)

        body = json.dumps(self.data).encode()
        self.up.opener = lambda req, timeout: Bounded(body)
        self.available()
        self.assertEqual(sizes, [updates.MANIFEST_READ], '清单只读一次且必须有界，别把超大响应整个读进内存')

    def test_check_sends_the_client_user_agent_and_timeout(self):
        self.available()
        request, timeout = self.opened[0]
        self.assertEqual(request.full_url, updates.MANIFEST_URL)
        self.assertEqual(request.get_header('User-agent'), 'AndroidAdCleaner/0.4.1')
        self.assertEqual(timeout, 15)

    def test_manifest_size_boundary_is_inclusive(self):
        raw = json.dumps(self.data).encode()
        for body, expected in [(raw + b' ' * (updates.MAX_MANIFEST - len(raw)), 'available'),
                               (raw + b' ' * (updates.MANIFEST_READ - len(raw)), 'error')]:
            with self.subTest(length=len(body)):
                self.up.opener = lambda req, timeout, body=body: io.BytesIO(body)
                self.up.check()
                self.assertEqual(self.finish()['state'], expected)
        self.up.check()
        self.assertEqual(self.finish()['error'], '更新清单过大')

    def test_check_busy_state_and_single_worker(self):
        entered, proceed = threading.Event(), threading.Event()

        class Paused(io.BytesIO):
            def read(self, size=-1):
                entered.set()
                if not proceed.wait(2):
                    raise RuntimeError('test did not release the manifest read')
                return super().read(size)

        self.up.opener = lambda req, timeout: Paused(json.dumps(self.data).encode())
        self.up.check()
        self.assertTrue(entered.wait(2))
        snapshot = self.up.snapshot()
        self.assertEqual(snapshot['state'], 'checking')
        self.assertTrue(snapshot['busy'])
        self.assertFalse(snapshot['can_download'])
        self.assertFalse(snapshot['can_cancel'])
        self.assertIs(self.up.worker.daemon, True, '更新线程要随窗口退出，不能把进程挂住')
        worker = self.up.worker
        self.assertEqual(self.up.check()['state'], 'checking')
        self.assertIs(self.up.worker, worker, '已有更新操作在跑时不能再起一个线程')
        proceed.set()
        self.assertEqual(self.finish()['state'], 'available')

    def test_check_rejects_oversize_and_non_object_manifests(self):
        self.available()
        for body, message in [(b'x' * updates.MANIFEST_READ, '更新清单过大'),
                              (b'[]', '更新清单无效'),
                              (b'{}', '更新清单里的版本号无效'),
                              (b'{not json', None)]:
            with self.subTest(body=body[:20]):
                self.up.opener = lambda req, timeout, body=body: io.BytesIO(body)
                self.up._set(received=123)
                self.up.check()
                snapshot = self.finish()
                self.assertEqual(snapshot['state'], 'error')
                if message is not None:
                    self.assertEqual(snapshot['error'], message)
                else:
                    self.assertNotEqual(snapshot['error'], '')
                self.assertEqual(snapshot['version'], '', '失败的检查要清掉上一次的版本与进度')
                self.assertEqual(snapshot['size'], 0)
                self.assertEqual(snapshot['received'], 0)
                self.assertIsNone(self.up.offer)
                self.assertIsNone(self.up.path)

    def test_check_on_current_release_clears_the_offer(self):
        self.available()
        self.data = manifest(version='0.4.1')
        self.up.opener = self.open
        self.up.check()
        snapshot = self.finish()
        self.assertEqual(snapshot['state'], 'current')
        self.assertEqual(snapshot['message'], '已是最新版本')
        self.assertEqual(snapshot['version'], '')
        self.assertEqual(snapshot['size'], 0)
        self.assertEqual(snapshot['received'], 0)
        self.assertFalse(snapshot['can_download'])
        self.assertFalse(snapshot['can_install'])
        self.assertIsNone(self.up.offer)
        self.assertIsNone(self.up.path)

    def test_available_snapshot_reports_the_release_details(self):
        self.available()
        request = self.up.snapshot()
        self.assertEqual(request['state'], 'available')
        self.assertEqual(request['version'], '0.4.2')
        self.assertEqual(request['size'], len(PAYLOAD))
        self.assertEqual(request['received'], 0)
        self.assertEqual(request['message'], '')
        self.assertEqual(request['error'], '')
        self.assertTrue(request['can_download'])
        self.assertFalse(request['can_install'])
        self.assertFalse(request['busy'])
        self.assertEqual(request['notes_url'],
                         'https://github.com/rddmwmddr/android-ad-cleaner/releases/tag/v0.4.2')

    def test_start_clears_a_previous_error_and_message(self):
        self.up.opener = lambda req, timeout: io.BytesIO(b'bad')
        self.up.check()
        self.assertNotEqual(self.finish()['error'], '')
        self.up._set(message='已取消下载')
        self.up.opener = self.open
        self.up.check()
        snapshot = self.finish()
        self.assertEqual(snapshot['error'], '')
        self.assertEqual(snapshot['message'], '')

    def test_work_reports_a_fallback_for_an_empty_error(self):
        self.up.opener = lambda req, timeout: (_ for _ in ()).throw(RuntimeError())
        self.up.check()
        self.assertEqual(self.finish()['error'], '更新没有完成，请重试')
        self.up.opener = lambda req, timeout: (_ for _ in ()).throw(RuntimeError('boom'))
        self.up.check()
        self.assertEqual(self.finish()['error'], 'boom')

    def test_download_requires_a_checked_offer_and_a_known_channel(self):
        self.assertEqual(self.up.download('gitee'), {'error': '请先检查更新'})
        self.assertIsNone(self.up.worker)
        self.available()
        worker = self.up.worker
        self.assertEqual(self.up.download('ftp'), {'error': '请选择 Gitee 或 GitHub 下载渠道'})
        self.assertIs(self.up.worker, worker, '无效渠道不能起下载线程')

    def test_download_streams_the_body_in_chunks_and_reports_ready(self):
        payload = b'z' * (updates.CHUNK * 2 + 7)
        self.data = manifest(payload=payload)
        reads, progress, requests, timeouts = [], [], [], []

        class Stream(io.BytesIO):
            def read(self, size=-1):
                reads.append(size)
                progress.append(self.owner.snapshot()['received'])
                return super().read(size)

        stream = Stream(payload)
        stream.owner = self.up

        def opener(request, timeout):
            requests.append(request)
            timeouts.append(timeout)
            return io.BytesIO(json.dumps(self.data).encode()) \
                if request.full_url == updates.MANIFEST_URL else stream

        self.up.opener = opener
        self.available()
        self.up.download()
        snapshot = self.finish()
        self.assertEqual(reads, [updates.CHUNK] * 4, '一次性 slurp 会让接收进度没有中间值')
        self.assertEqual(progress, [0, updates.CHUNK, updates.CHUNK * 2, len(payload)])
        self.assertEqual(snapshot['state'], 'ready')
        self.assertEqual(snapshot['received'], len(payload))
        self.assertEqual(snapshot['message'], '下载完成，校验通过')
        self.assertTrue(snapshot['can_install'])
        self.assertEqual(timeouts, [15, 30])
        self.assertEqual(requests[-1].full_url,
                         'https://gitee.com/rddmw/android-ad-cleaner/releases/download/v0.4.2/'
                         'AndroidAdCleaner-0.4.2-windows-portable.zip')
        self.assertEqual(requests[-1].get_header('User-agent'), 'AndroidAdCleaner/0.4.1')
        self.assertEqual(self.up.path.read_bytes(), payload)

    def test_download_cancel_reports_cancelling_then_resets_progress(self):
        entered, proceed = threading.Event(), threading.Event()
        half = len(PAYLOAD) // 2

        class Paused(io.BytesIO):
            def __init__(self, body):
                super().__init__(body)
                self.first = True

            def read(self, size=-1):
                if self.first:
                    self.first = False
                    return super().read(half)
                entered.set()
                if not proceed.wait(2):
                    raise RuntimeError('test did not release the download')
                return super().read(size)

        paused = Paused(PAYLOAD)
        self.up.opener = lambda req, timeout: io.BytesIO(json.dumps(self.data).encode()) \
            if req.full_url == updates.MANIFEST_URL else paused
        self.available()
        self.up.download()
        self.assertTrue(entered.wait(2))
        running = self.up.snapshot()
        self.assertEqual(running['state'], 'downloading')
        self.assertTrue(running['busy'])
        self.assertTrue(running['can_cancel'])
        self.assertFalse(running['can_download'])
        self.assertEqual(running['received'], half)
        cancelling = self.up.cancel()
        self.assertEqual(cancelling['state'], 'cancelling')
        self.assertTrue(cancelling['busy'])
        self.assertFalse(cancelling['can_cancel'])
        proceed.set()
        snapshot = self.finish()
        self.assertEqual(snapshot['state'], 'available')
        self.assertEqual(snapshot['received'], 0)
        self.assertEqual(snapshot['message'], '已取消下载')
        self.assertTrue(snapshot['can_download'])
        self.assertIsNone(self.up.path)
        self.assertEqual([p.name for p in self.root.iterdir()], ['download.lock'])

    @unittest.skipIf(os.name == 'nt', '创建软链接需要额外权限')
    def test_download_rejects_symlinked_partial_or_destination(self):
        self.available()
        name = self.up.offer['file']
        target = self.root / 'elsewhere.bin'
        target.write_bytes(PAYLOAD)
        for link in (self.root / name, self.root / (name + '.part')):
            with self.subTest(link=link.name):
                link.symlink_to(target)
                self.up.download()
                snapshot = self.finish()
                self.assertEqual(snapshot['error'], '更新目录里有异常链接，请清理更新缓存后重试')
                link.unlink()
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['download.lock', 'elsewhere.bin'])

    def test_download_error_messages_are_exact(self):
        self.available()
        for payload, message in [(PAYLOAD + b'x', '下载大小与发布清单不一致'),
                                 (PAYLOAD[:-1], '下载不完整或校验失败，请重试或切换渠道'),
                                 (b'y' * len(PAYLOAD), '下载不完整或校验失败，请重试或切换渠道')]:
            with self.subTest(message=message):
                self.payload = payload
                self.up.download()
                snapshot = self.finish()
                self.assertEqual(snapshot['state'], 'error')
                self.assertEqual(snapshot['error'], message)
                self.assertIsNone(self.up.path)
                self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['download.lock'])

    def test_download_creates_the_update_root_recursively(self):
        self.up = updates.Updates('0.4.1', self.root / 'nested' / 'updates', self.installer,
                                  target='windows', opener=self.open)
        self.ready()
        self.assertEqual(self.up.path.parent, self.root / 'nested' / 'updates')

    def test_download_lock_contention_names_the_other_window(self):
        self.available()
        with updates.file_lock(self.root / 'download.lock', '另一个窗口正在下载更新，等它完成后再试'):
            self.up.download()
            self.assertEqual(self.finish()['error'], '另一个窗口正在下载更新，等它完成后再试')

    def test_install_requires_both_an_offer_and_a_downloaded_file(self):
        self.assertEqual(self.up.install(), {'error': '请先下载更新'})
        self.assertIsNone(self.up.worker)
        self.available()
        self.assertEqual(self.up.install(), {'error': '请先下载更新'})
        self.assertFalse(self.up.worker.is_alive())

    def test_install_reports_ready_and_the_adapter_message(self):
        self.ready()
        self.up.install()
        snapshot = self.finish()
        self.assertEqual(snapshot['state'], 'ready')
        self.assertEqual(snapshot['message'], '系统确认')
        self.assertTrue(snapshot['can_install'])
        self.installer.install.return_value = {'exit': False}
        self.up.install()
        snapshot = self.finish()
        self.assertEqual(snapshot['state'], 'ready')
        self.assertEqual(snapshot['message'], '')

    def test_install_is_busy_and_blocks_a_second_operation(self):
        self.ready()
        entered, proceed = threading.Event(), threading.Event()

        def blocking_install(path, version):
            entered.set()
            if not proceed.wait(2):
                raise RuntimeError('test did not release the installer')
            return {'exit': False}

        self.installer.install.side_effect = blocking_install
        self.up.install()
        self.assertTrue(entered.wait(2))
        snapshot = self.up.snapshot()
        self.assertEqual(snapshot['state'], 'installing')
        self.assertTrue(snapshot['busy'])
        self.assertFalse(snapshot['can_install'])
        self.assertFalse(snapshot['can_download'])
        worker = self.up.worker
        self.assertEqual(self.up.check()['state'], 'installing')
        self.assertIs(self.up.worker, worker)
        proceed.set()
        self.assertEqual(self.finish()['state'], 'ready')

    def test_install_verify_failure_clears_the_downloaded_path(self):
        self.ready()
        self.up.path.write_bytes(b'tampered')
        self.up.install()
        snapshot = self.finish()
        self.assertEqual(snapshot['state'], 'error')
        self.assertIsNone(self.up.path)
        self.assertFalse(snapshot['can_install'])


class PreviousReceiptTests(unittest.TestCase):
    def build(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / 'last-result.json').write_text(text, encoding='utf-8')
        return updates.Updates('0.4.1', tmp.name, Mock(), target='windows').snapshot()

    def test_failed_receipts_surface_their_reason(self):
        self.assertEqual(self.build('{"ok": false}')['previous_error'], '上次更新没有完成')
        self.assertEqual(self.build('{"ok": false, "error": "已恢复旧版"}')['previous_error'], '已恢复旧版')

    def test_other_receipts_do_not_raise_previous_error(self):
        for text in ('{"ok": true}', '[]', 'not json', '{}'):
            with self.subTest(text=text):
                self.assertNotIn('previous_error', self.build(text))


class ManifestValueTests(unittest.TestCase):
    def valid(self, version='0.4.2', size=1):
        name = f'AndroidAdCleaner-{version.removeprefix("v")}-windows-portable.zip'
        row = dict(file=name, size=size, sha256='a' * 64,
                   sources={k: v + version.removeprefix('v') + '/' + name for k, v in updates.SOURCES.items()})
        return dict(schema=1, version=version, artifacts={'windows': row})

    def test_version_tuple_accepts_the_v_prefix_and_rejects_the_rest(self):
        self.assertEqual(updates.version_tuple('v1.2.3'), (1, 2, 3))
        self.assertEqual(updates.version_tuple('1.2.3'), (1, 2, 3))
        for value in ('1.2', '1.2.3.4', 'v1.2.x', '', None):
            with self.subTest(value=value), self.assertRaises(updates.UpdateError) as caught:
                updates.version_tuple(value)
            self.assertEqual(str(caught.exception), '更新清单里的版本号无效')

    def test_platform_matrix_covers_every_machine_spelling(self):
        for machine in ('amd64', 'x86_64', 'arm64', 'aarch64', 'AMD64'):
            self.assertEqual(updates.platform_id('Windows', machine), 'windows')
        self.assertEqual(updates.platform_id('Darwin', 'arm64'), 'mac-arm64')
        self.assertEqual(updates.platform_id('Darwin', 'aarch64'), 'mac-arm64')
        self.assertEqual(updates.platform_id('Darwin', 'x86_64'), 'mac-intel')
        self.assertEqual(updates.platform_id('Darwin', 'mips'), '')
        self.assertEqual(updates.platform_id('Linux', 'x86_64'), '')
        self.assertEqual(updates.platform_id('Windows', 'mips'), '')

    def test_artifact_accepts_the_v_prefix_and_the_size_boundaries(self):
        for version in ('0.4.2', 'v0.4.2'):
            with self.subTest(version=version):
                self.assertEqual(updates.artifact(self.valid(version), 'windows')['version'], '0.4.2')
        self.assertEqual(updates.artifact(self.valid(size=updates.MAX_PACKAGE), 'windows')['size'],
                         updates.MAX_PACKAGE)
        self.assertEqual(updates.artifact(self.valid(), 'windows')['file'],
                         'AndroidAdCleaner-0.4.2-windows-portable.zip')

    def test_artifact_rejections_carry_the_exact_message(self):
        def wrong(mutate):
            data = self.valid()
            mutate(data)
            return data

        cases = [
            ('x', '这个版本尚未提供应用内更新，请从官网下载'),
            (wrong(lambda d: d.update(schema=2)), '这个版本尚未提供应用内更新，请从官网下载'),
            (wrong(lambda d: d.pop('version')), '更新清单里的版本号无效'),
            (wrong(lambda d: d.update(version='bad')), '更新清单里的版本号无效'),
        ]
        for data, message in cases:
            with self.subTest(message=message), self.assertRaises(updates.UpdateError) as caught:
                updates.artifact(data, 'windows')
            self.assertEqual(str(caught.exception), message)
        self.assertRaises(updates.UpdateError, updates.artifact, self.valid(), 'linux')
        for mutate, message in [
            (lambda d: d.update(artifacts=[]), '这个版本还没有本平台的更新包'),
            (lambda d: d.pop('artifacts'), '这个版本还没有本平台的更新包'),
            (lambda d: d['artifacts'].update(windows='row'), '这个版本还没有本平台的更新包'),
            (lambda d: d['artifacts']['windows'].update(file='../bad.exe'), '更新包的名称与版本、平台不一致'),
            (lambda d: d['artifacts']['windows'].update(size=0), '更新包大小无效'),
            (lambda d: d['artifacts']['windows'].update(size=True), '更新包大小无效'),
            (lambda d: d['artifacts']['windows'].update(size=updates.MAX_PACKAGE + 1), '更新包大小无效'),
            (lambda d: d['artifacts']['windows'].update(size='1'), '更新包大小无效'),
            (lambda d: d['artifacts']['windows'].pop('sha256'), '更新包缺少有效的 SHA256 校验值'),
            (lambda d: d['artifacts']['windows'].update(sha256='a' * 63), '更新包缺少有效的 SHA256 校验值'),
            (lambda d: d['artifacts']['windows'].update(sources={'gitee': 'http://example.com/a'}),
             '更新包地址不是本产品的官方发布地址'),
        ]:
            with self.subTest(message=message), self.assertRaises(updates.UpdateError) as caught:
                updates.artifact(wrong(mutate), 'windows')
            self.assertEqual(str(caught.exception), message)
        with self.assertRaises(updates.UpdateError) as caught:
            updates.artifact(self.valid(), 'linux')
        self.assertEqual(str(caught.exception), '当前平台暂不支持应用内安装')

    def test_verify_file_checks_links_size_and_digest(self):
        payload = b'a' * 10
        row = dict(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / 'good.bin'
            good.write_bytes(payload)
            self.assertIsNone(updates.verify_file(good, row))
            wrong = root / 'wrong.bin'
            wrong.write_bytes(b'b' * 10)
            with self.assertRaises(updates.UpdateError) as caught:
                updates.verify_file(wrong, row)
            self.assertEqual(str(caught.exception), '安装包校验失败，请重新下载')
            short = root / 'short.bin'
            short.write_bytes(b'a')
            for path in (root, short):
                with self.assertRaises(updates.UpdateError) as caught:
                    updates.verify_file(path, row)
                self.assertEqual(str(caught.exception), '安装包不完整，请重新下载')
            if os.name != 'nt':
                link = root / 'link.bin'
                link.symlink_to(good)
                with self.assertRaises(updates.UpdateError) as caught:
                    updates.verify_file(link, row)
                self.assertEqual(str(caught.exception), '安装包不完整，请重新下载')


class TransportTests(unittest.TestCase):
    def test_open_https_rejects_plain_http_with_the_exact_message(self):
        request = updates.urllib.request.Request('http://example.com/manifest.json')
        no_network = patch.object(updates.urllib.request, 'build_opener',
                                  side_effect=AssertionError('http 地址不能走到 opener'))
        with no_network, self.assertRaises(updates.UpdateError) as caught:
            updates.open_https(request)
        self.assertEqual(str(caught.exception), '更新地址必须使用 HTTPS')

    def test_open_https_builds_the_redirect_guard_and_forwards_the_timeout(self):
        seen = {}

        class Opener:
            def open(self, request, timeout=None):
                seen['request'], seen['timeout'] = request, timeout
                return 'opened'

        def build(*handlers):
            if len(handlers) != 1 or not isinstance(handlers[0], updates.HttpsRedirect):
                raise AssertionError('必须在 opener 上装 HTTPS 重定向守卫')
            return Opener()

        request = updates.urllib.request.Request('https://example.com/manifest.json')
        with patch.object(updates.urllib.request, 'build_opener', side_effect=build):
            self.assertEqual(updates.open_https(request), 'opened')
            self.assertIs(seen['request'], request)
            self.assertEqual(seen['timeout'], 30)
            updates.open_https(request, timeout=5)
            self.assertEqual(seen['timeout'], 5)

    def test_redirect_rejects_downgrades_and_passes_https_through(self):
        handler = updates.HttpsRedirect()
        request = updates.urllib.request.Request('https://gitee.com/a')
        with self.assertRaises(updates.UpdateError) as caught:
            handler.redirect_request(request, None, 302, '', {}, 'http://example.com/file')
        self.assertEqual(str(caught.exception), '更新下载被重定向到不安全的地址')
        result = handler.redirect_request(request, None, 302, '', {'X-Test': '1'}, 'https://gitee.com/b')
        self.assertEqual(result.full_url, 'https://gitee.com/b')
        self.assertEqual(result.get_method(), 'GET')
        # 只有 301/302/303 放行 POST；307 会被基类拒绝，拒绝时 msg、响应头与 fp 都要原样带进 HTTPError
        post = updates.urllib.request.Request('https://gitee.com/a', method='POST')
        fp, hdrs = io.BytesIO(b'body'), {'X-Test': '1'}
        with self.assertRaises(updates.urllib.error.HTTPError) as rejected:
            handler.redirect_request(post, fp, 307, 'temporary redirect', hdrs, 'https://gitee.com/b')
        self.assertEqual(rejected.exception.msg, 'temporary redirect')
        self.assertIs(rejected.exception.hdrs, hdrs)
        self.assertIs(rejected.exception.fp, fp)


class WindowsLockTests(unittest.TestCase):
    """Windows 分支用假 msvcrt 跑：锁的是偏移 0 起的 1 个字节，拿不到就报占用。"""

    class FakeMsvcrt:
        LK_UNLCK, LK_LOCK, LK_NBLCK = 0, 1, 2

        def __init__(self):
            self.calls = []
            self.busy = set()
            self.held = set()

        def locking(self, fd, mode, nbytes):
            if not isinstance(fd, int) or isinstance(fd, bool) or not isinstance(mode, int) \
                    or not isinstance(nbytes, int) or nbytes <= 0:
                raise TypeError('locking() argument type or value invalid')
            if mode not in (self.LK_UNLCK, self.LK_LOCK, self.LK_NBLCK):
                raise TypeError('mode must be one of LK_LOCK, LK_NBLCK or LK_UNLCK')
            start = os.lseek(fd, 0, os.SEEK_CUR)
            self.calls.append((mode, start, nbytes))
            if mode == self.LK_UNLCK:
                self.held.discard((start, nbytes))
                return
            end = start + nbytes
            if any(start < other_end and other_start < end for other_start, other_end in self.busy):
                raise OSError('locked by another process')
            self.held.add((start, end))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stream = (Path(self.tmp.name) / 'download.lock').open('a+b')
        self.addCleanup(self.stream.close)
        self.stream.write(b'0')
        self.stream.flush()

    def test_lock_and_unlock_use_one_byte_at_offset_zero(self):
        fake = self.FakeMsvcrt()
        with patch.object(updates.os, 'name', 'nt'), patch.dict(sys.modules, {'msvcrt': fake}):
            self.stream.seek(0)
            self.assertTrue(updates._try_lock(self.stream))
            self.assertEqual(fake.calls, [(fake.LK_NBLCK, 0, 1)])
            updates._unlock(self.stream)
            self.assertEqual(fake.calls[-1], (fake.LK_UNLCK, 0, 1))

    def test_busy_bytes_mean_the_lock_is_not_taken(self):
        fake = self.FakeMsvcrt()
        fake.busy.add((1, 2))
        with patch.object(updates.os, 'name', 'nt'), patch.dict(sys.modules, {'msvcrt': fake}):
            self.stream.seek(0)
            self.assertTrue(updates._try_lock(self.stream), '只锁 1 个字节时不会碰到别人锁住的第 2 个字节')
        fake.busy = {(0, 1)}
        with patch.object(updates.os, 'name', 'nt'), patch.dict(sys.modules, {'msvcrt': fake}):
            self.stream.seek(0)
            self.assertFalse(updates._try_lock(self.stream))
