"""#1124：验证台账的覆盖度、证据来源与验证日期经 `status-json` 带出。

三个值都由引擎从 `recipes/verified.toml` 现读，客户端只透传。这里守两件外部行为：
真机上有的脚本，出来的是台账里那一行；台账里没有的脚本，出来的是「未记录 / 未知 / 空」而不是崩。
读设备的那几个协作方替身化只是为了把 `status-json` 跑起来——它们的输出由 CLI 逐字节对拍守着
（`tests/baselines/run_cli.json`），这里断言的是台账确实被读、读到的是哪份路径。
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
LEDGER_PATH = os.path.join(run.RECIPES, "verified.toml")


def status_json(device=None):
    """跑一次 `status-json`，返回 (JSON, 台账读取的替身)；`device` 是 `info()` 的返回值。"""
    device = device or {"model": "M154FF", "brand": "Xiaomi", "name": "Xiaomi 13",
                        "build": "OS4.0.24", "os": "OS4.0.24"}
    out = io.StringIO()
    with patch.object(run, "info", return_value=device), \
         patch.object(run, "locked", return_value=False), \
         patch.object(run, "ad_packages", return_value=()), \
         patch.object(run, "quickapps", return_value=[]), \
         patch.object(run, "sh", return_value=""), \
         patch.object(run, "fold_open", return_value=False), \
         patch.object(run, "input_blocked", return_value=False), \
         patch.object(verify_ledger, "load", wraps=verify_ledger.load) as load, \
         contextlib.redirect_stdout(out):
        assert run.cmd_status_json("S", []) == 0
    return json.loads(out.getvalue().strip().splitlines()[-1]), load


class StatusJsonVerificationTests(unittest.TestCase):
    def test_values_come_from_the_ledger_row_for_this_script(self):
        st, load = status_json()
        self.assertEqual(st["recipe"], "recipes/xiaomi-M154FF/recipe.py")
        load.assert_called_once_with(LEDGER_PATH)
        record = LEDGER["xiaomi-M154FF/recipe.py"]
        self.assertEqual((st["recipe_coverage"], st["recipe_evidence"], st["recipe_verified"]),
                         (record["tier"], record["evidence"], record["date"]))

    def test_a_script_missing_from_the_ledger_is_unrecorded_and_unknown(self):
        """没有专用脚本的机型：三个值照样有，是「未记录 / 未知 / 空」，不是异常也不是缺键。
        没有脚本可查时连台账都不该读。"""
        st, load = status_json(device={"model": "NOPE-1", "brand": "Foo", "name": "Foo NOPE-1",
                                       "build": "X", "os": "X"})
        self.assertIsNone(st["recipe"])
        load.assert_not_called()
        self.assertEqual((st["recipe_coverage"], st["recipe_evidence"], st["recipe_verified"]),
                         (verify_ledger.UNRECORDED, verify_ledger.UNKNOWN_EVIDENCE, ""))


if __name__ == "__main__":
    unittest.main()
