"""渠道引擎三个子命令的 CLI 输出基线：scan / off / on 的退出码、输出行与分支守卫。

基线 `tests/baselines/chan_cli.json` 由 `tests/make_chan_cli_baseline.py` 在 `git archive 103f19e0`
的干净副本上生成，喂的是同一份用例（`tests/chan_cli_cases.py`）与同一个假设备（`tests/chan_cli_probe.py`）。
批处理的队列、两趟、重试挑行与收尾复查搬成纯函数时，这三个子命令对外的东西要逐字不变：
退出码、两路输出、adb 往返顺序、`UI_HIDDEN` 名单的落盘。

`verify` 只做机械迁移（票面 Out of scope：行为不调整），它那一条也在基线里，防的是搬迁时顺手改掉。
"""
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "tests"))
import chan_cli_cases  # noqa: E402
import chan_cli_driver  # noqa: E402

BASELINE = ROOT / "tests" / "baselines" / "chan_cli.json"


class ChanCliParityTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_every_subcommand_is_covered_and_pinned_once(self):
        """三个子命令都要有用例；每条用例要么有输出断言、要么有守卫断言，
        基线里的用例数也要与用例表对上（加一条忘记重生成，这里就红）。"""
        covered = {spec["argv"][2] for spec in chan_cli_cases.CASES if len(spec["argv"]) > 2}
        self.assertTrue({"scan", "off", "on", "verify"} <= covered)
        self.assertEqual(self.baseline["provenance"]["cases"], len(chan_cli_cases.CASES))
        missing = [spec["name"] for spec in chan_cli_cases.CASES if not (spec["expect"] or spec["guards"])]
        self.assertEqual(missing, [])

    def test_matches_baseline(self):
        for spec in chan_cli_cases.CASES:
            with self.subTest(spec["name"]), tempfile.TemporaryDirectory() as work:
                got = chan_cli_driver.run_once(ROOT, spec, work)
                # 守卫断言先跑：证明这条用例真的走到了目标分支，而不是两边都停在同一个错误上。
                printed = got["stdout"] + got["stderr"]
                for needle in spec["expect"]:
                    self.assertIn(needle, printed)
                for key, want in spec["guards"].items():
                    self.assertEqual(got["guards"][key], want, f"{spec['name']} 的守卫 {key} 不对")
                self.assertEqual(got, self.baseline["cases"][spec["name"]])


if __name__ == "__main__":
    unittest.main()
