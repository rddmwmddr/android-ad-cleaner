"""失败现场落盘：这一屏的 dump 原文存进客户端的 `captures/`，事后不必再要一台设备就能回放（#1126）。

捕获点就是既有的两处「留现场」——`note_miss()` 与 `page_evidence()`——不另找地方，调用方一行都不用改。
它们只记下那一屏，段包装在段真的失败时才落盘：入口探路同样走 `note_miss()`（`entry()` 找不到可选入口
只返回假），那种跑不该留下「失败现场」。
两态都钉住：给了捕获目录就在 `<任务>-<段>/` 下留一份那一屏的原文，不给就一个字节都不写。
"""
import contextlib
import io
import json
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import captures  # noqa: E402
import fixtures  # noqa: E402
import run  # noqa: E402


PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
    <node text="个性化广告推荐" bounds="[60,600][700,660]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,600][1040,660]"/>
    <node text="隐私" bounds="[60,900][400,960]"/>
  </node>
</hierarchy>"""


def fast_module():
    fixtures.load_tool()
    import fast
    return fast


def base(fast_mod, size=(1080, 2340), page=PAGE):
    """真观测基座 + 假设备：读屏返回给定页面。"""
    clock = fixtures.Clock()
    device = fixtures.Device(fixtures.Timeline([(0.0, page)]), size, clock)
    return fast_mod.Screen(fast_mod.Connection("test", log=False, reader=device))


def run_step(fast_mod, store, body, name="主题"):
    """跑一段机型脚本的段体：装配走 `phone_stub()`，段包装是真的（`preamble` + `step`）。

    `body(p)` 决定这一段是失败（自己抛）还是走完；失败现场归 `store` 管，段名由 `step()` 设。"""
    phone = fixtures.phone_stub("test", fast_mod=fast_mod, W=1080, H=2340, d=Mock(name="reader"))
    phone.locked = lambda: False
    phone.screen.focus = lambda: "com.android.settings/.Settings"
    phone.screen.tree = lambda: ET.fromstring(PAGE)
    phone.screen.dump = PAGE
    phone.screen.captures = store
    scope = {"p": phone, "ONLY": []}
    fast_mod.recipe_kit.preamble(phone, scope)

    with contextlib.redirect_stdout(io.StringIO()):
        @scope["step"](name)
        def 段体():
            body(phone)
    return phone


class CaptureTests(unittest.TestCase):
    """两处捕获点各写一份原文；归档名由任务与段决定。"""

    def setUp(self):
        self.fast = fast_module()

    def test_page_evidence_saves_the_dump_of_that_screen(self):
        """点名要关的开关没找到、这一段失败：留下的是失败时那一屏的 dump 原文，不是一句摘要。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = captures.Captures(tmp)
            store.task, store.step = "recipe", "主题"

            def body(phone):
                phone.page_evidence(["某开关"])
                raise RuntimeError("未识别全部目标开关")

            run_step(self.fast, store, body)
            folder = Path(tmp, "recipe-主题")
            self.assertEqual((folder / captures.PAGE).read_text(encoding="utf-8"), PAGE)
            meta = json.loads((folder / captures.META).read_text(encoding="utf-8"))
            self.assertEqual((meta["w"], meta["h"], meta["task"], meta["step"]),
                             (1080, 2340, "recipe", "主题"))

    def test_note_miss_saves_the_dump_of_that_screen(self):
        """入口没找到、这一段失败：同一个捕获点，同一份原文。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = captures.Captures(tmp)
            store.task, store.step = "recipe", "设置"

            def body(phone):
                phone.note_miss("设置")
                raise RuntimeError("没找到入口「设置」")

            run_step(self.fast, store, body, name="设置")
            self.assertEqual((Path(tmp, "recipe-设置") / captures.PAGE).read_text(encoding="utf-8"), PAGE)

    def test_a_probe_that_leaves_evidence_does_not_save(self):
        """入口探路也走 note_miss()，但段照常走完：成功的跑不建现场，也不盖掉上一轮真失败的。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = captures.Captures(tmp)
            store.task, store.step = "recipe", "主题"

            def body(phone):
                phone.note_miss("可选入口")      # `entry()` 找不到可选入口时就是这样，段继续

            run_step(self.fast, store, body)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_without_the_variable_nothing_is_written(self):
        """没有捕获目录就一个字节都不写：源码态直接跑 `tool/run.py` 不产生任何文件。"""
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AAC_CAPTURES", None)
            self.assertEqual(base(self.fast).captures.dir, "")

            store = captures.Captures("")
            store.task, store.step = "recipe", "主题"

            def body(phone):
                phone.note_miss("设置")
                raise RuntimeError("没找到入口「设置」")

            run_step(self.fast, store, body)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_the_reported_size_counts_the_saved_pages(self):
        """不自动清理：命令行报出当前占用体积，由人手动清。"""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, "recipe-主题")
            folder.mkdir()
            (folder / captures.PAGE).write_bytes(b"x" * 2048)
            out = io.StringIO()
            with patch.dict(os.environ, {"AAC_CAPTURES": tmp}), contextlib.redirect_stdout(out):
                rc = run.cmd_captures([])
            self.assertEqual(rc, 0)
            self.assertIn("1 份", out.getvalue())
            self.assertIn("2.0 KB", out.getvalue())

    def test_an_empty_folder_is_reported_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with patch.dict(os.environ, {"AAC_CAPTURES": tmp}), contextlib.redirect_stdout(out):
                rc = run.cmd_captures([])
            self.assertEqual(rc, 0)
            self.assertIn("没有失败现场", out.getvalue())


