"""失败现场落盘：这一屏的 dump 原文存进客户端的 `captures/`，事后不必再要一台设备就能回放（#1126）。

捕获点就是既有的两处「留现场」——`note_miss()` 与 `page_evidence()`——不另找地方，调用方一行都不用改。
它们只记下那一屏，段包装在段真的失败时才落盘：入口探路同样走 `note_miss()`（`entry()` 找不到可选入口
只返回假），那种跑不该留下「失败现场」。
两态都钉住：给了捕获目录就在 `<任务>-<段>/` 下留一份那一屏的原文，不给就一个字节都不写。
"""
import contextlib
import datetime
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
    phone = fixtures.phone_stub("test", fast_mod=fast_mod, W=1080, H=2340, reader=Mock(name="reader"))
    phone.locked = lambda: False
    phone.screen.focus = lambda: "com.android.settings/.Settings"
    phone.screen.tree = lambda: ET.fromstring(PAGE)
    phone.screen.dump = PAGE
    phone.screen.captures = store
    import recipe_runtime
    rt = recipe_runtime.Runtime(phone, [])
    rt.namespace = {}
    scope = {"p": phone, "rt": rt, "ONLY": rt.only}

    def 段体():
        body(phone)

    with contextlib.redirect_stdout(io.StringIO()):
        scope["rt"].run_step(name, 段体)
    return phone


class SlugTests(unittest.TestCase):
    """目录名的一段：路径分隔符与控制字符替换掉，首尾的空格 / 点剥掉，空串落到 `-`。"""

    def test_path_separators_and_control_characters_become_underscores(self):
        self.assertEqual(captures.slug("主题 子\n/页"), "主题 子__页")

    def test_leading_and_trailing_spaces_and_dots_are_stripped(self):
        # 只剥空格与点：名字里的 X 原样保留（路径末尾的点在 Windows 上会被吃掉）
        self.assertEqual(captures.slug(" .名字X. "), "名字X")

    def test_an_empty_name_falls_back_to_a_dash(self):
        self.assertEqual(captures.slug(""), "-")
        self.assertEqual(captures.slug(" . "), "-")


class HumanSizeTests(unittest.TestCase):
    """体积给人看：B 取整、KB / MB 一位小数、超过 MB 的落回最后一个单位。"""

    def test_bytes_are_whole_numbers_with_an_upper_b_unit(self):
        self.assertEqual(captures.human_size(512), "512 B")
        self.assertEqual(captures.human_size(1023), "1023 B")

    def test_a_kilobyte_is_where_the_unit_changes(self):
        self.assertEqual(captures.human_size(1024), "1.0 KB")

    def test_a_megabyte_is_not_divided_a_second_time(self):
        self.assertEqual(captures.human_size(1024 * 1024), "1.0 MB")

    def test_megabytes_are_three_million_byte_scale(self):
        self.assertEqual(captures.human_size(3 * 1024 * 1024), "3.0 MB")

    def test_gigabytes_fall_back_to_the_last_unit(self):
        self.assertEqual(captures.human_size(2 * 1024 ** 3), "2.0 GB")


class CapturesDefaultsTests(unittest.TestCase):
    def test_a_store_starts_without_a_task_or_step(self):
        store = captures.Captures("/tmp/root")
        self.assertEqual((store.task, store.step), ("", ""))


class SaveTests(unittest.TestCase):
    """`save()` 直接落盘：空页面不建目录、同段重跑覆盖、meta 的形状固定。"""

    def setUp(self):
        self.root = self.enterContext(tempfile.TemporaryDirectory())
        self.store = captures.Captures(self.root)
        self.store.task, self.store.step = "recipe", "主题"

    @property
    def folder(self):
        return Path(self.root, "recipe-主题")

    def test_an_empty_page_is_not_saved(self):
        self.assertIsNone(self.store.save(""))
        self.assertEqual(list(Path(self.root).iterdir()), [])

    def test_the_meta_defaults_to_a_zero_size(self):
        self.store.save("<x/>")
        meta = json.loads((self.folder / captures.META).read_text(encoding="utf-8"))
        self.assertEqual((meta["w"], meta["h"]), (0, 0))

    def test_the_timestamp_is_second_precision_iso(self):
        self.store.save("<x/>", when=datetime.datetime(2026, 1, 2, 3, 4, 5))
        meta = json.loads((self.folder / captures.META).read_text(encoding="utf-8"))
        self.assertEqual(meta["at"], "2026-01-02T03:04:05")

    def test_saving_the_same_step_again_overwrites_the_folder(self):
        # `exist_ok=False` 时第二次保存会抛 FileExistsError、被当成写不进去，现场就丢了
        self.assertEqual(self.store.save("<a/>"), str(self.folder))
        self.assertEqual(self.store.save("<b/>"), str(self.folder))
        self.assertEqual((self.folder / captures.PAGE).read_text(encoding="utf-8"), "<b/>")

    def test_the_page_is_raw_utf8_and_the_meta_is_readable_json(self):
        page = '<node text="营销通知"/>'
        self.store.save(page)
        self.assertEqual((self.folder / captures.PAGE).read_bytes(), page.encode("utf-8"))
        meta_text = (self.folder / captures.META).read_text(encoding="utf-8")
        self.assertTrue(meta_text.startswith('{\n "w": 0,'), meta_text)
        self.assertIn('"task": "recipe"', meta_text)
        self.assertIn('"step": "主题"', meta_text)      # ensure_ascii=False：中文原样，不转 \uXXXX


class UsageTests(unittest.TestCase):
    """体积统计：文件数与总字节数；读不动的条目跳过但不拦后面的。"""

    def test_files_are_counted_and_sized(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        Path(root, "a").write_bytes(b"x" * 10)
        Path(root, "b").write_bytes(b"y" * 5)
        self.assertEqual(captures.Captures(root).usage(), (2, 15))

    def test_an_unreadable_entry_is_skipped_and_the_rest_is_still_counted(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "a").write_bytes(b"x" * 3)
        (root / "broken").symlink_to(root / "missing")     # getsize 抛 OSError
        (root / "b").write_bytes(b"y" * 4)
        self.assertEqual(captures.Captures(str(root)).usage(), (2, 7))


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
        import recipe_runtime
        rt = recipe_runtime.Runtime(phone, [])
        rt.namespace = {}
        scope = {"p": phone, "rt": rt, "ONLY": rt.only}
        def body():
            return None

        with contextlib.redirect_stdout(io.StringIO()):
            scope["rt"].run_step("主题", body)
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
