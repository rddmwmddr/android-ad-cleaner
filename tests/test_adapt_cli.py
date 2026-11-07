"""adapt.py 三条子命令对外的退出码与两路输出，与改动前逐字节相同（#708）。

基线 `tests/baselines/adapt_cli.json` 由 `tests/make_adapt_cli_baseline.py` 在
`git archive 294ff50` 的干净副本上生成，喂的是同一份用例（`tests/adapt_cli_cases.py`）。

需要手机的档位不进对拍：`check` 的锁屏与报告结论要真的读屏，`explore` 要真的连手机，
它们的退出码在 `tests/test_adapt_assistant.py` 里进程内断言。
`OSError` 的系统文案由 harness 规范化（见 `tests/adapt_cli_driver.py`），其余逐字比对。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import adapt_cli_cases
import adapt_cli_driver

BASELINE = ROOT / "tests" / "baselines" / "adapt_cli.json"


class AdaptCliParityTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_every_subcommand_is_covered(self):
        """三条子命令与参数分派都要有用例，每条带守卫断言，漏一条这里就红。"""
        covered = {spec["argv"][0] for spec in adapt_cli_cases.CASES}
        self.assertTrue({"gen", "check", "explore"} <= covered)
        self.assertTrue(any(spec["argv"][0] not in ("gen", "check", "explore") for spec in adapt_cli_cases.CASES))
        missing = [spec["name"] for spec in adapt_cli_cases.CASES if not spec["expect"]]
        self.assertEqual(missing, [])

    def test_matches_baseline(self):
        for spec in adapt_cli_cases.CASES:
            with self.subTest(spec["name"]), tempfile.TemporaryDirectory() as work:
                got = adapt_cli_driver.run_once(ROOT, spec, work)
                # 守卫断言先跑：证明这条用例真的走到了目标分支，而不是两边都停在同一个错误上。
                printed = got["stdout"] + got["stderr"]
                for needle in spec["expect"]:
                    self.assertIn(needle, printed)
                self.assertEqual(got, self.baseline["cases"][spec["name"]])


if __name__ == "__main__":
    unittest.main()
