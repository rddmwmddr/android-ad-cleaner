#!/usr/bin/env python3
"""桌面版引擎：电脑经 USB 用 hdc 操作手机，手机上不用装任何东西。

和手机 App 的引擎同一套规则（entry/src/main/ets/engine/），开关清单也是同一份 Recipes.ets。
没有签名、没有开发者账号、不会到期；跑完拔线，开发者模式可以关掉。

用法：python3 gui/harmony_engine.py status
      python3 gui/harmony_engine.py freeze <路径>   把开关清单冻结成 json，打包用
去广告和还原统一从桌面窗口执行，以保存原状态并协调停止。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

try:
    from . import hdc_fetch
except ImportError:
    import hdc_fetch

HERE = Path(__file__).resolve().parent
BUNDLE = Path(getattr(sys, '_MEIPASS', HERE.parent))

SYSTEM_UI = 'com.ohos.sceneboard'
SETTINGS = 'com.huawei.hmos.settings'
SETTINGS_ABILITY = 'com.huawei.hmos.settings.MainAbility'
DUMP = '/data/local/tmp/roudai_layout.json'
CONFIRM_WORDS = ('确认停用', '仍要关闭', '确认关闭', '关闭', '确定', '确认', '继续', '知道了')
CONSENT_WORDS = ('同意', '同意并继续', '同意并使用')
SAME_ROW = 110
WEB_WAIT = 60
WEB_STEPS = 14
SMALL_STEP = 0.35
MIN_SCROLL_AREA = 200000
MIN_LANE = 16
INVISIBLE = re.compile('[\u200b-\u200f\u202a-\u202e\u2060\ufeff]')

# 锁屏界面才有的节点。锁屏时不操作，请机主自己解锁。
LOCK_MARKS = ('MainPageView_Screen_Lock_Home', 'ScreenLock-QuickToolBar')


class DeviceLost(Exception):
    """手机断开了。"""


class ScreenLocked(Exception):
    """手机锁屏了。"""


class Stopped(Exception):
    """用户点了停止。"""



def clean_text(text):
    return INVISIBLE.sub('', text or '').strip()


def key_of(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', clean_text(text)))


class Rect:
    __slots__ = ('left', 'top', 'right', 'bottom')

    def __init__(self, bounds):
        parts = re.findall(r'-?\d+', bounds or '')
        self.left, self.top, self.right, self.bottom = (map(int, parts) if len(parts) == 4 else (0, 0, 0, 0))

    @property
    def area(self):
        w, h = self.right - self.left, self.bottom - self.top
        return w * h if w > 0 and h > 0 else 0

    @property
    def cx(self):
        return (self.left + self.right) // 2

    @property
    def cy(self):
        return (self.top + self.bottom) // 2

    def contains(self, x, y):
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def contains_rect(self, o):
        return o.left >= self.left and o.right <= self.right and o.top >= self.top and o.bottom <= self.bottom

    def overlap(self, o):
        w = min(self.right, o.right) - max(self.left, o.left)
        h = min(self.bottom, o.bottom) - max(self.top, o.top)
        return w * h if w > 0 and h > 0 else 0


class Item:
    __slots__ = ('type', 'text', 'description', 'rect', 'checkable', 'checked', 'enabled', 'scrollable')

    def __init__(self, a):
        self.type = a.get('type', '')
        self.text = clean_text(a.get('text'))
        self.description = clean_text(a.get('description'))
        self.rect = Rect(a.get('bounds'))
        self.checkable = a.get('checkable') == 'true'
        self.checked = a.get('checked') == 'true'
        self.enabled = a.get('enabled') != 'false'
        self.scrollable = a.get('scrollable') == 'true'


def _is_layer(a):
    return a.get('type') in ('NavDestination', 'Dialog') and a.get('visible') != 'false' and Rect(a.get('bounds')).area > 0


class Screen:
    """只留看得见的节点。规则见 Screen.ets 文件头。"""

    def __init__(self, root):
        scope = root
        for child in root.get('children', []):
            bundle = child.get('attributes', {}).get('bundleName', '')
            if bundle and bundle != SYSTEM_UI:
                scope = child
                break
        attrs = scope.get('attributes', {})
        self.bundle = attrs.get('bundleName', '')
        self.window = Rect(attrs.get('bounds'))
        found = []

        def find(node):
            if _is_layer(node.get('attributes', {})):
                found.append(node)
            for c in node.get('children', []):
                find(c)
        find(scope)
        visible, rects = [], []
        for node in reversed(found):
            r = Rect(node['attributes'].get('bounds'))
            if sum(r.overlap(u) for u in rects) < r.area / 2:
                visible.append(node)
                rects.append(r)
        self.items, seen = [], set()

        def collect(node):
            a = node.get('attributes', {})
            if id(a) not in seen:
                seen.add(id(a))
                self.items.append(Item(a))
            for c in node.get('children', []):
                collect(c)
        for node in visible:
            collect(node)
        top = visible[0] if visible else None
        passed = [False]

        def rest(node):
            a = node.get('attributes', {})
            if _is_layer(a):
                passed[0] = passed[0] or node is top
                return
            r = Rect(a.get('bounds'))
            if (passed[0] or not any(u.contains(r.cx, r.cy) for u in rects)) and id(a) not in seen:
                seen.add(id(a))
                self.items.append(Item(a))
            for c in node.get('children', []):
                rest(c)
        rest(scope)

    def find_text(self, title):
        wanted, loose = key_of(title), None
        for item in self.items:
            if item.rect.area <= 0 or not item.text:
                continue
            key = key_of(item.text)
            if key == wanted:
                return item
            if loose is None and item.type == 'Text' and key.startswith(wanted + ','):
                loose = item
        return loose

    def find_all(self, title):
        wanted = key_of(title)
        return [i for i in self.items if i.rect.area > 0 and i.text and key_of(i.text) == wanted]

    def has_consent(self):
        return any((i.type in ('Button', 'Text') and i.text in CONSENT_WORDS) or i.text == '隐私声明变更通知' for i in self.items)

    def switch_for(self, title):
        x, y, best = title.rect.cx, title.rect.cy, None
        for item in self.items:
            if not item.checkable or item.rect.area <= 0 or item.type == 'Checkbox':
                continue
            beside = abs(item.rect.cy - y) <= SAME_ROW and item.rect.left >= title.rect.left
            if (item.rect.contains(x, y) or beside) and (best is None or item.rect.area < best.rect.area):
                best = item
        return best

    def switch_below(self, title):
        best = None
        for item in self.items:
            if item.checkable and item.type == 'switch' and item.rect.area > 0 and item.rect.top >= title.rect.bottom:
                if best is None or item.rect.top < best.rect.top:
                    best = item
        return best

    def tap_target(self, control):
        best = control.rect
        for item in self.items:
            if item.type in ('Toggle', 'switch') and 0 < item.rect.area < best.area and control.rect.contains_rect(item.rect):
                best = item.rect
        return best

    def radios(self):
        return sorted((i for i in self.items if i.type == 'Radio' and i.rect.area > 0), key=lambda i: i.rect.left)

    def scroll_areas(self):
        # 网页节点不标 scrollable，但能滚；网页里的内容要滚到附近才出现在读屏结果里。
        rects = sorted((i.rect for i in self.items if (i.scrollable or i.type == 'Web') and i.rect.area >= MIN_SCROLL_AREA),
                       key=lambda r: -r.area)
        out = []
        for r in rects:
            if not any(b.contains_rect(r) for b in out):
                out.append(r)
        return out

    def swipe_column(self, area):
        left, right = area.right, area.left
        for item in self.items:
            r = item.rect
            if item.scrollable and MIN_SCROLL_AREA <= r.area < area.area and area.contains_rect(r) and r.contains(area.cx, r.cy):
                left, right = min(left, r.left), max(right, r.right)
        if left >= right:
            return area.cx
        if left - area.left >= MIN_LANE:
            return area.left + (left - area.left) // 2
        if area.right - right >= MIN_LANE:
            return right + (area.right - right) // 2
        return area.cx

    def signature(self):
        return '|'.join(i.text for i in self.items if i.text)


def _no_window():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def hdc_candidates(*, arch=None, env=None, bundle=None, which=None, home=None):
    """显式 HDC → 缓存目录 → 包内 → PATH → SDK 默认（#898）。"""
    env = os.environ if env is None else env
    arch = hdc_fetch.arch_of() if arch is None else arch
    exe = 'hdc.exe' if os.name == 'nt' else 'hdc'
    bundle = BUNDLE if bundle is None else bundle
    home = Path.home() if home is None else Path(home)
    which = shutil.which if which is None else which
    found = [env.get('HDC')]
    if arch:
        found += [str(hdc_fetch.cache_dir(arch, env) / exe),
                  str(Path(bundle) / 'harmony' / 'desktop' / 'vendor' / arch / exe)]
    found += [which('hdc'), str(home / '.local/share/harmony-clt/sdk/default/openharmony/toolchains' / exe)]
    return [c for c in found if c]


