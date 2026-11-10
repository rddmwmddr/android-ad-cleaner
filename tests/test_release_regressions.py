"""0.2.1：社区横屏、部分失败、通知默认选择及发布资源边界。"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "gui"))
from gui import app
import run
import chan_fast as chan
from bundle_data import bundle_data, stage
from fixtures import FakeRunner, fake_adb, load_recipe, phone_stub


def recipe(p, only="__no_steps__"):
    scope, _ = load_recipe(p, ROOT / "recipes/xiaomi-M154FF/recipe.py", only)
    return scope


class RotationTests(unittest.TestCase):
    def phone(self):
        p = phone_stub("test", d=Mock())
        p.W, p.H = 1080, 2340
        return p

    def test_landscape_right_edge_switch_is_visible_and_clickable(self):
        p = self.phone()
        p.d.window_size.return_value = (2340, 1080)
        p.d.dump_hierarchy.return_value = '''<hierarchy><node class="android.widget.Switch"
          text="热榜推荐" checkable="true" checked="true" bounds="[2040,300][2170,400]"/></hierarchy>'''
        switches = p.switches(p.tree())
        self.assertEqual(switches, [("热榜推荐", True, (2105, 350))])
        p.click(*switches[0][2])
        p.d.shell.assert_called_once_with("input swipe 2105 350 2105 350 80")

    def test_rotation_between_read_and_click_refuses_old_coordinates(self):
        p = self.phone()
        p.d.window_size.return_value = (2340, 1080)
        with self.assertRaisesRegex(RuntimeError, "旧坐标"):
            p.click(900, 600)
        p.d.shell.assert_not_called()

    def test_outside_screen_click_is_refused(self):
        p = self.phone()
        p.d.window_size.return_value = (1080, 2340)
        with self.assertRaisesRegex(RuntimeError, "屏幕外"):
            p.click(2105, 350)
        p.d.shell.assert_not_called()


class XiaomiNavigationTests(unittest.TestCase):
    def test_toolbar_image_without_clickable_flag_opens_settings(self):
        p = Mock(W=1080, H=2340)
        p.tree.return_value = ET.fromstring('''<hierarchy><node text="设置" class="android.widget.ImageView"
          clickable="false" bounds="[900,100][1020,220]"/></hierarchy>''')
        p.on_screen.return_value = True
        self.assertTrue(recipe(p)["browser_settings"]())
        p.click.assert_called_once_with(960, 160)

    def test_browser_article_is_not_my_tab(self):
        p = Mock(W=1080, H=2340)
        p.tree.return_value = ET.fromstring("<hierarchy/>")
        p.texts.return_value = [("我的", (100, 500, 500, 650), None)]
        self.assertFalse(recipe(p)["browser_settings"]())
        p.click.assert_not_called()
        p.tap.assert_not_called()

    def test_mixed_hotlist_visits_children_after_top_level_switch(self):
        p = Mock(W=1080, H=2340)
        p.locked.return_value = False
        p.switches.return_value = [("推荐", True, (900, 500))]
        p.find.side_effect = lambda text, **_: text in {"热搜", "娱乐", "话题"}
        p.tap.return_value = True
        recipe(p, "全局搜索")
        pages = [c.kwargs["page"] for c in p.off.call_args_list]
        for page in ("搜索·热搜榜单", "搜索·热榜·热搜", "搜索·热榜·娱乐", "搜索·热榜·话题"):
            self.assertIn(page, pages)


HELP = "\n".join("  " + name for name in (
    "set-package-networking-enabled [true|false] [package name]",
    "get-package-networking-enabled [package name]", "set-chain3-enabled [true|false]", "get-chain3-enabled"))


class MsaTests(unittest.TestCase):
    def setUp(self):
        fake_adb(self)

    def test_old_android_missing_interface_does_not_issue_writes(self):
        with patch.object(run, "sh_all", return_value="Connectivity service commands:\n  help") as shell:
            result = run.msa_net("test", False)
        self.assertFalse(result["supported"])
        self.assertFalse(result["ok"])
        shell.assert_called_once_with("test", "cmd connectivity help")

    def test_hyperos_package_and_chain_readback(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "chain:disabled", "Disabled networking", "",
                                                      run.MSA + ":deny", "chain:enabled"]):
            result = run.msa_net("test", False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["chain3"], "disabled")

    def test_allow_restore_does_not_disable_shared_chain(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "", run.MSA + ":allow"]) as shell:
            self.assertTrue(run.msa_net("test", True)["ok"])
        self.assertFalse(any("set-chain3" in c.args[1] for c in shell.call_args_list))

    def test_disabled_chain_is_not_success(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "chain:disabled", "", "",
                                                      run.MSA + ":deny", "chain:disabled"]):
            self.assertFalse(run.msa_net("test", False)["ok"])

    def test_error_with_false_word_is_not_boolean_success(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "chain:disabled", "", "", "Error: false is invalid"]):
            self.assertFalse(run.msa_net("test", False)["ok"])

    def test_permission_denied_stops_following_network_writes(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "chain:disabled", "Permission denied"]) as shell:
            self.assertFalse(run.msa_net("test", False)["ok"])
        self.assertEqual(shell.call_count, 3)

    def test_partial_suspend_keeps_restore_record_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run, "latest_backup", return_value=directory), \
             patch.object(run, "suspended", return_value=True), \
             patch.object(run, "sh_all", return_value="success"), patch.object(run, "sh"), \
             patch.object(run, "msa_net", return_value={"ok": False, "supported": True, "chain3": "", "reason": "系统拒绝"}), \
             patch.object(sys, "argv", ["run.py", "-s", "test", "suspend", run.MSA]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run.main(), 1)
            self.assertIn("部分完成", output.getvalue())
            self.assertIn(run.MSA, Path(directory, "suspended.txt").read_text())

    def test_missing_network_interface_is_not_a_failure(self):
        # 错误日志 10-27：7 份小米报告因系统没有断网接口被标成失败，用户改不了
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run, "latest_backup", return_value=directory), \
             patch.object(run, "suspended", return_value=True), \
             patch.object(run, "sh_all", return_value="success"), patch.object(run, "sh"), \
             patch.object(run, "msa_net", return_value={"ok": False, "supported": False, "chain3": "", "reason": "不支持断网"}), \
             patch.object(sys, "argv", ["run.py", "-s", "test", "suspend", run.MSA]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            run.main()
            self.assertIn("只做了挂起", output.getvalue())
            self.assertIn(run.MSA, Path(directory, "suspended.txt").read_text())


class GlobalMsaNetTests(unittest.TestCase):
    """海外版 HyperOS 的 msa 是 com.miui.msa.global（Redmi Note 13 俄区实测）：
    挂起后照样断网，断网和回读的命令写的是这个包名，不是国行的 run.MSA。"""

    GLOBAL = "com.miui.msa.global"

    def test_network_commands_name_the_global_package(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "chain:disabled", "Disabled networking", "",
                                                      self.GLOBAL + ":deny", "chain:enabled"]) as shell:
            self.assertTrue(run.msa_net("test", False, self.GLOBAL)["ok"])
        sent = [c.args[1] for c in shell.call_args_list]
        self.assertIn("cmd connectivity set-package-networking-enabled false " + self.GLOBAL, sent)
        self.assertIn("cmd connectivity get-package-networking-enabled " + self.GLOBAL, sent)
        self.assertFalse(any(run.MSA in c for c in sent))

    def test_suspend_global_msa_also_cuts_network(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run, "latest_backup", return_value=directory), \
             patch.object(run, "suspended", return_value=True), \
             patch.object(run, "sh_all", return_value="success"), patch.object(run, "sh"), \
             patch.object(run, "msa_net", autospec=True,
                          return_value={"ok": True, "supported": True, "chain3": "", "reason": ""}) as net, \
             patch.object(sys, "argv", ["run.py", "-s", "test", "suspend", self.GLOBAL]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run.main(), 0)
        net.assert_called_once_with("test", False, self.GLOBAL, chain3="")
        self.assertIn("已禁止联网", output.getvalue())

    def test_unsuspend_global_msa_restores_network(self):
        with patch.object(run, "suspended", return_value=False), patch.object(run, "sh"), \
             patch.object(run, "msa_net", autospec=True,
                          return_value={"ok": True, "supported": True, "chain3": "", "reason": ""}) as net, \
             patch.object(sys, "argv", ["run.py", "-s", "test", "unsuspend", self.GLOBAL]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(), 0)
        net.assert_called_once_with("test", True, self.GLOBAL, chain3="")


class Chain3RestoreTests(unittest.TestCase):
    """#945：挂起 msa 时 set-chain3-enabled 是设备级副作用，解除挂起要按挂起前的原值写回。"""

    def setUp(self):
        fake_adb(self)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.backup = Path(self.dir.name, "xiaomi-test")
        self.backup.mkdir()

    def _shell(self, chain, deny="", chain_readback=True, watching=None):
        """按命令内容回假结果，并把每次下发记进 self.sent（顺序即证据）。"""
        state = {"chain": chain, "net": {}}
        self.sent = []
        self.files_at_chain3_write = None

        def shell(_serial, cmd):
            self.sent.append(cmd)
            parts = cmd.split()
            if "connectivity help" in cmd:
                return HELP
            if deny and deny in cmd:
                return "Permission denied"
            if "set-chain3-enabled" in parts:
                if watching:
                    self.files_at_chain3_write = sorted(p.name for p in Path(watching).glob("chain3-setting*.json"))
                state["chain"] = "chain:enabled" if parts[-1] == "true" else "chain:disabled"
                return ""
            if "get-chain3-enabled" in parts:
                return state["chain"] if chain_readback else ""
            if "set-package-networking-enabled" in parts:
                state["net"][parts[-1]] = "allow" if parts[-2] == "true" else "deny"
                return ""
            if "get-package-networking-enabled" in parts:
                pkg = parts[-1]
                return f"{pkg}:{state['net'].get(pkg, 'allow')}"
            return ""

        return shell

    def _suspend(self, backup=None, chain="chain:disabled", chain_readback=True, watching=None, device_serial=""):
        with patch.object(run, "BACKUPS", self.dir.name), \
             patch.object(run, "prop", return_value=device_serial), \
             patch.object(run, "latest_backup", return_value=str(backup or self.backup)), \
             patch.object(run, "suspended", return_value=True), \
             patch.object(run, "sh") as self.sh, \
             patch.object(run, "sh_all", side_effect=self._shell(chain, chain_readback=chain_readback, watching=watching)), \
             patch.object(sys, "argv", ["run.py", "-s", "test", "suspend", run.MSA]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            return run.main(), output.getvalue()

    def _unsuspend(self, chain="chain:enabled", deny="", suspended=False, device_serial=""):
        with patch.object(run, "BACKUPS", self.dir.name), \
             patch.object(run, "prop", return_value=device_serial), \
             patch.object(run, "suspended", return_value=suspended), \
             patch.object(run, "sh") as self.sh, \
             patch.object(run, "sh_all", side_effect=self._shell(chain, deny)), \
             patch.object(sys, "argv", ["run.py", "-s", "test", "unsuspend", run.MSA]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            return run.main(), output.getvalue()

    def _record(self, original, serial="test", name="chain3-setting.json"):
        Path(self.backup, name).write_text(json.dumps({"serial": serial, "original": original}))

    def test_suspend_reads_chain3_before_turning_it_on(self):
        code, _ = self._suspend()
        self.assertEqual(code, 0)
        self.assertLess(self.sent.index("cmd connectivity get-chain3-enabled"),
                        self.sent.index("cmd connectivity set-chain3-enabled true"))

    def test_suspend_writes_record_before_turning_chain3_on(self):
        self._suspend(watching=self.backup)
        self.assertEqual(self.files_at_chain3_write, ["chain3-setting.json"])

    def test_suspend_forces_stop_and_records_original(self):
        self._suspend()
        self.sh.assert_any_call("test", f"am force-stop {run.MSA}")
        data = json.loads(Path(self.backup, "chain3-setting.json").read_text())
        self.assertEqual(data, {"serial": "test", "original": "disabled"})

    def test_unreadable_chain3_is_not_recorded(self):
        code, output = self._suspend(chain_readback=False)
        self.assertEqual(code, 1)
        self.assertIn("读不到 chain3 原值", output)
        self.assertFalse(any("set-chain3-enabled" in command for command in self.sent))
        self.assertFalse(any("set-package-networking-enabled" in command for command in self.sent))
        self.assertFalse(Path(self.backup, "chain3-setting.json").exists())

    def test_repeat_suspend_keeps_first_original(self):
        self._suspend()
        later = Path(self.dir.name, "xiaomi-later")
        later.mkdir()
        self._suspend(later, chain="chain:enabled")
        self.assertEqual(json.loads(Path(self.backup, "chain3-setting.json").read_text())["original"], "disabled")
        self.assertFalse(Path(later, "chain3-setting.json").exists())

    def test_wireless_debug_reuses_device_serial(self):
        # 无线调试的 adb serial 是 IP:端口，重连就变；记录要认设备自己的序列号
        self._suspend(device_serial="ABC123")
        self.assertEqual(json.loads(Path(self.backup, "chain3-setting.json").read_text())["serial"], "ABC123")
        code, _ = self._unsuspend("chain:enabled", device_serial="ABC123")
        self.assertEqual(code, 0)
        self.assertIn("cmd connectivity set-chain3-enabled false", self.sent)

    def test_unsuspend_writes_back_disabled_original(self):
        self._record("disabled")
        code, _ = self._unsuspend("chain:enabled")
        self.assertEqual(code, 0)
        self.assertIn("cmd connectivity set-chain3-enabled false", self.sent)
        self.assertFalse(Path(self.backup, "chain3-setting.json").exists())

    def test_unsuspend_keeps_enabled_original(self):
        self._record("enabled")
        code, _ = self._unsuspend("chain:enabled")
        self.assertEqual(code, 0)
        self.assertIn("cmd connectivity set-chain3-enabled true", self.sent)
        self.assertFalse(Path(self.backup, "chain3-setting.json").exists())

    def test_unsuspend_without_record_leaves_chain3_alone(self):
        code, _ = self._unsuspend()
        self.assertEqual(code, 0)
        self.assertFalse(any("chain3" in command for command in self.sent))

    def test_other_device_record_is_not_restored(self):
        self._record("disabled", serial="another-device")
        code, _ = self._unsuspend("chain:enabled")
        self.assertEqual(code, 0)
        self.assertFalse(any("chain3" in command for command in self.sent))
        self.assertTrue(Path(self.backup, "chain3-setting.json").exists())

    def test_failed_chain3_restore_keeps_record(self):
        self._record("disabled")
        code, output = self._unsuspend("chain:enabled", deny="set-chain3-enabled")
        self.assertEqual(code, 1)
        self.assertIn("联网还原失败", output)
        self.assertTrue(Path(self.backup, "chain3-setting.json").exists())

    def test_still_suspended_package_keeps_record(self):
        self._record("disabled")
        code, _ = self._unsuspend("chain:enabled", suspended=True)
        self.assertEqual(code, 1)
        self.assertTrue(Path(self.backup, "chain3-setting.json").exists())

    def test_unsuspend_sends_the_unsuspend_command(self):
        code, _ = self._unsuspend("chain:enabled")
        self.assertEqual(code, 0)
        self.sh.assert_any_call("test", f"pm unsuspend --user 0 {run.MSA}")

    def test_corrupt_record_is_skipped_not_fatal(self):
        Path(self.backup, "chain3-setting.json").write_text('{"serial": "te')
        code, _ = self._unsuspend("chain:enabled")
        self.assertEqual(code, 0)
        self.assertFalse(any("chain3" in command for command in self.sent))
        self.assertTrue(Path(self.backup, "chain3-setting.json").exists())

    def test_corrupt_record_does_not_hide_a_good_one(self):
        older = Path(self.dir.name, "xiaomi-older")
        older.mkdir()
        Path(older, "chain3-setting.json").write_text(json.dumps({"serial": "test", "original": "disabled"}))
        Path(self.backup, "chain3-setting-corrupt.json").write_text("{")
        code, _ = self._unsuspend("chain:enabled")
        self.assertEqual(code, 0)
        self.assertIn("cmd connectivity set-chain3-enabled false", self.sent)

    def test_same_model_second_device_gets_its_own_record(self):
        with patch.object(run, "BACKUPS", self.dir.name):
            first = run.chain3_remember("AAA", str(self.backup), "disabled")
            second = run.chain3_remember("BBB", str(self.backup), "enabled")
            self.assertEqual(Path(first).name, "chain3-setting.json")
            self.assertEqual(Path(second).name, "chain3-setting-BBB.json")
            self.assertEqual(run.chain3_record("AAA")[1]["original"], "disabled")
            self.assertEqual(run.chain3_record("BBB")[1]["original"], "enabled")

    def test_wireless_serial_never_reaches_the_filename(self):
        self._record("disabled", serial="another-device")
        with patch.object(run, "BACKUPS", self.dir.name):
            path = run.chain3_remember("192.168.1.10:5555", str(self.backup), "disabled")
        self.assertEqual(Path(path).name, "chain3-setting-192.168.1.10_5555.json")


class NotificationSelectionTests(unittest.TestCase):
    def test_scan_excludes_honor_service_channels(self):
        names = ["警告", "实时活动", "赛事资讯", "护眼推荐", "活动优惠"]
        data = {("com.example", "recommend_" + str(i)): (name, 3, False) for i, name in enumerate(names)}
        with patch.object(chan, "Phone"), patch.object(chan, "parse", return_value=(data, {})), \
             patch.object(chan, "phone_model", return_value=""), patch.object(chan, "keep_awake", return_value=None), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "scan"]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            chan.main()
        self.assertEqual(output.getvalue(), "com.example\trecommend_4\t活动优惠\n")

    def test_gui_does_not_preselect_ambiguous_channels(self):
        names = ["其他", "普通通知", "推送通知", "清理加速", "个性化提示", "活动优惠"]
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory, runner=FakeRunner(
                runs=("\n".join(f"com.example\tpromo{i}\t{name}" for i, name in enumerate(names)), "", 0)))
            rows = api.chan_scan("test")["chans"]
        self.assertEqual([r["name"] for r in rows if r["checked"]], ["活动优惠"])


