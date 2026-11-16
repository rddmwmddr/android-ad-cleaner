"""窗口桥契约与三块的责任边界（ADR-0011）。

窗口桥清单从改前的 `Api` 抄死：内部怎么拆都可以变，这些名字与参数不能变
（改前 22 个，之后新增的桥方法一并钉进 `BRIDGE`，别写死总数）。
三块之间不许互相点名，也不许 `self.<别的块>` 去读对方的状态。
"""
import ast
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui import app

ROOT = Path(__file__).resolve().parents[1]

BRIDGE = {
    "env": (),
    "latest_version": (),
    "check_update": (),
    "update_state": (),
    "download_update": ("source",),
    "cancel_update": (),
    "install_update": (),
    "devices": (),
    "harmony": ("action", "serial", "mode", "segments"),
    "usb_hint": (),
    "status": ("serial",),
    "chan_scan": ("serial",),
    "ui_check": ("serial",),
    "start": ("serial", "plan"),
    "poll": ("since",),
    "stop": (),
    "pause": (),
    "resume": (),
    "run_mode": (),
    "download_adb": (),
    "download_state": (),
    "adb_info": (),
    "pick_adb_file": (),
    "set_adb_path": ("text",),
    "clear_adb_path": (),
    "dev_off": ("serial",),
    "restore": ("serial", "what"),
    "diagnostics": (),
    "report_payload": (),
    "send_report": ("payload",),
    "copy_text": ("text",),
    "open_path": ("which",),
    "open_url": ("url",),
}

BLOCKS = ("AdbDownloader", "Reporter", "Dispatcher")
FORBIDDEN_IN = {
    "AdbDownloader": {"self.reporter", "self.dispatcher"},
    "Reporter": {"self.downloader", "self.dispatcher", "self.job"},
    "Dispatcher": {"self.downloader", "self.reporter"},
}


CLASS_FILES = {
    "Api": "app.py",
    "AdbDownloader": "adb.py",
    "Dispatcher": "dispatcher.py",
    "Reporter": "reporter.py",
}


def body_of(rel):
    return ast.parse((ROOT / "gui" / rel).read_text(encoding="utf-8")).body


def classes():
    """类名 → 它的 ClassDef。块搬出 `gui/app.py` 之后仍按这张表取，别去猜文件在哪。

    缺一个就报错：三条边界断言都以这三块为前提，静默少一块会让它们空转。
    """
    found = {}
    for name, rel in CLASS_FILES.items():
        node = next((node for node in body_of(rel) if isinstance(node, ast.ClassDef) and node.name == name), None)
        if node is None:
            raise AssertionError(f"gui/{rel} 里找不到类 {name}：这张表要跟着搬家一起改")
        found[name] = node
    return found


class BridgeTests(unittest.TestCase):
    def test_window_bridge_signatures_stay_put(self):
        for name, params in BRIDGE.items():
            with self.subTest(method=name):
                signature = inspect.signature(getattr(app.Api, name))
                self.assertEqual(tuple(p for p in signature.parameters if p != "self"), params)

    def test_poll_keeps_its_default_offset(self):
        self.assertEqual(inspect.signature(app.Api.poll).parameters["since"].default, 0)

    def test_api_holds_no_harmony_state(self):
        """鸿蒙状态与构造逻辑属于独立块，Api 只转发（#898）。"""
        api = classes()["Api"]
        assigned = {"self." + node.attr for node in ast.walk(api)
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "self" and isinstance(node.ctx, ast.Store)}
        self.assertFalse(assigned & {"self.harmony_service", "self.harmony_lock"})
        self.assertIn("self.harmony_bridge", assigned)


class ReExportTests(unittest.TestCase):
    """搬出 `gui/app.py` 的块仍按 `app.<名字>` 取得到，且是同一个对象（#1382）。

    `tests/`、手机版与打包脚本大量按 `app.<名字>` 取用；搬走之后少一个名字，那些地方就是
    AttributeError，而它们大多不在回归的覆盖面上。`startup_failed` 是转发壳（要多传 `APP_NAME`），
    在这里只核它还在、签名没变。
    """

    def test_the_startup_names_are_the_same_objects(self):
        from gui import startup
        for name in ("version_key", "startup_advice", "_attribution", "win_clipboard",
                     "COPIED_NOTE", "MANUAL_COPY_NOTE"):
            with self.subTest(name=name):
                self.assertIs(getattr(app, name), getattr(startup, name), f"app.{name} 没有 re-export")

    def test_startup_failed_keeps_its_signature(self):
        self.assertEqual(tuple(inspect.signature(app.startup_failed).parameters),
                         ("error", "preflight", "notify", "open_url", "clipboard"))