def find_hdc(*, arch=None, env=None, bundle=None, which=None, home=None):
    for c in hdc_candidates(arch=arch, env=env, bundle=bundle, which=which, home=home):
        if Path(c).is_file():
            return c
    raise FileNotFoundError('没找到 hdc；源码运行请先执行 python gui/hdc_fetch.py')


def devices(hdc):
    """返回 [(序列号, 状态)]。只看 USB，电脑上的串口设备也会出现在 hdc 列表里。"""
    out = subprocess.run([hdc, 'list', 'targets', '-v'], capture_output=True, text=True, encoding='utf-8',
                         errors='replace', timeout=20, check=True, **_no_window()).stdout
    rows = []
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 3 and f[1] == 'USB':
            rows.append((f[0], f[2]))
    return rows


class Phone:
    def __init__(self, hdc, serial, should_stop=None):
        self.hdc, self.serial = hdc, serial
        self.should_stop = should_stop or (lambda: False)
        self.holding = False
        self.before_change = lambda title, before: None

    def shell(self, cmd, timeout=30):
        # 点了开关还没回读确认时不响应停止，否则这次改动记不下来，以后也还原不了。
        if self.should_stop() and not self.holding:
            raise Stopped()
        try:
            r = subprocess.run([self.hdc, '-t', self.serial, 'shell', cmd], capture_output=True, timeout=timeout, **_no_window())
        except (subprocess.TimeoutExpired, OSError) as e:
            raise DeviceLost('鸿蒙连接中断') from e
        if r.returncode:
            raise DeviceLost('鸿蒙命令未完成')
        return r.stdout.decode('utf-8', 'replace').replace('\r', '')

    def param(self, name):
        return self.shell(f'param get {name}').strip()

    def read(self):
        for _ in range(3):
            raw = self.shell(f'rm -f {DUMP}; uitest dumpLayout -p {DUMP} >/dev/null 2>&1; cat {DUMP}; rm -f {DUMP}')
            if any(mark in raw for mark in LOCK_MARKS):
                raise ScreenLocked()
            try:
                return Screen(json.loads(raw[raw.index('{'):]))
            except ValueError:
                time.sleep(0.5)
        raise DeviceLost('读屏失败')

    def tap(self, x, y):
        self.shell(f'uitest uiInput click {x} {y}')
        time.sleep(0.5)

    def back(self):
        self.shell('uitest uiInput keyEvent Back')
        time.sleep(0.5)

    def home(self):
        self.shell('uitest uiInput keyEvent Home')

    def open_uri(self, uri):
        self.shell(f"aa force-stop {SETTINGS}; aa start -b {SETTINGS} -a {SETTINGS_ABILITY} -U '{uri}'")
        time.sleep(1.2)

    def open_developer_options(self):
        self.shell(f"aa start -b {SETTINGS} -a {SETTINGS_ABILITY} -U 'developer_options_settings'")

    def open_home(self):
        # 不带页面打开设置。展开时右栏默认是系统更新页，只点左栏，那一页不碰。
        self.shell(f'aa force-stop {SETTINGS}; aa start -b {SETTINGS} -a {SETTINGS_ABILITY}')
        time.sleep(1.2)

    def open_app(self, bundle, ability):
        self.shell(f'aa force-stop {bundle}; aa start -b {bundle} -a {ability}')
        time.sleep(1.2)

    def swipe(self, screen, area, up, fraction=0.6):
        x = screen.swipe_column(area)
        middle, half = (area.top + area.bottom) // 2, int((area.bottom - area.top) * fraction / 2)
        low, high = middle + half, middle - half
        a, b = (high, low) if up else (low, high)
        self.shell(f'uitest uiInput swipe {x} {a} {x} {b} 300')
        time.sleep(0.5)

    def _visible(self, screen, title):
        item = screen.find_text(title)
        return item if item is not None and item.rect.bottom < screen.window.bottom - 40 else None

    def find_scrolling(self, title):
        screen = self.read()
        if self._visible(screen, title):
            return screen
        for area in screen.scroll_areas():
            for up in (False, True):
                last = screen.signature()
                for _ in range(12 if up else 6):
                    self.swipe(screen, area, up)
                    screen = self.read()
                    if self._visible(screen, title):
                        return screen
                    sig = screen.signature()
                    if sig == last:
                        break
                    last = sig
        return None

    def wait_ready(self, title):
        deadline = time.time() + 9
        while time.time() < deadline:
            screen = self.read()
            if screen.find_text(title) or screen.has_consent():
                return
            time.sleep(0.5)

    def tap_text(self, title):
        screen = self.find_scrolling(title)
        if screen is None:
            return False
        item = self._visible(screen, title)
        self.tap(item.rect.cx, item.rect.cy)
        return True

    def control_of(self, screen, t):
        if t['radio'] >= 0:
            radios = screen.radios()
            return radios[t['radio']] if t['radio'] < len(radios) else None
        for label in screen.find_all(t['title']):
            c = screen.switch_below(label) if t['below'] else screen.switch_for(label)
            if c is not None:
                return c
        return None

    def find_in_web(self, t):
        """开关在网页里：先等网页出来，再只在网页里往下翻，直到开关出现。

        这类网页读一次屏要好几秒，内容也要滚到附近才读得到，不能用通用的翻页找法。
        """
        deadline = time.time() + WEB_WAIT
        screen, web = None, None
        while time.time() < deadline:
            screen = self.read()
            web = next((i.rect for i in screen.items if i.type == 'Web' and i.rect.area >= MIN_SCROLL_AREA), None)
            if web is not None:
                break
            time.sleep(1)
        if web is None:
            return screen, None
        for _ in range(WEB_STEPS):
            control = self.control_of(screen, t)
            if control is not None:
                return screen, control
            if time.time() > deadline:
                break
            self.swipe(screen, web, False, SMALL_STEP if screen.find_all(t['title']) else 0.5)
            screen = self.read()
        return screen, self.control_of(screen, t)

    def set_switch(self, t, want):
        """返回 (结果, 原状态)。结果：changed already moot missing locked failed"""
        if t['below']:
            screen, control = self.find_in_web(t)
        else:
            screen = self.read() if t['radio'] >= 0 else self.find_scrolling(t['title'])
            control = self.control_of(screen, t) if screen else None
        if screen is None or control is None:
            return 'missing', False
        before = control.checked
        if before == want:
            return 'already', before
        if t['moot'] and screen.find_text(t['moot']):
            return 'moot', before
        if not control.enabled:
            return 'locked', before
        point = screen.tap_target(control)
        if t['radio'] >= 0 and not want:
            others = [r for r in screen.radios() if r is not control]
            if not others:
                return 'missing', before
            point = others[0].rect
        self.before_change(t['title'], before)
        self.holding = True
        try:
            self.tap(point.cx, point.cy)
            for _ in range(5):
                after = self.read()
                current = self.control_of(after, t)
                if current is not None and current.checked == want:
                    return 'changed', before
                button = next((i for w in CONFIRM_WORDS for i in after.items
                               if i.rect.area > 0 and (i.text == w or i.description == w)), None)
                if button is not None:
                    self.tap(button.rect.cx, button.rect.cy)
                else:
                    time.sleep(0.5)
            return 'failed', before
        finally:
            self.holding = False


