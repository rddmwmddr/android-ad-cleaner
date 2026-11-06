"""备份目录：命名、扫描、`<型号>-gui` 兜底各只有一处（tool/backups.py）。

对拍基线是改动前散在 run.py 与 gui/app.py 的两份实现，逐字抄在下面；两边喂同一批目录树。
"""
import datetime
import glob
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

from backups import Backups  # noqa: E402


# ---------- 基线：改动前的两处实现 ----------
def old_gui_latest(root, model):
    """gui/app.py:541-544（_latest_backup）。"""
    try:
        hits = sorted(d for d in os.listdir(root) if d.startswith(model + "-"))
        return os.path.join(root, hits[-1]) if hits else None
    except FileNotFoundError:
        return None


def old_run_latest(root, model):
    """run.py:211-214 的 create=False 分支（glob 版）。"""
    hits = sorted(glob.glob(os.path.join(root, f"{model}-*")))
    return hits[-1] if hits else None


def old_create(root, model, now):
    """run.py:214-216 的 create=True 分支。"""
    d = os.path.join(root, f"{model}-{now:%Y%m%d-%H%M}")
    os.makedirs(d, exist_ok=True)
    return d


def old_gui_fallback(root, model):
    """gui/app.py:571-572 的 `<型号>-gui` 兜底。"""
    d = os.path.join(root, f"{model}-gui")
    os.makedirs(d, exist_ok=True)
    return d


MODEL = "xiaomi-M154FF"

# 每条用例：(说明, 预先存在的目录名)
TREES = (
    ("空仓库", ()),
    ("只有带时间的备份", (f"{MODEL}-20260101-1000",)),
    ("多份备份取最后一份", (f"{MODEL}-20260101-1000", f"{MODEL}-20260101-1010")),
    ("gui 兜底目录", (f"{MODEL}-20260101-1000", f"{MODEL}-gui")),
    ("只有 gui 兜底目录", (f"{MODEL}-gui",)),
    ("名字相近的别家型号", (f"{MODEL}x-20260101-1000",)),
    ("同名前缀但没破折号", (MODEL,)),
)


class LatestTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = self.dir.name

    def test_latest_matches_both_old_implementations(self):
        for label, names in TREES:
            with self.subTest(label):
                for name in names:
                    Path(self.root, name).mkdir(exist_ok=True)
                newest = Backups(self.root).latest(MODEL)
                self.assertEqual(newest, old_gui_latest(self.root, MODEL))
                self.assertEqual(newest, old_run_latest(self.root, MODEL))

    def test_missing_root_returns_none_like_the_gui_did(self):
        missing = os.path.join(self.root, "not-created")
        self.assertFalse(os.path.exists(missing))
        self.assertIsNone(old_gui_latest(missing, MODEL))
        self.assertIsNone(Backups(missing).latest(MODEL))

    def test_missing_root_really_takes_the_file_not_found_branch(self):
        # 守卫：不是「目录里恰好什么都没有」，而是 os.listdir 真的抛了 FileNotFoundError 被接住
        with patch("backups.os.listdir", side_effect=FileNotFoundError) as listed:
            self.assertIsNone(Backups(self.root).latest(MODEL))
        listed.assert_called_once()

    def test_glob_metacharacters_in_the_model_stay_literal(self):
        # 型号不会带 [ ] * ?。选 listdir 语义（gui 侧的原实现）：glob 版会把 A[B]C-* 当字符类，
        # 匹配到 ABC-20260101-1000。两边原来就不一致，这里钉住选中的那一套。
        Path(self.root, "ABC-20260101-1000").mkdir()
        self.assertEqual(old_run_latest(self.root, "A[B]C"), os.path.join(self.root, "ABC-20260101-1000"))
        self.assertIsNone(Backups(self.root).latest("A[B]C"))

    def test_gui_fallback_outranks_dated_backups(self):
        # 字典序 "gui" > "2026..."：只要 `<型号>-gui` 存在，它就是「最近一份」。这是现状行为，不改成取最新。
        Path(self.root, f"{MODEL}-gui").mkdir()
        Path(self.root, f"{MODEL}-20991231-2359").mkdir()
        self.assertGreater("gui", "20991231-2359")
        self.assertEqual(Backups(self.root).latest(MODEL), os.path.join(self.root, f"{MODEL}-gui"))

    def test_empty_model_uses_the_bare_dash_prefix(self):
        Path(self.root, "-gui").mkdir()
        self.assertEqual(Backups(self.root).latest(""), os.path.join(self.root, "-gui"))
        self.assertEqual(Backups(self.root).latest(""), old_gui_latest(self.root, ""))


class AllTests(unittest.TestCase):
    """`all()` 是三处扫描的唯一实现：`latest()` / `newest_with()` 都从它派生，顺序不能分叉。"""

    def test_all_is_the_same_scan_newest_first(self):
        for label, names in TREES:
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as root:
                    for name in names:
                        Path(root, name).mkdir(exist_ok=True)
                    dirs = Backups(root).all(MODEL)
                    expected = sorted((os.path.join(root, n) for n in names if n.startswith(MODEL + "-")),
                                      reverse=True)
                    self.assertEqual(dirs, expected)
                    self.assertEqual(Backups(root).latest(MODEL), dirs[0] if dirs else None)

    def test_missing_root_gives_an_empty_list(self):
        missing = os.path.join(tempfile.mkdtemp(), "not-created")
        self.assertFalse(os.path.exists(missing))
        self.assertEqual(Backups(missing).all(MODEL), [])


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = self.dir.name
        self.now = datetime.datetime(2026, 10, 30, 9, 5)

    def test_create_matches_the_old_name_and_makes_the_directory(self):
        made = Backups(self.root).create(MODEL, when=self.now)
        self.assertEqual(made, old_create(self.root, MODEL, self.now))
        self.assertEqual(os.path.basename(made), f"{MODEL}-20261030-0905")
        self.assertTrue(os.path.isdir(made))

    def test_create_always_starts_a_new_directory_even_when_backups_exist(self):
        # run.py 的 create=True 不返回旧目录，而是再建一份 —— 对拍守住这一点
        Path(self.root, f"{MODEL}-20260101-1000").mkdir()
        made = Backups(self.root).create(MODEL, when=self.now)
        self.assertNotEqual(made, os.path.join(self.root, f"{MODEL}-20260101-1000"))
        self.assertEqual(sorted(os.listdir(self.root)), [f"{MODEL}-20260101-1000", f"{MODEL}-20261030-0905"])

    def test_gui_fallback_matches_the_old_one(self):
        made = Backups(self.root).gui(MODEL)
        self.assertEqual(made, old_gui_fallback(self.root, MODEL))
        self.assertEqual(os.path.basename(made), f"{MODEL}-gui")
        self.assertTrue(os.path.isdir(made))


class RootFromEnvTests(unittest.TestCase):
    def test_env_wins_and_absence_is_empty(self):
        from backups import root_from_env
        with patch.dict(os.environ, {"AAC_BACKUPS": "/tmp/where"}, clear=False):
            self.assertEqual(root_from_env(), "/tmp/where")
        with patch.dict(os.environ, {"AAC_BACKUPS": ""}, clear=False):
            self.assertEqual(root_from_env(), "")


if __name__ == "__main__":
    unittest.main()
