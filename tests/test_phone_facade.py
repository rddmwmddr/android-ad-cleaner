"""`Phone` 拆成门面 + 两个基座 + 五个阶段期间，两条对外契约必须有人钉住（ADR-0033、#1037）。

门面守卫：公开成员的名字、是方法还是数据、能不能被赋值，逐条快照。少一个名字、把方法改成数据、
或把可写字段改成只读，都会在真机上炸，而不是在评审里被发现。

脚本访问面守卫：`recipes/` 里 `p.<名字>` 的读取必须仍然取得得到，写入必须仍然赋得进去并读得回来，
集合类字段必须仍是活对象（`p.changed.append(...)` 直接改它，转发成拷贝只会静默失效），
`from fast import …` 的模块级名字也必须仍可 import。

两条都只钉对外契约，钉不到七个模块之间的内部分工——那由代码结构与评审保证。

门面与脚本访问面这两组用例在拆分前的旧树上也全绿：守的是不回退（七步搬迁期间门面公开面与
脚本访问面零变化），不是新增行为。`RecipeWriteTests` 是唯一的例外，它在旧树上红（#1047）。
"""
import ast
import contextlib
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from devtools import script_surface  # noqa: E402
from fixtures import phone_stub  # noqa: E402

RECIPES = ROOT / "recipes"

# 门面的公开方法：类上定义的函数，今天 54 个。方法变成数据（例如搬成实例上绑定的函数）也算红：
# 脚本会把 `p.click` / `p.switches` 换成本地读法，形状变了就不是同一个门面。
METHODS = frozenset({
    "app_stop", "await_page", "back", "check_alive", "click",
    "close", "confirm", "dismiss", "edit_ready",
    "enter", "entry", "expect_hits", "expect_page",
    "find", "focus", "focused_text", "go",
    "has_text", "home", "icon_candidates", "in_settings_page", "locked",
    "ls", "note_miss", "off", "on_screen",
    "page_evidence", "page_text", "press", "residual_confirm", "residual_note",
    "say", "scroll", "scroll_more", "set_text", "setting",
    "settle", "shell", "sig", "start", "swipe", "switch_rows",
    "switches", "tab", "tap", "tap_id", "tap_id_if_present", "tap_icon",
    "texts", "top", "tree", "type_text",
    "wait_unlocked", "window_size",
})

# 公开数据：4 个类常量 + 8 个设备概念属性，今天 12 个（ADR-0045、#1479）。
# 其余状态归协作者（`p.conn.*` / `p.screen.*` / `p.channel_session.*` / `p.launch_session.*`），
# 门面上不再有第二条访问路径；`FacadeShrinkTests` 钉住删掉的那些取不到。
DATA = frozenset({
    "BACK_LABELS", "BOX", "CLOSE", "SEARCH_ACTION",
    "H", "W",
    "app", "changed", "lost", "miss", "missed", "safe_mode",
})

# 脚本访问面的快照：`recipes/` 里出现过 `p.<名字>` 的 37 个唯一名字。新增或去掉一个名字都要
# 在这里显式改一行——这正是「脚本访问面变了」。每个名字还必须是门面真实成员，见下面那条守卫。
# `lost` 已不在快照里：读它的是注入面的 `opened()`（#1148），脚本源码不再出现 `p.lost`；
# `say` 同理，随广告跟踪段搬进 `recipe_steps`（沿用 #1213）。`page_text` 也是这一类：读它的是
# `recipe_nav` 里 `tap` 的 exact 档（#1245），脚本本地那份已删。门面是否还提供它们由成员守卫盯：
# `lost` 在 `DATA`，`say` / `page_text` 在 `METHODS`。
# `app` 同样如此：写它的是 `recipe_lib/honor.py` 的 `launch`（沿用 #1370 的落点），它仍在 `DATA`。
# `miss` 也是这一类：`p.miss = 0` 随 PNM-AN10 的广告跟踪段搬进数据的 `miss_reset` op（#1372），
# 写入落在解释器里，`miss` 仍在 `DATA`。
# `screen` 来自 catalog 数据的 `scoped` op 降级出的那一行（`p.screen.systemui_text = …`，
# 写的是协作者而不是门面）；真实 `recipes/**/*.py` 里没有 `p.screen`，脚本面守卫只扫真实文件。
SCRIPT_NAMES = frozenset({
    "await_page", "back", "changed", "click", "confirm", "dismiss", "enter",
    "entry", "expect_page", "find", "focus", "go", "H", "has_text", "in_settings_page",
    "locked", "note_miss", "off", "on_screen", "page_evidence",
    "press", "safe_mode", "screen", "scroll", "scroll_more", "setting", "shell", "settle", "sig",
    "start", "swipe", "switches", "tab", "tap", "tap_icon",
    "tap_id_if_present", "texts", "top", "tree", "W", "window_size",
})

