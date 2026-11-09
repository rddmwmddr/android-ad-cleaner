"""#890：鸿蒙接入后的选机、互斥、持久化、停止和旧数据兼容。"""
import json
import io
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from gui import app, harmony_client as client, harmony_engine as engine
from gui.bundle_data import bundle_data
from fixtures import FakeRunner
from test_harmony_engine import FakePhone, SWITCH, switch_page

ROOT = Path(__file__).resolve().parents[1]
SEGMENTS = [dict(id='search', name='小艺搜索', pages=[dict(path=[], targets=[dict(SWITCH, title='热搜榜')])]),
            dict(id='feed', name='负一屏', pages=[dict(path=[], targets=[dict(SWITCH, title='资讯')])])]


class Phone:
    instances = []
    locked = False

    def __init__(self, hdc, serial, should_stop=None):
        self.serial = serial
        self.should_stop = should_stop or (lambda: False)
        self.instances.append(self)

    def param(self, name):
        return {'const.product.name': '测试手机', 'const.product.model': 'TEST-001', 'const.ohos.apiversion': '26'}[name]

    def read(self):
        if self.locked:
            raise engine.ScreenLocked()


class ClientTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        Phone.instances, Phone.locked = [], False
        self.api = app.Api(self.root, runner=FakeRunner())
        self.service = client.HarmonyClient(self.root, self.api.dispatcher.claim, self.api.dispatcher.release,
                                            hdc='test-hdc', legacy=self.root / 'legacy', phone_factory=Phone, segments=SEGMENTS)
        self.api.harmony_bridge.service = self.service
        patcher = patch.object(engine, 'devices', return_value=[('first', 'Connected'), ('second', 'Connected')])
        self.devices = patcher.start()
        self.addCleanup(patcher.stop)

    def wait(self):
        self.service.worker.join(3)
        self.assertFalse(self.service.worker.is_alive())
        self.assertEqual(self.api.dispatcher.side, '')

    def test_chooses_explicit_device_and_only_selected_segments(self):
        def run(phone, segments, values, emit):
            self.assertEqual(phone.serial, 'second')
            self.assertEqual([s['id'] for s in segments], ['feed'])
            emit('before', dict(id='feed', title='资讯', before=True))
            emit('switch', dict(id='feed', title='资讯', before=True, want=False, result='changed'))
            emit('segment', dict(id='feed', status='done', note=''))
        with patch.object(engine, 'run', side_effect=run) as operation:
            self.assertTrue(self.service.start('second', selected=['feed'])['ok'])
            self.wait()
            operation.assert_called_once()
        self.devices.assert_called_once_with('test-hdc')
        self.assertEqual(client.ChangeLog(self.service.root, 'second').load(), {'feed/资讯': True})
        self.assertFalse(client.ChangeLog(self.service.root, 'first').path.exists())
        self.assertEqual(self.service.snapshot()['segments'][0]['rows'][0]['result'], 'changed')

    def test_no_default_device_and_rejects_disconnected_selection(self):
        with patch.object(engine, 'run') as operation:
            for serial in ('', 'missing'):
                self.assertIn('error', self.service.start(serial))
            operation.assert_not_called()
        self.devices.assert_called_once()
        self.assertEqual(self.api.dispatcher.side, '')

    def test_untrusted_device_never_creates_a_phone(self):
        self.devices.return_value = [('first', 'Unauthorized')]
        self.assertIn('error', self.service.start('first'))
        self.devices.assert_called_once()
        self.assertEqual(Phone.instances, [])

    def test_lock_screen_stops_before_opening_settings(self):
        Phone.locked = True
        with patch.object(engine, 'run') as operation:
            self.assertTrue(self.service.start('first')['ok'])
            self.wait()
            operation.assert_not_called()
        self.assertIn('锁屏', self.service.snapshot()['message'])
        self.assertTrue(all(s['status'] == 'interrupted' for s in self.service.snapshot()['segments']))

    def test_shared_gate_blocks_android_restore_update_and_second_harmony_task(self):
        entered, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        def run(phone, segments, values, emit):
            entered.set()
            if not finish.wait(2):
                raise AssertionError('test barrier timed out')
            if phone.should_stop():
                raise engine.Stopped()
        with patch.object(engine, 'run', side_effect=run) as operation:
            self.assertTrue(self.service.start('first')['ok'])
            self.assertTrue(entered.wait(2))
            self.assertIn('error', self.api.start('android', {}))
            self.assertTrue(self.api.dispatcher.claim('安装更新'))
            self.assertTrue(self.api.restore('android', 'channels'))
            self.assertIn('error', self.service.start('second'))
            self.service.stop()
            finish.set()
            self.wait()
            operation.assert_called_once()
        self.assertIn('已停止', self.service.snapshot()['message'])

    def test_stop_and_disconnect_keep_pre_click_record(self):
        def run(phone, segments, values, emit):
            emit('before', dict(id='search', title='热搜榜', before=True))
            raise engine.DeviceLost('PRIVATE-DEVICE-SERIAL')
        with patch.object(engine, 'run', side_effect=run) as operation:
            self.assertTrue(self.service.start('second')['ok'])
            self.wait()
            operation.assert_called_once()
        self.assertEqual(client.ChangeLog(self.service.root, 'second').load(), {'search/热搜榜': True})
        self.assertNotIn('PRIVATE-DEVICE-SERIAL', (self.service.root / 'run-log.txt').read_text(encoding='utf-8'))

    def test_repeated_runs_preserve_earliest_original_state(self):
        log = client.ChangeLog(self.service.root, 'first')
        log.save({'search/热搜榜': True})
        def run(phone, segments, values, emit):
            emit('before', dict(id='search', title='热搜榜', before=False))
            emit('segment', dict(id='search', status='done', note=''))
        with patch.object(engine, 'run', side_effect=run) as operation:
            self.service.start('first', selected=['search']); self.wait()
            operation.assert_called_once()
        self.assertEqual(log.load(), {'search/热搜榜': True})

    def test_restore_only_removes_verified_rows_and_keeps_failed_rows(self):
        log = client.ChangeLog(self.service.root, 'first')
        log.save({'search/热搜榜': True, 'feed/资讯': False})
        def run(phone, segments, values, emit):
            self.assertEqual(values, {'search/热搜榜': True, 'feed/资讯': False})
            emit('switch', dict(id='search', title='热搜榜', want=True, before=False, result='changed'))
            emit('switch', dict(id='feed', title='资讯', want=False, before=True, result='failed'))
        with patch.object(engine, 'run', side_effect=run) as operation:
            self.service.start('first', 'restore'); self.wait()
            operation.assert_called_once()
        self.assertEqual(log.load(), {'feed/资讯': False})
        self.assertTrue(self.service.snapshot()['can_restore'])

    def test_corrupt_record_blocks_work_without_overwriting_it(self):
        log = client.ChangeLog(self.service.root, 'first')
        log.path.parent.mkdir(parents=True)
        log.path.write_text('{broken', encoding='utf-8')
        with patch.object(engine, 'run') as operation:
            self.assertIn('error', self.service.start('first'))
            operation.assert_not_called()
        self.assertEqual(log.path.read_text(encoding='utf-8'), '{broken')

    def test_retry_runs_only_incomplete_segments_for_same_device(self):
        self.service.phase = 'done'
        self.service.device = {'serial': 'second'}
        self.service.views[0]['status'] = 'done'
        self.service.views[1]['status'] = 'partial'
        with patch.object(engine, 'run') as operation:
            self.assertTrue(self.service.retry()['ok'])
            self.wait()
            operation.assert_called_once()
            self.assertEqual(operation.call_args.args[0].serial, 'second')
            self.assertEqual([s['id'] for s in operation.call_args.args[1]], ['feed'])

    def test_snapshot_is_detached_from_worker_state(self):
        snapshot = self.service.snapshot()
        snapshot['segments'][0]['rows'][0]['title'] = 'corrupt'
        self.assertEqual(self.service.snapshot()['segments'][0]['rows'][0]['title'], '热搜榜')

    def test_unknown_bridge_action_has_no_side_effects(self):
        self.assertIn('error', self.api.harmony('delete_everything'))
        self.devices.assert_not_called()
        self.assertFalse(self.service.root.exists())

    def test_close_waits_until_checkpoint_and_result_are_saved(self):
        entered, finish, closed = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(finish.set)
        def run(phone, segments, values, emit):
            emit('before', dict(id='search', title='热搜榜', before=True))
            entered.set()
            if not finish.wait(2):
                raise AssertionError('test barrier timed out')
            emit('switch', dict(id='search', title='热搜榜', want=False, before=True, result='changed'))
        with patch.object(engine, 'run', side_effect=run) as operation:
            self.service.start('first')
            self.assertTrue(entered.wait(2))
            self.service.close_when_done(closed.set)
            self.assertFalse(closed.is_set())
            finish.set(); self.wait()
            self.assertTrue(closed.wait(2))
            operation.assert_called_once()
        self.assertEqual(client.ChangeLog(self.service.root, 'first').load(), {'search/热搜榜': True})

    def test_close_during_start_preflight_cancels_before_phone_operation(self):
        entered, proceed, closed = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(proceed.set)
        original = self.service._device
        def preflight(serial):
            entered.set()
            if not proceed.wait(3):
                raise AssertionError('test barrier timed out')
            return original(serial)
        result = []
        with patch.object(self.service, '_device', side_effect=preflight), patch.object(engine, 'run') as operation:
            starter = threading.Thread(target=lambda: result.append(self.service.start('first')))
            starter.start()
            self.assertTrue(entered.wait(2))
            phase = self.service.snapshot()['phase']
            self.service.close_when_done(closed.set)
            early_close = closed.is_set()
            proceed.set()
            starter.join(3)
            if self.service.worker is not None:
                self.service.worker.join(3)
            self.assertTrue(closed.wait(2))
            self.assertFalse(starter.is_alive())
            self.assertEqual(phase, 'preparing')
            self.assertFalse(early_close)
            operation.assert_not_called()
        self.assertTrue(self.service.stop_flag.is_set())
        self.assertEqual(self.api.dispatcher.side, '')

    def test_restore_save_failure_keeps_original_record_and_restore_action(self):
        log = client.ChangeLog(self.service.root, 'first')
        original_values = {'search/热搜榜': True}
        log.save(original_values)
        save = client.ChangeLog.save
        def fail_empty(current, values):
            if not values:
                raise OSError('disk full')
            return save(current, values)
        def run(phone, segments, values, emit):
            emit('switch', dict(id='search', title='热搜榜', want=True, before=False, result='changed'))
        with patch.object(client.ChangeLog, 'save', new=fail_empty), patch.object(engine, 'run', side_effect=run):
            self.service.start('first', 'restore')
            self.wait()
        self.assertEqual(log.load(), original_values)
        self.assertTrue(self.service.snapshot()['can_restore'])

    def test_idle_window_close_rejects_late_start_requests(self):
        self.assertTrue(self.service.close_if_idle())
        with patch.object(engine, 'run') as operation:
            self.assertIn('error', self.service.start('first'))
            self.assertIn('error', self.service.developer_options('first'))
            operation.assert_not_called()
        self.devices.assert_not_called()
        self.assertEqual(self.api.dispatcher.side, '')


