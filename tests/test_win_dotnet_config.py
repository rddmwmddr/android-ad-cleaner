"""随包分发的 `<exe>.config`：让包内托管 dll 不被 .NET Framework 判成「网络位置」（#597）。

打包脚本只在 Windows 上跑，这里守着两件事：写出来的内容只开 `loadFromRemoteSources`，
以及 `windows.spec` 真的调了它——spec 里的这一步写错了本地全绿，只有用户解压后才发现。
"""
import re
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from gui import dotnet_config

ROOT = Path(__file__).resolve().parents[1]
EXES = ("AndroidAdCleaner", "aac-cli")


class WriteConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_writes_one_config_next_to_each_exe(self):
        paths = dotnet_config.write(self.dir.name, EXES)
        self.assertEqual({Path(p).name for p in paths},
                         {"AndroidAdCleaner.exe.config", "aac-cli.exe.config"})
        for path in paths:
            self.assertTrue(Path(path).is_file(), f"{path} 没写出来")

    def test_config_only_turns_on_load_from_remote_sources(self):
        for path in dotnet_config.write(self.dir.name, EXES):
            with self.subTest(path=path):
                root = ElementTree.parse(path).getroot()
                self.assertEqual(root.tag, "configuration")
                self.assertEqual([child.tag for child in root], ["runtime"])
                runtime = root.find("runtime")
                self.assertEqual([child.tag for child in runtime], ["loadFromRemoteSources"])
                self.assertEqual(runtime.find("loadFromRemoteSources").get("enabled"), "true")

    def test_files_are_valid_xml_without_a_byte_order_mark(self):
        for path in dotnet_config.write(self.dir.name, EXES):
            with self.subTest(path=path):
                data = Path(path).read_bytes()
                self.assertTrue(data.startswith(b"<?xml"), data[:20])


class SpecWiringTests(unittest.TestCase):
    """spec 里的这一步写错了本地全绿，只有用户解压后才发现；这里只读源码，不跑打包。"""

    def setUp(self):
        self.spec = (ROOT / "gui" / "windows.spec").read_text(encoding="utf-8")

    def test_windows_spec_writes_the_configs_where_it_collects_the_exes(self):
        self.assertRegex(self.spec, r"(?m)^(?!\s*#).*import dotnet_config",
                         "windows.spec 没有 import dotnet_config")
        collected = re.search(r"(?m)^\w+ = COLLECT\(.*\bname=(\w+)\)", self.spec)
        self.assertIsNotNone(collected, "windows.spec 里找不到 COLLECT 的目录名")
        written = re.search(r"(?m)^dotnet_config\.write\(os\.path\.join\(DISTPATH, (\w+)\)",
                            self.spec)
        self.assertIsNotNone(written, "windows.spec 没有把 config 写进收集目录")
        self.assertEqual(collected.group(1), written.group(1),
                         "config 写的目录与 COLLECT 的产物目录不是同一个")


if __name__ == "__main__":
    unittest.main()
