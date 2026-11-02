"""手动指定 adb（#311）：查找顺序、保存校验、来源标记。

adb 本体是外部边界：这里用「只认白名单里的路径」的假 adb_ok 顶替，
被测的是客户端自己的解析链与 settings.json 的读写。
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from gui import app


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.platform_tools = os.path.join(self.root, "platform-tools")
        self.downloaded = self._touch(self.platform_tools, app.adb_exe())
        self.manual = self._touch(os.path.join(self.root, "my-sdk"), app.adb_exe())
        self.env_adb = self._touch(os.path.join(self.root, "env"), app.adb_exe())

    def _touch(self, folder, name):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        open(path, "w").close()
        return path

    def find(self, manual=None, ok=lambda p: True):
        with patch.dict(os.environ, {"ADB": self.env_adb, "ADBUTILS_ADB_PATH": ""}), \
                patch("shutil.which", return_value=None), \
                patch.object(app, "adb_ok", side_effect=ok):
            return app.find_adb(self.platform_tools, manual)


class FindAdbTests(TempRoot):
    def test_manual_wins_over_downloaded_adb(self):
        self.assertEqual(self.find(self.manual), self.manual)

    def test_downloaded_wins_over_environment(self):
        self.assertEqual(self.find(None), self.downloaded)

    def test_environment_used_when_nothing_else_exists(self):
        os.remove(self.downloaded)
        self.assertEqual(self.find(None), self.env_adb)

    def test_missing_manual_path_falls_back(self):
        gone = os.path.join(self.root, "moved-away", "adb")
        self.assertEqual(self.find(gone), self.downloaded)

    def test_manual_with_old_version_falls_back(self):
        self.assertEqual(self.find(self.manual, ok=lambda p: p != self.manual), self.downloaded)


class SettingsFileTests(TempRoot):
    def data(self):
        return app.ClientData(self.root)

    def test_missing_file_reads_as_default(self):
        self.assertIsNone(self.data().setting("adb"))

    def test_written_setting_survives_a_new_client(self):
        self.data().put_setting("adb", "/sdk/platform-tools/adb")
        self.assertEqual(self.data().setting("adb"), "/sdk/platform-tools/adb")

    def test_none_removes_only_that_key(self):
        data = self.data()
        data.put_setting("adb", "/sdk/adb")
        data.put_setting("other", "keep me")
        data.put_setting("adb", None)
        self.assertIsNone(data.setting("adb"))
        self.assertEqual(data.setting("other"), "keep me")

    def test_corrupt_file_is_treated_as_empty(self):
        self.data().ensure()
        with open(self.data().settings, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(self.data().setting("adb"))
        self.data().put_setting("adb", "/sdk/adb")
        self.assertEqual(self.data().setting("adb"), "/sdk/adb")

    def test_clearing_leaves_no_settings_file(self):
        data = self.data()
        data.put_setting("adb", "/sdk/adb")
        data.put_setting("adb", None)
        self.assertFalse(os.path.exists(data.settings))
        self.assertIsNone(data.setting("adb"))

    def test_settings_file_is_json_in_the_data_root(self):
        self.data().put_setting("adb", "/sdk/adb")
        with open(os.path.join(self.root, "settings.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"adb": "/sdk/adb"})


VERSION_OUT = "Android Debug Bridge version 1.0.41\nVersion 37.0.1-1234567\n"


class SetAdbPathTests(TempRoot):
    def api(self, adb=None):
        api = app.Api(self.root, adb=adb if adb is not None else self.downloaded)
        api._adb = lambda *a, **k: VERSION_OUT
        return api

    def test_saving_a_usable_path_persists_it_and_takes_effect(self):
        api = self.api()
        with patch.object(app, "adb_ok", return_value=True):
            result = api.set_adb_path(self.manual)
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "1.0.41")
        self.assertEqual(result["source"], "manual")
        self.assertEqual(api.adb, self.manual)
        self.assertEqual(app.ClientData(self.root).setting("adb"), self.manual)

    def test_missing_file_is_rejected_and_old_setting_kept(self):
        api = self.api()
        with patch.object(app, "adb_ok", return_value=True):
            api.set_adb_path(self.manual)
            result = api.set_adb_path(os.path.join(self.root, "moved-away", "adb"))
        self.assertFalse(result["ok"])
        self.assertIn("找不到", result["error"])
        self.assertEqual(app.ClientData(self.root).setting("adb"), self.manual)
        self.assertEqual(api.adb, self.manual)

    def test_old_adb_is_rejected(self):
        api = self.api()
        with patch.object(app, "adb_ok", side_effect=lambda p: p != self.manual):
            result = api.set_adb_path(self.manual)
        self.assertFalse(result["ok"])
        self.assertIn("1.0.41", result["error"])
        self.assertIsNone(app.ClientData(self.root).setting("adb"))

    def test_relative_path_is_stored_absolute(self):
        api = self.api()
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        with patch.object(app, "adb_ok", return_value=True):
            result = api.set_adb_path(os.path.join("my-sdk", app.adb_exe()))
        self.assertTrue(result["ok"])
        self.assertTrue(os.path.isabs(app.ClientData(self.root).setting("adb")))

    def test_directory_input_gets_the_executable_appended(self):
        api = self.api()
        with patch.object(app, "adb_ok", return_value=True):
            result = api.set_adb_path(os.path.dirname(self.manual))
        self.assertTrue(result["ok"])
        self.assertEqual(app.ClientData(self.root).setting("adb"), self.manual)

    def test_clearing_goes_back_to_automatic_lookup(self):
        api = self.api()
        with patch.object(app, "adb_ok", return_value=True):
            api.set_adb_path(self.manual)
            info = api.clear_adb_path()
        self.assertIsNone(app.ClientData(self.root).setting("adb"))
        self.assertEqual(api.adb, self.downloaded)
        self.assertEqual(info["source"], "downloaded")


class AdbInfoTests(TempRoot):
    def info(self, adb, manual=None):
        api = app.Api(self.root, adb=adb)
        api._adb = lambda *a, **k: VERSION_OUT
        if manual:
            app.ClientData(self.root).put_setting("adb", manual)
        return api.adb_info()

    def test_info_reports_ok_only_when_the_version_line_parses(self):
        self.assertTrue(self.info(self.downloaded)["ok"])
        api = app.Api(self.root, adb=self.downloaded)
        api._adb = lambda *a, **k: "not an adb"
        self.assertFalse(api.adb_info()["ok"])

    def test_reports_downloaded_and_system_sources(self):
        self.assertEqual(self.info(self.downloaded)["source"], "downloaded")
        self.assertEqual(self.info("/usr/local/bin/adb")["source"], "system")
        self.assertEqual(self.info(None)["source"], "none")

    def test_manual_path_that_disappeared_falls_back_and_says_so(self):
        gone = os.path.join(self.root, "moved-away", "adb")
        info = self.info(self.downloaded, manual=gone)
        self.assertEqual(info["source"], "downloaded")
        self.assertTrue(info["manual_error"])

    def test_working_manual_path_has_no_problem_reported(self):
        info = self.info(self.manual, manual=self.manual)
        self.assertEqual(info["source"], "manual")
        self.assertEqual(info["manual_error"], "")


if __name__ == "__main__":
    unittest.main()
