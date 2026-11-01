"""错误日志上报：内容脱敏、预览与发送一致、限频、安装编号、服务器回应处理。不联网。"""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from fixtures import job_stub
from gui import app

ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.api = self.app.Api(self.dir.name)
        home = str(Path.home())
        self.api.last_status = {"info": {"brand": "Xiaomi", "name": "Xiaomi 17", "model": "25113PN0EC",
                                         "os": "OS3.0.40.0", "build": "BP2A", "android": "16"}}
        self.api.job = job_stub(serial="TESTSERIAL01", results=[
            {"title": "关闭营销通知", "rc": 1, "sec": 12},
            {"title": "收尾", "rc": 0, "sec": 1},
            {"title": "关闭各 App 里的广告开关", "rc": 3, "sec": 0, "skipped": True}],
            lines=["▶ 关闭营销通知", f"device 'TESTSERIAL01' 读取 {home}/AppData/x", "联系 a.b@qq.com 13900001111",
                   "adb connect 192.0.2.10:5555"])

    def test_payload_scrubs_private_values(self):
        payload = self.api.report_payload()
        text = json.dumps(payload, ensure_ascii=False)
        for secret in ("TESTSERIAL01", str(Path.home()), "a.b@qq.com", "13900001111", "192.0.2.10"):
            self.assertNotIn(secret, text)
        for mark in ("<序列号>", "<用户目录>", "<邮箱>", "<手机号>", "<IP>"):
            self.assertIn(mark, payload["log"])
        self.assertEqual([s["result"] for s in payload["steps"]], ["失败", "成功", "跳过"])
        self.assertNotIn("install_id", payload)

    def test_payload_fits_server_limits(self):
        self.api.job.lines = ["x" * 500] * 200
        self.api.job.results = [{"title": "步骤" * 30, "rc": 0, "sec": 1}] * 20
        payload = self.api.report_payload()
        self.assertLessEqual(len(payload["log"]), 20000)
        self.assertEqual(len(payload["steps"]), 12)
        self.assertTrue(all(len(s["title"]) <= 40 for s in payload["steps"]))
        self.assertLess(len(json.dumps(payload, ensure_ascii=False).encode()), 64 * 1024)

    def test_send_posts_preview_plus_install_id(self):
        payload = self.api.report_payload()
        sent = {}

        def fake(request, timeout):
            sent["body"] = json.loads(request.data.decode("utf-8"))
            sent["url"] = request.full_url
            return Response(json.dumps({"status": "ok", "id": "abc"}).encode())
        with patch.object(self.app.urllib.request, "urlopen", side_effect=fake):
            self.assertEqual(self.api.send_report(payload), {"ok": True, "id": "abc"})
        install = sent["body"].pop("install_id")
        self.assertEqual(sent["body"], payload)
        self.assertEqual(sent["url"], self.app.REPORT_URL)
        self.assertEqual(Path(self.dir.name, "install-id").read_text(), install)
        self.assertEqual(self.api._install_id(), install)              # 同一台电脑沿用

    def test_invalid_install_id_file_is_replaced(self):
        Path(self.dir.name, "install-id").write_text("serial-or-junk")
        value = self.api._install_id()
        self.assertNotEqual(value, "serial-or-junk")
        self.assertRegex(value, r"^[0-9a-f-]{36}$")

    def test_install_id_creates_the_data_directory_it_writes_into(self):
        # 以前靠 import 期建好目录；现在只有 ensure() 会建，缺了它这里就写不进去
        missing = Path(self.dir.name, "not-created-yet")
        api = self.app.Api(str(missing))
        self.assertFalse(missing.exists())
        self.assertRegex(api._install_id(), r"^[0-9a-f-]{36}$")
        self.assertTrue(Path(missing, "install-id").exists())

    def test_local_hourly_limit(self):
        payload = self.api.report_payload()
        reply = lambda *a, **k: Response(json.dumps({"status": "ok", "id": "x"}).encode())
        with patch.object(self.app.urllib.request, "urlopen", side_effect=reply) as call:
            for _ in range(3):
                self.assertTrue(self.api.send_report(payload)["ok"])
            self.assertIn("最多上报", self.api.send_report(payload)["error"])
        self.assertEqual(call.call_count, 3)

    def test_server_rate_limit_and_errors_are_explained(self):
        payload = self.api.report_payload()
        limited = urllib.error.HTTPError(self.app.REPORT_URL, 429, "Too Many", {}, io.BytesIO(b'{"status":"limited"}'))
        with patch.object(self.app.urllib.request, "urlopen", side_effect=limited):
            self.assertIn("太频繁", self.api.send_report(payload)["error"])
        bad = urllib.error.HTTPError(self.app.REPORT_URL, 400, "Bad", {}, io.BytesIO('{"message":"安装编号格式不对"}'.encode()))
        with patch.object(self.app.urllib.request, "urlopen", side_effect=bad):
            self.assertIn("安装编号格式不对", self.api.send_report(payload)["error"])
        with patch.object(self.app.urllib.request, "urlopen", side_effect=urllib.error.URLError("timed out")):
            self.assertIn("连不上", self.api.send_report(payload)["error"])
        self.assertEqual(self.api.report_times, [])                    # 失败不占本地额度

    def test_duplicate_is_not_an_error(self):
        reply = lambda *a, **k: Response(b'{"status":"duplicate"}')
        with patch.object(self.app.urllib.request, "urlopen", side_effect=reply):
            self.assertEqual(self.api.send_report(self.api.report_payload()), {"ok": True, "duplicate": True})


SERVER = ROOT / ".private/aac-report"      # 服务端代码只在维护者本机，不进仓库


@unittest.skipUnless((SERVER / "index.ts").exists(), "服务端代码不在仓库里")
class ServerContractTests(unittest.TestCase):
    """客户端字段上限与服务端一致。"""

    def test_limits_match_edge_function_and_schema(self):
        ts = (SERVER / "index.ts").read_text(encoding="utf-8")
        sql = (SERVER / "schema.sql").read_text(encoding="utf-8")
        for field, limit in (("client_version", 32), ("platform", 80), ("phone_brand", 40), ("phone_model", 80),
                             ("phone_system", 160), ("android", 16), ("log", 20000)):
            self.assertIn(f"{field}: {limit}", ts)
            self.assertRegex(sql, rf"{field}.*{limit}")
        self.assertIn("MAX_STEPS = 12", ts)
        self.assertIn("revoke all on aac.error_reports from public, anon, authenticated, service_role", sql)


if __name__ == "__main__":
    unittest.main()
