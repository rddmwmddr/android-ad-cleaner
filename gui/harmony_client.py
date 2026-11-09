"""#890：统一桌面客户端的鸿蒙任务、原状态与日志；手机操作仍由鸿蒙引擎负责。"""
import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from . import harmony_engine as engine
except ImportError:
    import harmony_engine as engine

MIN_API = 20


def legacy_data_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/RoudaiHarmony'
    if os.name == 'nt':
        return Path(os.environ.get('APPDATA', Path.home())) / 'RoudaiHarmony'
    return Path.home() / '.roudai-harmony'


class ChangeLog:
    """按设备哈希隔离。首次使用复制旧客户端记录，空记录也保留以免再次导入。"""
    def __init__(self, root, serial, legacy=None):
        name = 'changes-' + hashlib.sha256(serial.encode()).hexdigest()[:16] + '.json'
        self.path = Path(root) / name
        self.legacy = Path(legacy) / name if legacy is not None else None

    def load(self):
        source = self.path if self.path.exists() else self.legacy
        if source is None or not source.exists():
            return {}
        if source.stat().st_size > 1_000_000:
            raise ValueError('还原记录过大，请保留原文件并反馈问题')
        values = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(values, dict) or any(not isinstance(k, str) or type(v) is not bool for k, v in values.items()):
            raise ValueError('还原记录损坏，请保留原文件并反馈问题')
        if source != self.path:
            self.save(values)
        return values

    def save(self, values):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(values, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, self.path)


def plan_views(segments):
    return [{'id': s['id'], 'name': s['name'], 'status': 'waiting', 'note': '',
             'rows': [{'title': t['title'], 'want': t['want'], 'result': ''}
                      for p in s['pages'] for t in p['targets']]} for s in segments]