# 今天每一条公开成员都可写。脚本确实这样用的有 4 个：`honor-WKL-AN20` 把
# `p.click` / `p.scroll` / `p.confirm` / `p.switches` 换成本地读法，
# `p.changed.append(...)` 直接改集合本体。`p.app` 随 CLE-AN00 的浏览器 / 主题搬进
# `recipe_lib/honor.py` 的 `launch`（沿用 #1370 的落点），`p.miss = 0` 随 PNM-AN10 的广告跟踪段搬进
# 数据的 `miss_reset` op（#1372），都不再是脚本侧的写入。
# 其中任何一条变成只读属性即红——只读转发会让脚本静默失效。
WRITTEN_BY_SCRIPTS = frozenset({"click", "scroll", "confirm", "switches"})


def facade():
    """造一台不连手机的门面：装配仍走 `phone_stub()` 这一处，读屏替身落 `conn.reader`。"""
    phone = phone_stub(W=1080, H=2340)
    phone.conn.reader = Mock(name="reader")
    return phone


def public_functions(cls):
    return {name for name, value in vars(cls).items()
            if not name.startswith("_") and inspect.isfunction(value)}


def assign(phone, name):
    """把当前值写回去再读回来：挡住只读属性，以及写完读回不是同一值（存进拷贝、写了又规范化）。

    值本来就相同的「吞掉写入」这条测不出来；写到门面上不存在的名字同样会通过，那条由
    `RecipeWriteTests` 挡。
    """
    value = getattr(phone, name, None)
    setattr(phone, name, value)
    return value


def recipe_trees():
    """`recipes/` 下每份脚本的 (相对路径, 语法树)。catalog 的 `.toml` 先降成等价源码再解析（#1263）。"""
    for path in sorted(RECIPES.rglob("*.py")):
        yield str(path.relative_to(ROOT)), ast.parse(path.read_text(encoding="utf-8"))
    import tomllib
    import recipe_source
    for path in sorted(RECIPES.rglob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        src = recipe_source._catalog_src(data)
        yield str(path.relative_to(ROOT)), ast.parse(src)


def recipe_accesses():
    """`recipes/` 里 `p.<名字>` 的读取与写入：{名字: [位置, …]}，位置取到文件行。"""
    reads, writes = {}, {}
    for name, tree in recipe_trees():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "p"):
                continue
            bucket = writes if isinstance(node.ctx, (ast.Store, ast.Del)) else reads
            bucket.setdefault(node.attr, []).append(f"{name}:{node.lineno}")
    return reads, writes


def recipe_imports():
    """`from fast import …` 用到的模块级名字。"""
    names = {}
    for name, tree in recipe_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fast":
                for alias in node.names:
                    names.setdefault(alias.name, []).append(name)
    return names


class FacadeSurfaceTests(unittest.TestCase):
    """旧树也绿，守的是不回退：门面公开成员的名字、形状与可赋值性在七步搬迁里不变。"""

    def test_no_reflective_forwarding(self):
        """搬漏的方法必须当场 AttributeError；`__getattr__` 会把搬漏静默吃掉，也让下面几条失效。"""
        self.assertNotIn("__getattr__", vars(fast.Phone), "门面上出现了反射兜底（ADR-0033）")

    def test_public_methods_stay_methods(self):
        missing = sorted(METHODS - public_functions(fast.Phone))
        self.assertEqual(missing, [], "这些公开方法不在类上了，脚本与 tool/ 会 AttributeError："
                                      + "、".join(missing))

    def test_public_data_stays_on_the_instance(self):
        phone = facade()
        missing = sorted(name for name in DATA if not hasattr(phone, name))
        self.assertEqual(missing, [], "这些公开数据取不到了：" + "、".join(missing))
        flattened = sorted(name for name in DATA if name in public_functions(fast.Phone))
        self.assertEqual(flattened, [], "这些数据变成了方法：" + "、".join(flattened))

    def test_every_public_member_is_writable(self):
        phone = facade()
        readonly = []
        for name in sorted(METHODS | DATA):
            with self.subTest(member=name):
                try:
                    value = assign(phone, name)
                except AttributeError as error:
                    readonly.append(f"{name}（{error}）")
                    continue
                self.assertEqual(getattr(phone, name), value, f"{name} 写进去又读回来变了")
        self.assertEqual(readonly, [], "这些公开成员变成只读了，脚本写不动：\n" + "\n".join(readonly))

    def test_constructor_keeps_its_signature(self):
        """`Phone(serial, log=…, reader=…)` 是读屏替身的注入点（#1038 只把它往下传一层）。"""
        self.assertEqual(tuple(inspect.signature(fast.Phone).parameters),
                         ("serial", "log", "reader"))

    def test_the_members_scripts_write_are_part_of_the_surface(self):
        """守卫本身不能空转：脚本真在写的名字必须还在快照里。"""
        self.assertLessEqual(WRITTEN_BY_SCRIPTS, METHODS | DATA)


