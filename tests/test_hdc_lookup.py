"""#898：找 hdc 的候选顺序——显式 HDC → 缓存目录 → 包内 → PATH → SDK 默认。"""
import os
import tempfile
import unittest
from pathlib import Path

from gui import hdc_fetch, harmony_engine as engine

EXE = "hdc.exe" if os.name == "nt" else "hdc"


class LookupTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def touch(self, *parts):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return str(path)

    def candidates(self, **kwargs):
        env = dict(kwargs.pop("env", {}))
        env.setdefault("AAC_HDC_CACHE", str(self.root / "cache"))
        return engine.hdc_candidates(arch="mac-x64", env=env, bundle=self.root / "bundle",
                                     which=kwargs.pop("which", lambda _name: None),
                                     home=self.root / "home", **kwargs)

    def test_explicit_HDC_wins_over_everything(self):
        explicit = self.touch("explicit", EXE)
        self.touch("cache", hdc_fetch.RELEASE, "mac-x64", EXE)
        order = self.candidates(env={"HDC": explicit})
        self.assertEqual(order[0], explicit)

    def test_cache_precedes_bundled_and_path(self):
        cache = self.touch("cache", hdc_fetch.RELEASE, "mac-x64", EXE)
        bundled = self.touch("bundle", "harmony", "desktop", "vendor", "mac-x64", EXE)
        on_path = self.touch("path", EXE)
        order = self.candidates(which=lambda name: on_path if name == "hdc" else None)
        self.assertEqual(order, [cache, bundled, on_path,
                                 str(self.root / "home/.local/share/harmony-clt/sdk/default/openharmony/toolchains" / EXE)])

    def test_bundled_precedes_path_when_cache_is_empty(self):
        bundled = self.touch("bundle", "harmony", "desktop", "vendor", "mac-x64", EXE)
        on_path = self.touch("path", EXE)
        order = self.candidates(which=lambda name: on_path if name == "hdc" else None)
        self.assertEqual(order[:3], [str(self.root / "cache" / hdc_fetch.RELEASE / "mac-x64" / EXE), bundled, on_path])

    def test_find_hdc_returns_first_existing_candidate(self):
        cache = self.touch("cache", hdc_fetch.RELEASE, "mac-x64", EXE)
        env = {"AAC_HDC_CACHE": str(self.root / "cache")}
        self.assertEqual(engine.find_hdc(env=env, arch="mac-x64", bundle=self.root / "bundle",
                                         which=lambda _name: None, home=self.root / "home"), cache)

    def test_find_hdc_raises_when_nothing_exists(self):
        with self.assertRaises(FileNotFoundError):
            engine.find_hdc(env={"AAC_HDC_CACHE": str(self.root / "cache")}, arch="mac-x64",
                            bundle=self.root / "bundle", which=lambda _name: None, home=self.root / "home")


if __name__ == "__main__":
    unittest.main()