class HarmonyClient:
    def __init__(self, root, claim, release, *, hdc=None, legacy=None, phone_factory=engine.Phone, segments=None):
        self.root = Path(root) / 'harmony'
        self.legacy = legacy_data_dir() if legacy is None else Path(legacy)
        self.claim, self.release = claim, release
        self.hdc = hdc
        self.phone_factory = phone_factory
        self.segments = engine.load_segments() if segments is None else segments
        self.lock = threading.RLock()
        self.phase, self.mode, self.message = 'idle', 'clean', ''
        self.device = {}
        self.views = plan_views(self.segments)
        self.lines = []
        self.worker = None
        self.stop_flag = threading.Event()
        self.task_done = threading.Event()
        self.task_done.set()
        self.closing = False
        self.can_restore = False
        self.last_progress = 0.0
        self.last_selected = []

    def _hdc(self):
        if not self.hdc:
            self.hdc = engine.find_hdc()
        return self.hdc

    def devices(self):
        try:
            hdc = self._hdc()
        except FileNotFoundError:
            return {'available': False, 'list': [], 'error': '鸿蒙连接工具缺失，请重新下载完整客户端'}
        try:
            found = engine.devices(hdc)
        except (OSError, subprocess.SubprocessError):
            return {'available': True, 'list': [], 'error': '鸿蒙连接工具未能响应，请重新插线后重试'}
        rows = []
        for serial, state in found:
            d = {'serial': serial, 'platform': 'harmony', 'state': state, 'name': '', 'model': '', 'api': '', 'supported': False}
            if state == 'Connected':
                try:
                    phone = self.phone_factory(hdc, serial)
                    d.update(name=phone.param('const.product.name'), model=phone.param('const.product.model'),
                             api=phone.param('const.ohos.apiversion'))
                    d['supported'] = d['api'].isdigit() and int(d['api']) >= MIN_API
                except (engine.DeviceLost, OSError, subprocess.SubprocessError):
                    d['state'] = 'Disconnected'
            rows.append(d)
        return {'available': True, 'list': rows, 'error': ''}

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({'phase': self.phase, 'mode': self.mode, 'device': self.device,
                                  'segments': self.views, 'message': self.message, 'can_restore': self.can_restore,
                                  'stalled': self.phase == 'running' and time.monotonic() - self.last_progress > 60,
                                  'stopping': self.stop_flag.is_set(), 'lines': self.lines[-300:]})

    def _device(self, serial):
        if not isinstance(serial, str) or not serial:
            raise ValueError('请先选择要操作的鸿蒙手机')
        result = self.devices()
        if result['error']:
            raise ValueError(result['error'])
        device = next((d for d in result['list'] if d['serial'] == serial), None)
        if device is None or device['state'] != 'Connected':
            raise ValueError('选中的鸿蒙手机已断开或尚未授权，请重新连接')
        if not device['supported']:
            raise ValueError('此系统版本不在当前鸿蒙规则范围内；鸿蒙 4 及以前请走安卓连接')
        return device

    def _claim(self, name):
        with self.lock:
            if self.closing:
                return '窗口正在关闭，请重新打开客户端后操作'
            held = self.claim(name)
            if not held:
                self.task_done.clear()
                self.stop_flag.clear()
                self.phase = 'preparing'
            return held

    def _release(self):
        with self.lock:
            if self.phase == 'preparing':
                self.phase = 'idle'
            self.release()
            self.task_done.set()

    def close_if_idle(self):
        with self.lock:
            if not self.task_done.is_set():
                return False
            self.closing = True
            return True

    def select(self, serial):
        held = self._claim('检测鸿蒙手机')
        if held:
            return {'error': held}
        try:
            device = self._device(serial)
            values = ChangeLog(self.root, serial, self.legacy).load()
            with self.lock:
                self.device, self.phase, self.message = device, 'idle', ''
                self.views = plan_views(self.segments)
                self.can_restore = bool(values)
                self.last_selected = []
                self.lines = []
            return self.snapshot()
        except (ValueError, OSError) as error:
            return {'error': str(error) if isinstance(error, ValueError) else '无法读取还原记录，请检查备份目录权限'}
        finally:
            self._release()

    def start(self, serial, mode='clean', selected=None):
        if mode not in ('clean', 'restore'):
            return {'error': '未知的鸿蒙操作'}
        if selected is not None and (not isinstance(selected, list) or any(not isinstance(s, str) for s in selected)):
            return {'error': '请选择要执行的设置分组'}
        chosen = [s for s in self.segments if selected is None or s['id'] in selected]
        if not chosen:
            return {'error': '至少选择一项设置'}
        held = self._claim('鸿蒙还原' if mode == 'restore' else '鸿蒙去广告')
        if held:
            return {'error': held}
        try:
            device = self._device(serial)
            log = ChangeLog(self.root, serial, self.legacy)
            values = log.load()
            if mode == 'restore' and not values:
                raise ValueError('这台手机没有可还原的改动')
            # 在第一下点击之前验证可持久化；已有记录损坏或目录不可写时不能继续。
            log.save(values)
            with self.lock:
                if self.stop_flag.is_set():
                    raise engine.Stopped()
                self.device, self.phase, self.mode, self.message = device, 'running', mode, ''
                self.views = plan_views(chosen)
                self.last_selected = [s['id'] for s in chosen]
                self.last_progress = time.monotonic()
                self.worker = threading.Thread(target=self._run, args=(device, chosen, mode, log, values))
                self.worker.start()
            return {'ok': True}
        except engine.Stopped:
            self._release()
            return {'error': '已取消启动，未执行手机操作'}
        except (ValueError, OSError, RuntimeError) as error:
            with self.lock:
                self.phase = 'idle'
            self._release()
            return {'error': str(error) if isinstance(error, ValueError) else '无法开始任务，请检查连接和备份目录权限'}

    def retry(self):
        with self.lock:
            if self.phase != 'done':
                return {'error': '当前没有已结束的鸿蒙任务'}
            ids = [s['id'] for s in self.views if s['status'] in ('partial', 'unreachable', 'interrupted', 'waiting')]
            serial, mode = self.device.get('serial', ''), self.mode
        if not ids:
            return {'error': '没有需要重试的步骤'}
        return self.start(serial, mode, ids)

    def stop(self):
        self.stop_flag.set()
        return {'ok': True}

    def close_when_done(self, callback):
        """先完成当前开关的回读与记账，再关窗口；不杀共享 HDC 服务。"""
        with self.lock:
            self.closing = True
            self.stop()
        def wait():
            self.task_done.wait()
            callback()
        threading.Thread(target=wait, daemon=True).start()

    def developer_options(self, serial):
        held = self._claim('打开鸿蒙开发者选项')
        if held:
            return {'error': held}
        try:
            self._device(serial)
            if self.stop_flag.is_set():
                raise engine.Stopped()
            self.phone_factory(self._hdc(), serial, self.stop_flag.is_set).open_developer_options()
            return {'ok': True}
        except (ValueError, engine.Stopped, engine.DeviceLost, OSError, subprocess.SubprocessError):
            return {'error': '没能打开，请在手机设置中手动关闭开发者选项'}
        finally:
            self._release()

    def _line(self, text):
        with self.lock:
            self.lines.append(text)
            self.lines = self.lines[-1000:]
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / 'run-log.txt'
            if path.exists() and path.stat().st_size > 200_000:
                path.replace(path.with_suffix('.old.txt'))
            with path.open('a', encoding='utf-8') as stream:
                stream.write(time.strftime('%m-%d %H:%M:%S ') + text + '\n')
        except OSError:
            pass

    def _event(self, kind, data, log, values, restoring):
        key = engine.key_for(data['id'], data.get('title', ''))
        if kind == 'before' and not restoring and key not in values:
            updated = dict(values, **{key: data['before']})
            log.save(updated)  # 必须成功落盘才允许引擎点击。
            values.update(updated)
        if kind == 'switch' and restoring and data['result'] in ('changed', 'already'):
            updated = dict(values)
            updated.pop(key, None)
            log.save(updated)
            values.clear()
            values.update(updated)
        with self.lock:
            self.last_progress = time.monotonic()
            view = next(v for v in self.views if v['id'] == data['id'])
            if kind == 'segment':
                view.update(status=data['status'], note=data['note'])
            elif kind == 'switch':
                for row in view['rows']:
                    if row['title'] == data['title']:
                        row.update(result=data['result'], want=data['want'])
            self.can_restore = bool(values)
        if kind == 'segment':
            self._line(f"{view['name']}：{data['status']} {data['note']}")
        elif kind == 'switch':
            self._line(f"{view['name']} / {data['title']}：{data['result']}")
        elif kind == 'retry':
            self._line(f"{view['name']}：正在重试本段")

    def _run(self, device, segments, mode, log, values):
        message = ''
        try:
            if self.stop_flag.is_set():
                raise engine.Stopped()
            phone = self.phone_factory(self._hdc(), device['serial'], self.stop_flag.is_set)
            # 锁屏检查在启动任何设置页前完成；不绕过、不唤醒解锁。
            phone.read()
            self._line('开始还原' if mode == 'restore' else '开始去广告')
            engine.run(phone, segments, dict(values) if mode == 'restore' else None,
                       lambda kind, data: self._event(kind, data, log, values, mode == 'restore'))
        except engine.ScreenLocked:
            message = '手机锁屏了。请解锁后重试未完成步骤。'
        except engine.Stopped:
            message = '已停止，原状态已保存，可以还原。'
        except (engine.DeviceLost, subprocess.SubprocessError):
            message = '手机连接或读屏中断，请重新连接后重试。'
        except OSError:
            message = '任务中断。请检查连接和备份目录权限，保留已有还原记录。'
        except Exception as error:
            message = f'任务中断（{type(error).__name__}），请复制运行日志反馈。'
        finally:
            with self.lock:
                for view in self.views:
                    if view['status'] in ('running', 'waiting'):
                        view['status'] = 'interrupted'
                self.message = message
                self.can_restore = bool(values)
                self.phase = 'done'
            self._line(message or '本轮结束，请核对每一项结果')
            self._release()

    def command(self, action, serial='', mode='clean', segments=None):
        if action == 'devices':
            return self.devices()
        if action == 'poll':
            return self.snapshot()
        if action == 'select':
            return self.select(serial)
        if action == 'start':
            return self.start(serial, mode, segments)
        if action == 'retry':
            return self.retry()
        if action == 'stop':
            return self.stop()
        if action == 'developer_options':
            return self.developer_options(serial)
        if action == 'log':
            with self.lock:
                return '\n'.join(self.lines)
        return {'error': '未知的鸿蒙操作'}