class FacadeShrinkTests(unittest.TestCase):
    """门面只剩「这台手机」的概念（ADR-0045、#1479）。

    留的 8 个设备概念属性仍可读写；删掉的 12 组内部状态在门面上取不到、也写不进去。
    写不进去这一半同样重要：留着赋值器，读侧就还是有第二条访问路径。
    """

    KEPT = ("W", "H", "changed", "safe_mode", "miss", "missed", "lost", "app")
    GONE = ("d", "reader", "link", "log", "serial", "pause_at_lock_check", "systemui_text",
            "vivo_seen", "skeleton_sigs", "skeleton_count", "mismatch_probes", "promoted")

    def test_the_eight_device_concepts_are_still_readable_and_writable(self):
        phone = facade()
        for name in self.KEPT:
            with self.subTest(name=name):
                value = getattr(phone, name)
                setattr(phone, name, value)
                self.assertEqual(getattr(phone, name), value)

    def test_the_twelve_internal_states_are_gone(self):
        phone = facade()
        for name in self.GONE:
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    getattr(phone, name)

    def test_the_state_moved_to_its_collaborator(self):
        """删掉不等于丢：状态还在持有它的协作者上，门面留下的那几个读的是同一份。"""
        phone = facade()
        self.assertEqual(phone.W, phone.screen.W)
        self.assertEqual(phone.H, phone.screen.H)
        self.assertEqual(phone.miss, phone.lost_note.miss)
        self.assertIs(phone.missed, phone.lost_note.missed)
        self.assertEqual(phone.app, phone.launch_session.app)
        self.assertFalse(phone.screen.systemui_text)
        self.assertFalse(phone.channel_session.vivo_seen)
        self.assertEqual(phone.channel_session.skeleton_count, 0)
        self.assertIsNotNone(phone.conn.reader)


class RecipeAccessTests(unittest.TestCase):
    """旧树也绿，守的是不回退：`recipes/` 现在怎么用门面，搬迁期间必须照旧。"""

    def test_the_surface_matches_the_snapshot(self):
        """41 个名字的快照：脚本侧少用一个、多用一个新名字，都要回来显式改这一行。"""
        reads, writes = recipe_accesses()
        self.assertEqual(set(reads) | set(writes), set(SCRIPT_NAMES))

    def test_reads_resolve_on_the_facade(self):
        reads, _ = recipe_accesses()
        phone = facade()
        broken = [f"{name}（{sites[0]} 等 {len(sites)} 处）"
                  for name, sites in sorted(reads.items()) if not hasattr(phone, name)]
        self.assertEqual(broken, [], "脚本读的名字从门面上消失了：\n" + "\n".join(broken))

    def test_writes_still_take(self):
        _, writes = recipe_accesses()
        self.assertLessEqual(WRITTEN_BY_SCRIPTS, set(writes),
                             "脚本不再写这些名字了，守卫的前提变了，回来核一遍快照")
        phone = facade()
        broken = []
        for name, sites in sorted(writes.items()):
            with self.subTest(name=name):
                try:
                    value = assign(phone, name)
                except AttributeError as error:
                    broken.append(f"{name}（{sites[0]}）：{error}")
                    continue
                self.assertEqual(getattr(phone, name), value, f"{name} 写进去又读回来变了")
        self.assertEqual(broken, [], "脚本写不进去了：\n" + "\n".join(broken))

    def test_collections_stay_live(self):
        """`p.changed.append(...)` 改的是门面持有的那一个集合，不是副本。"""
        reads, _ = recipe_accesses()
        phone = facade()
        mutable = {name for name in reads if isinstance(getattr(phone, name, None), (list, set, dict))}
        self.assertTrue(mutable, "脚本读的集合名一个都没认出来，这条守卫会空转")
        for name in sorted(mutable):
            with self.subTest(name=name):
                live = getattr(phone, name)
                self.assertIs(live, getattr(phone, name), f"{name} 每次读回来都是新的拷贝")
                sentinel = "__facade_guard__"
                if isinstance(live, dict):
                    live[sentinel] = None
                    self.assertIn(sentinel, getattr(phone, name), f"{name} 改副本不影响门面")
                else:
                    live.append(sentinel) if isinstance(live, list) else live.add(sentinel)
                    self.assertIn(sentinel, getattr(phone, name), f"{name} 改副本不影响门面")

    def test_module_exports_stay_importable(self):
        names = recipe_imports()
        self.assertTrue(names, "脚本里没扫到 `from fast import …`，守卫会空转")
        missing = sorted(name for name in names if not hasattr(fast, name))
        self.assertEqual(missing, [], "脚本 import 的模块级名字没了：" + "、".join(missing))