class CaptureLabelTests(unittest.TestCase):
    """归档名从哪儿来：任务由引擎入口设，段名由段包装设。"""

    def setUp(self):
        self.fast = fast_module()

    def test_the_task_name_comes_from_the_command(self):
        phone = fixtures.phone_stub("test", fast_mod=self.fast)
        phone.ls = lambda: None
        with patch.dict(os.environ, {"AAC_CAPTURES": ""}):
            self.fast.execute(phone, "ls", [])
        self.assertEqual(phone.screen.captures.task, "ls")

    def test_the_step_name_comes_from_the_section_wrapper(self):
        phone = fixtures.phone_stub("test", fast_mod=self.fast)
        phone.locked = lambda: False
        scope = {"p": phone, "ONLY": []}
        self.fast.recipe_kit.preamble(phone, scope)
        with contextlib.redirect_stdout(io.StringIO()):
            @scope["step"]("主题")
            def body():
                return None
        self.assertEqual(phone.screen.captures.step, "主题")

    def test_folder_name_drops_path_separators(self):
        """段名里带 `/` 不能让它跑出 captures/，Windows 认不得的字符也不能带进路径。"""
        store = captures.Captures("/tmp/root")
        store.task, store.step = "recipe", "主题/鸿蒙:设置"
        self.assertEqual(store.dir, os.path.join("/tmp/root", "recipe-主题_鸿蒙_设置"))


class CaptureChannelTests(unittest.TestCase):
    """两个宿主共用一条通道：客户端起子进程时把目录传下去，手机版的持久根不另建。"""

    def test_the_client_passes_the_captures_folder_to_the_engine(self):
        from gui import app
        self.assertEqual(app.child_env(None, "/tmp/backups", "/tmp/captures")["AAC_CAPTURES"],
                         "/tmp/captures")

    def test_the_captures_folder_sits_under_the_client_root(self):
        from gui import app
        self.assertEqual(app.ClientData("/tmp/data").captures, os.path.join("/tmp/data", "captures"))

    def test_the_root_comes_from_the_environment(self):
        with patch.dict(os.environ, {"AAC_CAPTURES": "/tmp/where"}):
            self.assertEqual(captures.root_from_env(), "/tmp/where")
        with patch.dict(os.environ, {"AAC_CAPTURES": ""}):
            self.assertFalse(captures.root_from_env())