def load_segments():
    """开关清单和手机 App 用同一份。打包时冻结成 recipes.json，源码运行时从 Recipes.ets 现算。"""
    frozen = BUNDLE / 'harmony' / 'recipes.json'
    if hasattr(sys, '_MEIPASS') and frozen.exists():
        return json.loads(frozen.read_text('utf-8'))
    try:
        from . import harmony_vocab as vocab
    except ImportError:
        import harmony_vocab as vocab
    segments = []
    for g in vocab.parse().groups:
        pages, order = {}, []
        for w in g.words:
            key = tuple(w.path)
            if key not in pages:
                pages[key] = []
                order.append(key)
            pages[key].append({'title': w.text, 'want': w.helper in ('on', 'choose'),
                               'below': w.helper == 'offBelow', 'radio': w.radio,
                               'moot': '通知已关闭' if w.helper == 'offUnlessMuted' else ''})
        segments.append({'id': g.segment_id, 'name': g.name, 'kind': g.entry_kind, 'value': g.entry_value,
                         'ability': g.entry_ability, 'path': g.entry_path,
                         'pages': [{'path': list(k), 'targets': pages[k]} for k in order]})
    return segments


def key_for(segment_id, title):
    return f'{segment_id}/{title}'


def _run_segment(phone, seg, wanted, emit):
    phone.before_change = lambda title, before: emit('before', {'id': seg['id'], 'title': title, 'before': before})
    if seg['kind'] == 'uri':
        phone.open_uri(seg['value'])
    elif seg['kind'] == 'home':
        phone.open_home()
    else:
        phone.open_app(seg['value'], seg['ability'])
        phone.wait_ready(seg['path'][0])
    if phone.read().has_consent():
        emit('segment', {'id': seg['id'], 'status': 'skipped', 'note': '这个 App 还没同意过协议'})
        return
    if not all(phone.tap_text(step) for step in seg['path']):
        emit('segment', {'id': seg['id'], 'status': 'unreachable', 'note': ''})
        return
    trouble = False
    for page in seg['pages']:
        if not all(phone.tap_text(step) for step in page['path']):
            trouble = True
            continue
        for t in page['targets']:
            want = wanted(t)
            if want is None:
                continue
            result, before = phone.set_switch(t, want)
            emit('switch', {'id': seg['id'], 'title': t['title'], 'result': result, 'before': before, 'want': want})
            if result not in ('changed', 'already', 'moot'):
                trouble = True
        for _ in page['path']:
            phone.back()
    emit('segment', {'id': seg['id'], 'status': 'partial' if trouble else 'done', 'note': ''})