class RecordingSelection:
    """u2 选择器的替身：记选择器、下标与动作，`click_exists` 按 `present` 回真假。"""

    def __init__(self, reader, selector):
        self.reader, self.selector = reader, selector
        self.index = None

    def __getitem__(self, index):
        self.index = index
        self.reader.indexes.append(index)
        return self

    def click(self, timeout=None):
        self.reader.clicks.append((self.selector, self.index, timeout))

    def click_exists(self, timeout=0):
        self.reader.existence_checks.append((self.selector, timeout))
        return self.reader.present

    def set_text(self, text, timeout=None):
        self.reader.typed.append((self.selector, text))


class RecordingReader:
    """读屏替身：记下发过什么，`shell` 返回一段固定输出。#1472 的门面动词只经它观察。"""

    def __init__(self, output="probe", size=(1080, 2340), present=True):
        self.output, self.size, self.present = output, size, present
        self.shells = []       # [(命令, timeout)]
        self.swipes = []       # [((x1, y1, x2, y2), {关键字})]
        self.presses = []      # [键名]
        self.stops = []        # [包名]
        self.size_reads = 0
        self.selectors = []    # [选择器]：`reader(**选择器)` 收到了什么
        self.clicks = []       # [(选择器, 下标, timeout)]
        self.indexes = []      # [下标]
        self.existence_checks = []   # [(选择器, timeout)]
        self.typed = []        # [(选择器, 值)]

    def __call__(self, **selectors):
        self.selectors.append(selectors)
        return RecordingSelection(self, selectors)

    def shell(self, command, timeout=None):
        self.shells.append((command, timeout))
        return SimpleNamespace(output=self.output, exit_code=0)

    def swipe(self, x1, y1, x2, y2, **kwargs):
        self.swipes.append(((x1, y1, x2, y2), kwargs))

    def press(self, key):
        self.presses.append(key)

    def app_stop(self, package):
        self.stops.append(package)

    def window_size(self):
        self.size_reads += 1
        return self.size


def verb_phone(**fields):
    """带记录读屏的门面：装配仍走 `phone_stub()`，只把读屏换成会记账的那一份。"""
    reader = RecordingReader()
    return phone_stub(W=1080, H=2340, reader=reader, **fields), reader


