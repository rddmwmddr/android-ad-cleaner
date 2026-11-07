"""#710：设备名的候选属性只定义一处，设备列表与 status-json 给出同一个名字。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run  # noqa: E402

BRAND, MODEL, VENDOR_NAME = "OPPO", "PJD110", "OPPO Find X8"

# 改动前 info() 的 or 链逐字冻结：NAME_PROPS 删词、挪位都要让下面那条断言返红。
# 不遍历实现自己的元组——否则删词会连期望一起消失（CODING_STANDARDS.md）。
BASE_NAME_PROPS = ("ro.vendor.oplus.market.name", "ro.product.marketname", "ro.product.vendor.marketname")


def adb_reply(props, calls):
    """假 adb：`devices -l` 报一台设备，`shell` 按 getprop 串逐条回值。"""
    def _adb(*args, timeout=20):
        calls.append(args)
        if args[0] == "devices":
            return "List of devices attached\nS\tdevice\n"
        keys = [part.split("getprop ", 1)[1] for part in args[3].split(";") if "getprop " in part]
        return "\n".join(props.get(key, "") for key in keys) + "\n"
    return _adb


class DeviceNameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = app.Api(self.tmp.name)
        self.api.adb = "/opt/tools/adb"
        self.calls = []

    def device_listed(self, props):
        """GUI 设备列表里那一行；props 是「属性 → 值」表。"""
        with patch.object(self.api, "_adb", adb_reply(props, self.calls)):
            return self.api.devices()["list"][0]

    def status_name(self, props):
        """status-json 那条路上的名字，走 info() 自己的 getprop 顺序。"""
        with patch.object(run, "prop", side_effect=lambda serial, key: props.get(key, "")):
            return run.info("S")["name"]

    def test_vendor_marketname_is_shared_by_both_sides(self):
        # 只暴露 ro.product.vendor.marketname 的手机：设备列表以前落到 brand + model，检测页给市场名
        props = {"ro.product.brand": BRAND, "ro.product.model": MODEL,
                 "ro.product.vendor.marketname": VENDOR_NAME}
        listed = self.device_listed(props)
        self.assertEqual(listed["name"], VENDOR_NAME)
        self.assertEqual(self.status_name(props), VENDOR_NAME)

    def test_both_sides_fall_back_to_brand_and_model(self):
        """旧树也绿，守的是都空时两边回退成同一个 brand + model，不被塞进假名字。"""
        props = {"ro.product.brand": BRAND, "ro.product.model": MODEL}
        listed = self.device_listed(props)
        self.assertEqual(listed["name"], "")
        self.assertEqual(self.status_name(props), "")
        # 前端两处的回退表达式都是 name || brand + " " + model
        self.assertEqual(listed["name"] or listed["brand"] + " " + listed["model"], f"{BRAND} {MODEL}")

    def test_marketname_precedes_vendor_marketname(self):
        """旧树也绿，守的是两个候选都有值时仍取靠前的那个，顺序不被 vendor 属性顶掉。"""
        props = {"ro.product.marketname": "Find X8", "ro.product.vendor.marketname": VENDOR_NAME}
        self.assertEqual(self.device_listed(props)["name"], "Find X8")
        self.assertEqual(self.status_name(props), "Find X8")

    def test_candidate_props_are_frozen(self):
        self.assertEqual(run.NAME_PROPS, BASE_NAME_PROPS)

    def test_device_list_reads_every_candidate_in_one_shell_call(self):
        self.device_listed({"ro.product.brand": BRAND, "ro.product.model": MODEL})
        shells = [call for call in self.calls if call[0] == "-s"]
        self.assertEqual(len(shells), 1)
        command = shells[0][3]
        self.assertEqual(command.count("getprop"), 2 + len(BASE_NAME_PROPS))
        for key in BASE_NAME_PROPS:
            self.assertIn(f"getprop {key}", command)


if __name__ == "__main__":
    unittest.main()
