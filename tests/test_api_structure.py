"""窗口桥契约与三块的责任边界（ADR-0011）。

窗口桥清单从改前的 `Api` 抄死：内部怎么拆都可以变，这 22 个名字与参数不能变。
三块之间不许互相点名，也不许 `self.<别的块>` 去读对方的状态。
"""
import ast
import inspect
import unittest
from pathlib import Path

from gui import app

ROOT = Path(__file__).resolve().parents[1]

BRIDGE = {
    "env": (),
    "latest_version": (),
    "devices": (),
    "usb_hint": (),
    "status": ("serial",),
    "chan_scan": ("serial",),
    "ui_check": ("serial",),
    "start": ("serial", "plan"),
    "poll": ("since",),
    "stop": (),
    "pause": (),
    "resume": (),
    "download_adb": (),
    "download_state": (),
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


def classes():
    tree = ast.parse((ROOT / "gui" / "app.py").read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


class BridgeTests(unittest.TestCase):
    def test_window_bridge_signatures_stay_put(self):
        for name, params in BRIDGE.items():
            with self.subTest(method=name):
                signature = inspect.signature(getattr(app.Api, name))
                self.assertEqual(tuple(p for p in signature.parameters if p != "self"), params)

    def test_poll_keeps_its_default_offset(self):
        self.assertEqual(inspect.signature(app.Api.poll).parameters["since"].default, 0)


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


if __name__ == "__main__":
    unittest.main()