class DeviceVerbTests(unittest.TestCase):
    """设备动词（#1472）：门面上多出五个动作，下发到手机的仍是原来那条路。"""

    def test_shell_returns_the_command_output(self):
        phone, reader = verb_phone()
        self.assertEqual(phone.shell("getprop ro.product.model"), "probe")
        self.assertEqual(reader.shells, [("getprop ro.product.model", None)])

    def test_shell_passes_the_timeout_through(self):
        phone, reader = verb_phone()
        phone.shell("dumpsys notification --noredact", timeout=60)
        self.assertEqual(reader.shells, [("dumpsys notification --noredact", 60)])

    def test_home_sends_one_home_keyevent(self):
        phone, reader = verb_phone()
        phone.home()
        self.assertEqual(reader.shells, [("input keyevent HOME", None)])

    def test_window_size_reads_the_size_and_returns_a_tuple(self):
        phone, reader = verb_phone()
        reader.size = [1200, 2600]
        self.assertEqual(phone.window_size(), (1200, 2600))

    def test_swipe_keeps_the_uiautomator2_path(self):
        """绝对坐标手势走 u2 的 swipe，**不是** `input swipe`：两条下发路径实测不等价。"""
        phone, reader = verb_phone()
        phone.swipe(100, 200, 300, 400, 450)
        self.assertEqual(reader.swipes, [((100, 200, 300, 400), {"duration": 0.45})])
        self.assertEqual(reader.shells, [], "swipe 不该退回 `input swipe` 那条路")

    def test_press_keeps_the_uiautomator2_path(self):
        """按一个键走 u2 的 `press`（jsonrpc `pressKey`），**不是** `input keyevent`：两条不同路。"""
        phone, reader = verb_phone()
        phone.press("home")
        self.assertEqual(reader.presses, ["home"])
        self.assertEqual(reader.shells, [], "press 不该退回 `input keyevent` 那条路")

    def test_switches_raw_ignores_a_wrapper_installed_on_the_instance(self):
        """自绘页的读法：段内包装器装在实例的 `switches` 上，`switches_raw` 仍走引擎自己那份。"""
        phone = facade()
        phone.screen.switches = Mock(return_value=[("自绘开关", True, (900, 425))])
        phone.switches = Mock(return_value=[])
        self.assertEqual(phone.switches_raw(), [("自绘开关", True, (900, 425))])
        self.assertEqual(phone.switches(), [])

    def test_app_stop_keeps_the_uiautomator2_path(self):
        """强停走 u2 的 `app_stop`，**不是** `am force-stop` 串：`_u2` 还负责断线记账。"""
        phone, reader = verb_phone()
        phone.app_stop("com.android.browser")
        self.assertEqual(reader.stops, ["com.android.browser"])
        self.assertEqual(reader.shells, [], "app_stop 不该退回 `am force-stop` 那条路")

    def test_tap_id_clicks_the_first_match_without_an_instance_key(self):
        """`p.d(resourceId=X).click()` 的等价物：选择器里不出现空键，也不带 instance。"""
        phone, reader = verb_phone()
        phone.tap_id("com.honor.browser:id/menu_btn")
        self.assertEqual(reader.selectors, [{"resourceId": "com.honor.browser:id/menu_btn"}])
        self.assertEqual(reader.clicks, [({"resourceId": "com.honor.browser:id/menu_btn"}, None, None)])
        self.assertEqual(reader.indexes, [], "默认档不该往选择器上加 instance")

    def test_tap_id_index_picks_the_nth_match(self):
        """`p.d(resourceId=X)[2].click()` 的等价物：下标原样落到 u2 选择器上。"""
        phone, reader = verb_phone()
        phone.tap_id("com.honor.browser:id/top_local_icon", index=2)
        self.assertEqual(reader.indexes, [2])

    def test_tap_id_accepts_a_text_selector_alone(self):
        """数据里的 `tap_id` op 两种选择器都要能表达：只给文字时不塞空的 resourceId。"""
        phone, reader = verb_phone()
        phone.tap_id(text="确定")
        self.assertEqual(reader.selectors, [{"text": "确定"}])

    def test_tap_id_if_present_returns_true_when_it_lands(self):
        phone, reader = verb_phone()
        self.assertTrue(phone.tap_id_if_present("com.android.settings:id/vigour_search_edit", timeout=3))
        self.assertEqual(reader.existence_checks,
                         [({"resourceId": "com.android.settings:id/vigour_search_edit"}, 3)])

    def test_tap_id_if_present_returns_false_instead_of_raising(self):
        """`p.d(...).click_exists(timeout=3)` 的语义：没点到是 False，不是异常。"""
        phone, reader = verb_phone()
        reader.present = False
        self.assertFalse(phone.tap_id_if_present("com.honor.browser:id/menu_btn", timeout=3))

    def test_set_text_writes_through_uiautomator2(self):
        """`p.d(resourceId=X).set_text(v)` 的等价物：u2 原方法，不是 `input text` 串。"""
        phone, reader = verb_phone()
        phone.set_text("com.android.settings:id/vigour_search_edit", "广告")
        self.assertEqual(reader.typed,
                         [({"resourceId": "com.android.settings:id/vigour_search_edit"}, "广告")])
        self.assertEqual(reader.shells, [], "set_text 不该退回 shell 那条路")

    def back_phone(self):
        """`back()` 读屏与等待都桩在观测基座上（`phone_stub` 的约定），只留下发的命令可观察。"""
        phone, reader = verb_phone()
        calls = []
        phone.screen.sig = lambda: calls.append("sig") or "sig"
        phone.screen.settle = lambda before, maxwait=0.8: calls.append(("settle", before, maxwait)) or True
        return phone, reader, calls

    def test_back_alone_keeps_the_old_sequence(self):
        phone, reader, calls = self.back_phone()
        phone.back()
        self.assertEqual(calls, ["sig", ("settle", "sig", 0.6)])
        self.assertEqual(reader.shells, [("input keyevent BACK", None)])

    def test_back_without_settle_sends_only_the_keyevent(self):
        """`settle=False`：只发一次 keyevent，不额外读屏、不额外等（WKL-AN20 的原语义）。"""
        phone, reader, calls = self.back_phone()
        phone.back(settle=False)
        self.assertEqual(calls, [])
        self.assertEqual(reader.shells, [("input keyevent BACK", None)])

    def test_back_repeats_n_times(self):
        phone, reader, _ = self.back_phone()
        phone.back(2, settle=False)
        self.assertEqual(reader.shells, [("input keyevent BACK", None)] * 2)