class BoundaryTests(unittest.TestCase):
    def test_blocks_do_not_name_each_other(self):
        found = classes()
        self.assertTrue(set(BLOCKS) <= set(found), "三块类没有全部出现，这条守卫会空转")
        for name in BLOCKS:
            others = set(BLOCKS) - {name}
            used = set()
            for node in ast.walk(found[name]):
                if isinstance(node, ast.Name):
                    used.add(node.id)
                elif isinstance(node, ast.Attribute):
                    used.add(node.attr)
            self.assertFalse(used & others, f"{name} 提到了 {sorted(used & others)}")

    def test_blocks_do_not_reach_into_each_other(self):
        found = classes()
        for name, forbidden in FORBIDDEN_IN.items():
            seen = set()
            for node in ast.walk(found[name]):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                        and node.value.id == "self":
                    seen.add("self." + node.attr)
            self.assertFalse(seen & forbidden, f"{name} 读了 {sorted(seen & forbidden)}")

    def test_blocks_do_not_use_getattr_to_reach_around(self):
        found = classes()
        for name in BLOCKS:
            for node in ast.walk(found[name]):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and node.func.id == "getattr" and len(node.args) > 1 \
                        and isinstance(node.args[0], ast.Name) and node.args[0].id == "self" \
                        and isinstance(node.args[1], ast.Constant):
                    self.assertNotIn(node.args[1].value, BLOCKS,
                                     f"{name} 用 getattr 绕到了 {node.args[1].value}")


class DispatcherSeamTests(unittest.TestCase):
    """执行编排的协作者全部由构造方给（#1383）：块里不认识 `gui/app.py` 的模块全局。

    铃声、断线措辞、adb 存活探测都传取值函数进来——手机版在 `boot()` 里换掉它们、测试在构造之后
    patch 它们，两种都要落到搬走之后的那份实现上。三样 `tool/` 模块（`summary` / `coverage_note` /
    `plan_of`）同样是构造参数，块里不自己加载。
    """

    def test_the_host_hooks_come_from_the_constructor(self):
        from fixtures import FakeProc, FakeRunner, job_stub
        from gui import dispatcher, tasks, toolpath

        rings, probes = [], []
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runner = FakeRunner(spawns=[FakeProc('#aac:event {"kind": "link_lost"}\n读屏断了\n', rc=1)])
        block = dispatcher.Dispatcher(lambda: runner, lambda: None, app.ClientData(directory.name),
                                      lambda: None, lambda operation, serial, detail: "",
                                      chime=lambda: rings.append(1),
                                      link_lost=lambda: "注入的断线措辞",
                                      adb_present=lambda adb, serial: probes.append(serial) or False,
                                      summary=toolpath.tool("summary"),
                                      coverage_note=toolpath.tool("coverage_note"),
                                      plan_of=lambda: toolpath.tool("plan"))
        block.job = job_stub(serial="SER")
        block._work([tasks.Task("广告开关", "run.py", ["-s", "SER", "recipe"]),
                     tasks.Task("收尾", "run.py", ["-s", "SER", "finish"], always_run=True)])
        self.assertEqual(block.job.results[1]["tail"], ["注入的断线措辞"])
        self.assertEqual(probes, ["SER"])
        self.assertTrue(rings, "执行结束的提示音要走注入的那个")


class ClipboardWiringTests(unittest.TestCase):
    """写剪贴板只有一个实现：窗口桥的 `copy_text` 与启动失败弹窗走同一个 `win_clipboard`（#1382）。

    那一份住在 `gui/startup.py`，桥面按模块取用；多 import 一份函数对象就会让换掉
    `gui.startup.win_clipboard` 的替身落不到 `copy_text` 上。
    """

    def test_copy_text_goes_through_the_startup_clipboard(self):
        from gui import startup
        seen = []
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        api = app.Api(directory.name)
        with patch.object(app, "IS_WIN", True), patch.object(startup, "win_clipboard", seen.append):
            self.assertTrue(api.copy_text("诊断文本"))
        self.assertEqual(seen, ["诊断文本"])


if __name__ == "__main__":
    unittest.main()
