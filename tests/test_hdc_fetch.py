"""#898：HDC 只在构建期从 OpenHarmony SDK 下载、校验、解包；用例不联网。"""
import hashlib
import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from gui import hdc_fetch

MAC_X64_TARBALL = "391d76cb90d69b476ae0b65a9f311c572e1a9cdd77da71734af62ed63b108dcc"
MAC_ARM64_TARBALL = "df46e398b391d3406d1eb05e7322c5874f6bf6821e93b1211b36cfcf7a0bbf6f"
WINDOWS_TARBALL = "130a438cbcddd46a2a5b09ee9925339cddf4cca99223329b860f96a5c72f338f"
MAC_X64_HDC = "813eb8d03f88ed211ca51507965e6b269eaa6badc00824de56d8e14e463b3e3a"
MAC_X64_USB = "ca969caa3689a318a2e2f06b6cc87371ced640506f8e79abe59a2e98efcdb4dc"
MAC_ARM64_HDC = "0a37c94164e305dd7ea62ffe395dc4f5a336210d00a3e7f9c97d8f1cc92878c3"
MAC_ARM64_USB = "4268da1480ee6950696fd102cedb5627bcdbb6a2928233133460a3dbe6a254c1"
WINDOWS_HDC = "fa77ab490ab12b10760f01627a894062d12749c4917608fafa96df1860a131c4"
WINDOWS_USB = "e6f475c9e770b02080958e788426aeab8540a6c1fad5c029e83d2f1d72d5e649"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def toolchain_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def tarball(member, payload):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class FakeDownloader:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, dest):
        self.calls.append(url)
        if isinstance(self.payload, Exception):
            raise self.payload
        Path(dest).write_bytes(self.payload)


def sample_spec(hdc=b"hdc-bytes", usb=b"libusb-bytes", **overrides):
    payload = tarball("sdk/pkg/toolchains-test.zip",
                      toolchain_zip({"toolchains/hdc": hdc, "toolchains/libusb_shared.dylib": usb}))
    spec = {
        "tarball": "sample.tar.gz",
        "tarball_sha256": sha(payload),
        "member": "sdk/pkg/toolchains-test.zip",
        "files": {
            "hdc": ("toolchains/hdc", sha(hdc)),
            "libusb_shared.dylib": ("toolchains/libusb_shared.dylib", sha(usb)),
        },
    }
    spec.update(overrides)
    return spec, payload


class PlatformTableTest(unittest.TestCase):
    def test_pins_the_official_release_hashes(self):
        """数值取自 #898：上游重发包时这里先红，而不是悄悄换掉工具。"""
        self.assertEqual(hdc_fetch.RELEASE, "7.0-Release")
        self.assertEqual(hdc_fetch.BASE_URL, "https://repo.huaweicloud.com/openharmony/os/7.0-Release/")
        expected = {
            "mac-x64": (MAC_X64_TARBALL, MAC_X64_HDC, MAC_X64_USB),
            "mac-arm64": (MAC_ARM64_TARBALL, MAC_ARM64_HDC, MAC_ARM64_USB),
            "windows": (WINDOWS_TARBALL, WINDOWS_HDC, WINDOWS_USB),
        }
        for arch, (tarball_sha, hdc_sha, usb_sha) in expected.items():
            spec = hdc_fetch.PLATFORMS[arch]
            self.assertEqual(spec["tarball_sha256"], tarball_sha, arch)
            hashes = [entry[1] for entry in spec["files"].values()]
            self.assertEqual(sorted(hashes), sorted([hdc_sha, usb_sha]), arch)

    def test_arch_mapping_is_single_sourced(self):
        self.assertEqual(hdc_fetch.arch_of("darwin", "arm64"), "mac-arm64")
        self.assertEqual(hdc_fetch.arch_of("darwin", "x86_64"), "mac-x64")
        self.assertEqual(hdc_fetch.arch_of("win32", "AMD64"), "windows")
        self.assertIsNone(hdc_fetch.arch_of("linux", "x86_64"))


class FetchTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def fetch(self, spec, downloader):
        return hdc_fetch.fetch("mac-x64", spec=spec, downloader=downloader, cache=self.root)

    def test_downloads_the_platform_tarball_and_writes_both_files(self):
        spec, payload = sample_spec()
        downloader = FakeDownloader(payload)
        files = self.fetch(spec, downloader)
        self.assertEqual(sorted(files), ["hdc", "libusb_shared.dylib"])
        self.assertEqual(Path(files["hdc"]).read_bytes(), b"hdc-bytes")
        self.assertEqual(Path(files["libusb_shared.dylib"]).read_bytes(), b"libusb-bytes")
        self.assertEqual(len(downloader.calls), 1)
        self.assertTrue(downloader.calls[0].endswith("sample.tar.gz"))

    def test_tarball_hash_mismatch_fails_without_writing_tools(self):
        spec, payload = sample_spec(tarball_sha256="0" * 64)
        with self.assertRaises(ValueError):
            self.fetch(spec, FakeDownloader(payload))
        self.assertFalse((self.root / "hdc").exists())

    def test_inner_file_hash_mismatch_fails(self):
        spec, payload = sample_spec()
        spec["files"]["hdc"] = ("toolchains/hdc", "f" * 64)
        with self.assertRaises(ValueError):
            self.fetch(spec, FakeDownloader(payload))
        self.assertFalse((self.root / "hdc").exists())

    def test_cache_hit_does_not_download_again(self):
        spec, payload = sample_spec()
        self.fetch(spec, FakeDownloader(payload))
        offline = FakeDownloader(RuntimeError("cache hit must not download"))
        files = self.fetch(spec, offline)
        self.assertEqual(offline.calls, [])
        self.assertTrue(Path(files["hdc"]).is_file())

    def test_env_overrides_the_cache_root(self):
        with tempfile.TemporaryDirectory() as custom:
            self.assertEqual(hdc_fetch.cache_dir("mac-arm64", {"AAC_HDC_CACHE": custom}),
                             Path(custom) / hdc_fetch.RELEASE / "mac-arm64")

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(KeyError):
            hdc_fetch.fetch("linux-x64", cache=self.root)

    def test_stage_vendor_lays_out_the_bundle_resources(self):
        spec, payload = sample_spec()
        staged = hdc_fetch.stage_vendor(self.root, "mac-x64", spec=spec, downloader=FakeDownloader(payload))
        vendor = self.root / "harmony" / "desktop" / "vendor" / "mac-x64"
        self.assertEqual(sorted(Path(p).name for p in staged), ["hdc", "libusb_shared.dylib"])
        self.assertTrue((vendor / "hdc").is_file())
        self.assertTrue((vendor / "libusb_shared.dylib").is_file())


if __name__ == "__main__":
    unittest.main()
