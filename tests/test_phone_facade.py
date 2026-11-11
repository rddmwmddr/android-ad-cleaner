"""`Phone` 拆成门面 + 两个基座 + 五个阶段期间，两条对外契约必须有人钉住（ADR-0033、#1037）。

门面守卫：公开成员的名字、是方法还是数据、能不能被赋值，逐条快照。少一个名字、把方法改成数据、
或把可写字段改成只读，都会在真机上炸，而不是在评审里被发现。

脚本访问面守卫：`recipes/` 里 `p.<名字>` 的读取必须仍然取得得到，写入必须仍然赋得进去并读得回来，
集合类字段必须仍是活对象（`p.changed.append(...)` 与 `p.promoted.clear()` 直接改它，转发成拷贝
只会静默失效），`from fast import …` 的模块级名字也必须仍可 import。

两条都只钉对外契约，钉不到七个模块之间的内部分工——那由代码结构与评审保证。

这些用例在拆分前的旧树上也全绿：守的是不回退（七步搬迁期间门面公开面与脚本访问面零变化），
不是新增行为。
"""
import ast
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from fixtures import phone_stub  # noqa: E402

RECIPES = ROOT / "recipes"

# 门面的公开方法：类上定义的函数，今天 45 个。方法变成数据（例如搬成实例上绑定的函数）也算红：
# 脚本会把 `p.click` / `p.switches` 换成本地读法，形状变了就不是同一个门面。
METHODS = frozenset({
    "await_page", "back", "check_alive", "click",
    "close", "confirm", "dismiss", "edit_ready",
    "enter", "entry", "expect_hits", "expect_page",
    "find", "focus", "focused_text", "go",
    "has_text", "icon_candidates", "in_settings_page", "locked",
    "ls", "note_miss", "off", "on_screen",
    "page_evidence", "page_text", "residual_confirm", "residual_note",
    "say", "scroll", "scroll_more", "setting",
    "settle", "sig", "start", "switch_rows",
    "switches", "tab", "tap", "tap_icon",
    "texts", "top", "tree", "type_text",
    "wait_unlocked",
})

# 公开数据：3 个读写属性（`d` / `serial` / `lost`）、4 个类常量、17 个实例字段，今天 24 个。
# 拆分时它们可以变成属性，但不能消失、不能变成方法。
DATA = frozenset({
    "BACK_LABELS", "BOX", "CLOSE", "SEARCH_ACTION",
    "H", "W",
    "app", "changed", "d", "link", "log", "lost", "miss", "missed",
    "mismatch_probes", "pause_at_lock_check", "promoted", "reader",
    "safe_mode", "serial", "skeleton_count", "skeleton_sigs",
    "systemui_text", "vivo_seen",
})

# 脚本访问面的快照：`recipes/` 里出现过 `p.<名字>` 的 43 个唯一名字（`sysui` 是 `vivo-V1986A`
# 那三行从未生效的写，票面另开，仍算在访问面里）。今天共 3210 次访问（AST 口径；把正文与注释里
# 提到的写法也算上是 3261）。新增或去掉一个名字都要在这里显式改一行——这正是「脚本访问面变了」。
SCRIPT_NAMES = frozenset({
    "app", "await_page", "back", "changed", "click", "confirm", "d", "dismiss", "enter",
    "entry", "expect_page", "find", "focus", "go", "H", "has_text", "in_settings_page",
    "locked", "lost", "miss", "note_miss", "off", "on_screen", "page_evidence", "page_text",
    "promoted", "safe_mode", "say", "scroll", "scroll_more", "setting", "settle", "sig",
    "start", "switches", "sysui", "tab", "tap", "tap_icon", "texts", "top", "tree", "W",
})

# 今天每一条公开成员都可写。脚本确实这样用的有 6 个：`p.miss = 0`、`p.app = pkg`，
# 以及 `honor-WKL-AN20` 把 `p.click` / `p.scroll` / `p.confirm` / `p.switches` 换成本地读法；
# `p.promoted.clear()` 与 `p.changed.append(...)` 直接改集合本体。
# 其中任何一条变成只读属性即红——只读转发会让脚本静默失效。
WRITTEN_BY_SCRIPTS = frozenset({"miss", "app", "click", "scroll", "confirm", "switches"})


def facade():
    """造一台不连手机的门面：装配仍走 `phone_stub()` 这一处。"""
    return phone_stub(W=1080, H=2340, d=Mock(name="reader"))


def public_functions(cls):
    return {name for name, value in vars(cls).items()
            if not name.startswith("_") and inspect.isfunction(value)}


def assign(phone, name):
    """把当前值写回去再读回来：挡住只读属性，以及写完读回不是同一值（存进拷贝、写了又规范化）。

    值本来就相同的「吞掉写入」这条测不出来，所以 `p.sysui` 那种死属性仍算通过。
    """
    value = getattr(phone, name, None)
    setattr(phone, name, value)
    return value


def recipe_trees():
    """`recipes/` 下每份脚本的 (相对路径, 语法树)。"""
    for path in sorted(RECIPES.rglob("*.py")):
        yield str(path.relative_to(ROOT)), ast.parse(path.read_text(encoding="utf-8"))


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


class RecipeAccessTests(unittest.TestCase):
    """旧树也绿，守的是不回退：`recipes/` 现在怎么用门面，搬迁期间必须照旧。"""

    def test_the_surface_matches_the_snapshot(self):
        """43 个名字的快照：脚本侧少用一个、多用一个新名字，都要回来显式改这一行。"""
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
        """`p.changed.append(...)` / `p.promoted.clear()` 改的是门面持有的那一个集合，不是副本。"""
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


if __name__ == "__main__":
    unittest.main()