class HistoryTests(unittest.TestCase):
    def test_legacy_record_migrates_once_and_empty_tombstone_blocks_reimport(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = client.ChangeLog(root / 'legacy', 'SERIAL-SECRET')
            old.save({'search/热搜榜': True})
            new = client.ChangeLog(root / 'new', 'SERIAL-SECRET', root / 'legacy')
            self.assertEqual(new.load(), {'search/热搜榜': True})
            new.save({})
            self.assertEqual(new.load(), {})
            self.assertEqual(old.load(), {'search/热搜榜': True})
            self.assertNotIn('SERIAL-SECRET', str(new.path) + new.path.read_text(encoding='utf-8'))

    def test_invalid_backup_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = client.ChangeLog(tmp, 'phone')
            for invalid in ([], {'key': 1}, {'key': 'false'}):
                log.path.write_text(json.dumps(invalid), encoding='utf-8')
                with self.assertRaises(ValueError):
                    log.load()


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        wait = patch.object(engine.time, 'sleep')
        wait.start()
        self.addCleanup(wait.stop)

    def test_checkpoint_failure_prevents_click(self):
        phone = FakePhone([switch_page(True)])
        def record(title, before):
            self.assertEqual((title, before), ('热搜榜', True))
            raise OSError('disk full')
        phone.before_change = record
        with self.assertRaisesRegex(OSError, 'disk full'):
            phone.set_switch(SWITCH, False)
        self.assertFalse(any('click' in c for c in phone.commands))

    def test_checkpoint_precedes_the_first_physical_click(self):
        phone = FakePhone([switch_page(True), switch_page(False)])
        snapshots = []
        phone.before_change = lambda title, before: snapshots.append((title, before, list(phone.commands)))
        self.assertEqual(phone.set_switch(SWITCH, False), ('changed', True))
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(any('click' in c for c in snapshots[0][2]))
        self.assertTrue(any('click' in c for c in phone.commands))


class PackageTests(unittest.TestCase):
    def test_engine_cli_cannot_bypass_window_selection_and_journaling(self):
        with patch.object(engine, 'find_hdc') as hdc, patch.object(engine, 'run') as operation, redirect_stderr(io.StringIO()):
            self.assertEqual(engine.main(['harmony_engine.py', 'clean']), 1)
        hdc.assert_not_called()
        operation.assert_not_called()

    def test_each_desktop_package_only_contains_its_staged_hdc_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'harmony' / 'desktop' / 'vendor').mkdir(parents=True)
            (root / 'harmony' / 'desktop' / 'vendor' / 'NOTICE-hdc.txt').write_text('license', encoding='utf-8')
            for arch, exe in [('mac-arm64', 'hdc'), ('mac-x64', 'hdc'), ('windows', 'hdc.exe')]:
                vendor = root / 'harmony' / 'desktop' / 'vendor' / arch
                vendor.mkdir()
                (vendor / exe).write_text('bin', encoding='utf-8')
                (vendor / ('libusb_shared.dll' if arch == 'windows' else 'libusb_shared.dylib')).write_text('bin', encoding='utf-8')
            for system, machine, expected in [('darwin', 'arm64', 'mac-arm64'), ('darwin', 'x86_64', 'mac-x64'), ('win32', 'AMD64', 'windows')]:
                with self.subTest(system=system, machine=machine):
                    paths = [Path(src).resolve().relative_to(root.resolve()).as_posix()
                             for src, _ in bundle_data(root, system, machine)]
                    vendors = [p for p in paths if '/vendor/' in p and not p.endswith('.txt')]
                    self.assertEqual(len(vendors), 2)
                    self.assertTrue(all('/' + expected + '/' in p for p in vendors))

    def test_frozen_recipe_is_identical_to_the_source(self):
        self.assertEqual(json.loads((ROOT / 'harmony/recipes.json').read_text(encoding='utf-8')), engine.load_segments())