class BundleTests(unittest.TestCase):
    def test_only_public_runtime_assets_are_staged(self):
        with tempfile.TemporaryDirectory() as directory:
            root, out = Path(directory, "source"), Path(directory, "stage")
            public = {"tool/run.py", "recipes/xiaomi-test/recipe.py", "gui/web/index.html", "gui/web/img/guide.png", "images/guide.png"}
            private = {"recipes/xiaomi-test/run-log.txt", "recipes/zztest-device/recipe.py", "tool/__pycache__/secret.pyc",
                       "gui/web/private.txt", "backups/phone.json", "images/private.txt"}
            for name in public | private:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            self.assertEqual({Path(src).relative_to(root.resolve()).as_posix() for src, _ in bundle_data(root)}, public)
            stage(root, out)
            self.assertEqual({p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}, public)

    def test_every_file_under_gui_web_is_staged(self):
        # 页面用 file:// 从同目录取资源：不在白名单里的文件发出去就是 404，桌面版一点就炸（#665 的 core.js）
        staged = {Path(src).relative_to(ROOT).as_posix() for src, _ in bundle_data(ROOT)}
        on_disk = {p.relative_to(ROOT).as_posix() for p in (ROOT / "gui" / "web").rglob("*") if p.is_file()}
        self.assertEqual(on_disk - staged, set())


if __name__ == "__main__":
    unittest.main()