def run(phone, segments, values=None, emit=None):
    """跑清单。values 为 None 时去广告；否则按 {段/词: 目标状态} 还原，清单之外不动。

    emit(kind, data) 收进度：segment 带 id、status、note；switch 带 id、title、result、before、want；
    retry 带 id、error。一段里读屏偶尔失败而手机还连着时，这一段重跑一次。
    DeviceLost、ScreenLocked、Stopped 向外抛，已经发出的 switch 事件仍然有效。
    """
    emit = emit or (lambda kind, data: None)
    for seg in segments:
        def wanted(t, seg=seg):
            return t['want'] if values is None else values.get(key_for(seg['id'], t['title']))
        if values is not None and not any(wanted(t) is not None for p in seg['pages'] for t in p['targets']):
            emit('segment', {'id': seg['id'], 'status': 'skipped', 'note': ''})
            continue
        emit('segment', {'id': seg['id'], 'status': 'running', 'note': ''})
        for attempt in range(2):
            try:
                _run_segment(phone, seg, wanted, emit)
                break
            except DeviceLost as e:
                if attempt == 1 or 'ok' not in phone.shell('echo ok'):
                    raise
                emit('retry', {'id': seg['id'], 'error': str(e)[:80]})
    phone.home()


def main(argv):
    command = argv[1] if len(argv) > 1 else 'status'
    if command == 'freeze':
        Path(argv[2]).write_text(json.dumps(load_segments(), ensure_ascii=False, indent=1), 'utf-8')
        return 0
    if command != 'status':
        print(__doc__, file=sys.stderr)
        return 1
    hdc = find_hdc()
    ready = [s for s, st in devices(hdc) if st == 'Connected']
    print('已连接', len(ready), '台')
    return 0 if ready else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
