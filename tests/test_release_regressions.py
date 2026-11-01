"""0.2.1：社区横屏、部分失败、通知默认选择及发布资源边界。"""
import contextlib
import io
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
import fast
import run
import chan_fast as chan
from bundle_data import bundle_data, stage
from fixtures import fake_adb, phone_stub


def recipe(p, only="__no_steps__"):
    scope = {"p": p, "ONLY": [only]}
    path = ROOT / "recipes/xiaomi-M154FF/recipe.py"
    with patch.object(fast.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
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
        with patch.object(fast.time, "sleep"):
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
        with patch.object(run, "sh_all", side_effect=[HELP, "Disabled networking", "", run.MSA + ":deny", "chain:enabled"]):
            self.assertTrue(run.msa_net("test", False)["ok"])

    def test_allow_restore_does_not_disable_shared_chain(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "", run.MSA + ":allow"]) as shell:
            self.assertTrue(run.msa_net("test", True)["ok"])
        self.assertFalse(any("set-chain3" in c.args[1] for c in shell.call_args_list))

    def test_disabled_chain_is_not_success(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "", "", run.MSA + ":deny", "chain:disabled"]):
            self.assertFalse(run.msa_net("test", False)["ok"])

    def test_error_with_false_word_is_not_boolean_success(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "", "", "Error: false is invalid"]):
            self.assertFalse(run.msa_net("test", False)["ok"])

    def test_permission_denied_stops_following_network_writes(self):
        with patch.object(run, "sh_all", side_effect=[HELP, "Permission denied"]) as shell:
            self.assertFalse(run.msa_net("test", False)["ok"])
        self.assertEqual(shell.call_count, 2)

    def test_partial_suspend_keeps_restore_record_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run, "latest_backup", return_value=directory), \
             patch.object(run, "suspended", return_value=True), \
             patch.object(run, "sh_all", return_value="success"), patch.object(run, "sh"), \
             patch.object(run, "msa_net", return_value={"ok": False, "supported": True, "reason": "系统拒绝"}), \
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
             patch.object(run, "msa_net", return_value={"ok": False, "supported": False, "reason": "不支持断网"}), \
             patch.object(sys, "argv", ["run.py", "-s", "test", "suspend", run.MSA]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            run.main()
            self.assertIn("只做了挂起", output.getvalue())
            self.assertIn(run.MSA, Path(directory, "suspended.txt").read_text())


class NotificationSelectionTests(unittest.TestCase):
    def test_scan_excludes_honor_service_channels(self):
        names = ["警告", "实时活动", "赛事资讯", "护眼推荐", "活动优惠"]
        data = {("com.example", "recommend_" + str(i)): (name, 3, False) for i, name in enumerate(names)}
        with patch.object(chan, "Phone"), patch.object(chan, "parse", return_value=(data, {})), patch.object(chan, "keep_awake", return_value=None), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "scan"]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            chan.main()
        self.assertEqual(output.getvalue(), "com.example\trecommend_4\t活动优惠\n")

    def test_gui_does_not_preselect_ambiguous_channels(self):
        names = ["其他", "普通通知", "推送通知", "清理加速", "个性化提示", "活动优惠"]
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            api._run = Mock(return_value=("\n".join(f"com.example\tpromo{i}\t{name}" for i, name in enumerate(names)), "", 0))
            rows = api.chan_scan("test")
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


if __name__ == "__main__":
    unittest.main()
