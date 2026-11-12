"""#1124：验证台账的覆盖度、证据来源与验证日期经 `status-json` 带出。

三个值都由引擎从 `recipes/verified.toml` 现读，客户端只透传。这里守两件外部行为：
真机上有的脚本，出来的是台账里那一行；台账里没有的脚本，出来的是「未记录 / 未知 / 空」而不是崩。
引擎侧别的读设备动作全部替身化——这三样是纯本地数据，一条 adb 命令都不该发。
"""
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run  # noqa: E402
import verify_ledger  # noqa: E402

LEDGER = verify_ledger.load(os.path.join(ROOT, "recipes", "verified.toml"))


def status_json(serial="S", device=None):
    """跑一次 `status-json`，只留下 JSON；`device` 是 `info()` 的返回值。"""
    device = device or {"model": "M154FF", "brand": "Xiaomi", "name": "Xiaomi 13",
                        "build": "OS4.0.24", "os": "OS4.0.24"}
    out = io.StringIO()

    def no_device(*_a, **_k):
        raise AssertionError("status-json 不该为这三个值再去读手机")

    with patch.object(run, "info", return_value=device), \
         patch.object(run, "locked", return_value=False), \
         patch.object(run, "ad_packages", return_value=()), \
         patch.object(run, "quickapps", return_value=[]), \
         patch.object(run, "sh", return_value=""), \
         patch.object(run, "fold_open", return_value=False), \
         patch.object(run, "input_blocked", return_value=False), \
         patch.object(run, "installed", side_effect=no_device), \
         contextlib.redirect_stdout(out):
        assert run.cmd_status_json(serial, []) == 0
    return json.loads(out.getvalue().strip().splitlines()[-1])


class StatusJsonVerificationTests(unittest.TestCase):
    def test_values_come_from_the_ledger_row_for_this_script(self):
        st = status_json()
        key = "xiaomi-M154FF/recipe.py"
        self.assertEqual(st["recipe"], f"recipes/{key}")
        record = LEDGER[key]
        self.assertEqual((st["recipe_coverage"], st["recipe_evidence"], st["recipe_verified"]),
                         (record["tier"], record["evidence"], record["date"]))

    def test_a_script_missing_from_the_ledger_is_unrecorded_and_unknown(self):
        """没有专用脚本的机型：三个值照样有，是「未记录 / 未知 / 空」，不是异常也不是缺键。"""
        st = status_json(device={"model": "NOPE-1", "brand": "Foo", "name": "Foo NOPE-1",
                                 "build": "X", "os": "X"})
        self.assertIsNone(st["recipe"])
        self.assertEqual((st["recipe_coverage"], st["recipe_evidence"], st["recipe_verified"]),
                         (verify_ledger.UNRECORDED, verify_ledger.UNKNOWN_EVIDENCE, ""))


if __name__ == "__main__":
    unittest.main()
