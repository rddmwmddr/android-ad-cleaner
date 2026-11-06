"""#632：收尾按 `<型号>-gui` 目录里不存在的 stay_on.txt 把「插电常亮」写成 0。"""

import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
from backups import Backups
import run


class FinishStayOnTest(unittest.TestCase):
    def finish(self, root):
        calls = []
        out = io.StringIO()
        with patch.object(run, "BACKUPS", root), patch.object(run, "info", return_value={"model": "M"}), \
                patch.object(run, "sh", side_effect=lambda s, c, *a, **k: calls.append(c) or "0"), \
                contextlib.redirect_stdout(out):
            run.cmd_finish("test", [])
        return [c for c in calls if "stay_on" in c], out.getvalue()

    def test_gui_dir_after_snapshot_does_not_hide_saved_value(self):
        with tempfile.TemporaryDirectory() as root:
            snap = Backups(root).create("M")
            Path(snap, "stay_on.txt").write_text("15", encoding="utf-8")
            Path(Backups(root).gui("M"), "channels.tsv").write_text("", encoding="utf-8")
            puts, out = self.finish(root)
            self.assertEqual(puts, ["settings put global stay_on_while_plugged_in 15"])
            self.assertIn("插电常亮已改回 15", out)

    def test_no_snapshot_leaves_setting_alone(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "M-20261106-1218"))     # 快照刚建目录就被停止
            puts, out = self.finish(root)
            self.assertEqual(puts, [])
            self.assertIn("插电常亮未改动", out)

    def test_newest_snapshot_with_the_file_wins(self):
        with tempfile.TemporaryDirectory() as root:
            for name, v in (("M-20261105-0900", "7"), ("M-20261106-0900", "15")):
                os.makedirs(os.path.join(root, name))
                Path(root, name, "stay_on.txt").write_text(v, encoding="utf-8")
            os.makedirs(os.path.join(root, "M-20261106-1218"))
            self.assertEqual(Path(Backups(root).newest_with("M", "stay_on.txt")).read_text(encoding="utf-8"), "15")


if __name__ == "__main__":
    unittest.main()