class RecipeWriteTests(unittest.TestCase):
    """#1047：脚本写一个门面上不存在的名字不会报错，只在实例上挂个没人读的死属性。

    这不是回退守卫——`vivo-V1986A` 的 `p.sysui` 就写在旧树里，所以本类在旧树上红，
    是条新增行为。
    """

    def test_writes_target_real_members(self):
        _, writes = recipe_accesses()
        self.assertTrue(writes, "脚本里没扫到 `p.<名字>` 的写，守卫会空转")
        phone = facade()
        missing = sorted(name for name in writes if not hasattr(phone, name))
        self.assertEqual(missing, [], "脚本写了门面上不存在的名字，写了也不会报错："
                                     + "、".join(missing))


@contextlib.contextmanager
def _script_tree(files):
    """临时目录里造一份最小脚本树：{相对路径: 源码}，用来给守卫喂反例。"""
    with tempfile.TemporaryDirectory() as tmp:
        for rel, text in files.items():
            path = Path(tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        yield Path(tmp)


class ScriptSurfaceTests(unittest.TestCase):
    """rule:dev.phone.script-surface（#1477）：脚本面是一份明写的集合。

    病因是同一个动作两条访问路径：`p.d.click` 与 `Screen.click` 是一件事的两条路，一条有尺寸 /
    越界守卫、一条没有，WKL-AN20 因此走了另一条。只修最响的那一条，同构的泄漏半年后还会长出来
    ——所以钉的是「脚本能碰的名字」这份声明本身（`tool/phone/surface.py` 的 `SCRIPT_SURFACE`）。

    声明是单一来源：本类只做对账，名单不在这里再抄一份。
    """

    def test_the_real_tree_only_uses_declared_names(self):
        self.assertTrue(script_surface.script_files(ROOT), "没扫到脚本，守卫会空转")
        found = script_surface.violations(ROOT)
        self.assertEqual(
            found, [],
            "脚本碰了声明外的门面名字（`tool/phone/surface.py` 的 `SCRIPT_SURFACE`）：\n"
            + "\n".join(f"{path}:{line}  p.{name}" for path, line, name in found))

    def test_every_declared_name_is_a_real_facade_member(self):
        """拼错名字会让守卫形同虚设：声明里每个名字都得是门面上真有的成员。"""
        phone = facade()
        missing = sorted(name for name in script_surface.SCRIPT_SURFACE if not hasattr(phone, name))
        self.assertEqual(missing, [], "声明里有门面上不存在的名字："
                                     + "、".join(missing))

    def test_an_undeclared_name_is_reported_with_its_location(self):
        with _script_tree({"recipes/honor/X1/X1.py": "def step(p, rt):\n    p.serial.strip()\n"}) as root:
            found = script_surface.violations(root)
        self.assertEqual(found, [("recipes/honor/X1/X1.py", 2, "serial")])

    def test_the_library_layer_is_scanned_too(self):
        with _script_tree({"recipe_lib/honor.py": "def go(p):\n    p.d.click(1, 2)\n"}) as root:
            found = script_surface.violations(root)
        self.assertEqual(found, [("recipe_lib/honor.py", 2, "d")])

    def test_writes_are_scanned_as_well(self):
        with _script_tree({"recipe_lib/honor.py": "def go(p):\n    p.vivo_seen = True\n"}) as root:
            found = script_surface.violations(root)
        self.assertEqual(found, [("recipe_lib/honor.py", 2, "vivo_seen")])


if __name__ == "__main__":
    unittest.main()
