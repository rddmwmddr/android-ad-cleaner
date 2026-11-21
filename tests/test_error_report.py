"""错误日志上报：内容脱敏、预览与发送一致、限频、安装编号、服务器回应处理。不联网。"""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from fixtures import job_stub
from gui import app, reporter

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


class ReporterInjectionTests(unittest.TestCase):
    """上报块从 `gui/app.py` 搬出去之后，常量与协作者由构造方给（#1384）。

    版本号、上报地址、空报告文案、限频、宿主措辞与排查提示都不该再读 `gui/app.py` 的模块全局：
    换成一组不像真值的输入，就能看出它们是不是真的从构造参数来。
    """

    class Help:
        UI_RECOVERY = "关掉读屏占用再试"

        @staticmethod
        def is_ui_connection_error(detail):
            return "UIAUTOMATION_BUSY" in detail

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.reporter = reporter.Reporter(
            app.ClientData(self.dir.name), version="9.9.9",
            report_url="https://example.invalid/aac-report", empty_report="空报告（试验）",
            limit=1, os_name=lambda: "试验机", help_of=lambda: self.Help)

    def view(self, **fields):
        return {"serial": None, "lines": [], "results": [], "payloads": [], **fields}

    def test_the_empty_report_sentence_comes_from_the_constructor(self):
        # 网络出口也桩掉：判空的变异要是放行，这一条要红在断言上，而不是真的去打服务器
        reply = lambda *a, **k: Response(b'{"status":"ok","id":"x"}')
        with patch.object(reporter.urllib.request, "urlopen", side_effect=reply):
            self.assertEqual(self.reporter.send_report({"steps": [], "log": "  "}),
                             {"error": "空报告（试验）"})

    def test_the_version_and_the_platform_words_come_from_the_constructor(self):
        payload = self.reporter.report_payload({"info": {"brand": "X"}}, self.view())
        self.assertEqual(payload["client_version"], "9.9.9")
        self.assertTrue(payload["platform"].startswith("试验机（"), payload["platform"])

    def test_sending_uses_the_constructor_url_and_hourly_limit(self):
        payload = self.reporter.report_payload({"info": {}}, self.view(lines=["▶ 收尾"]))
        seen = []

        def fake(request, timeout):
            seen.append(request.full_url)
            return Response(json.dumps({"status": "ok", "id": "x"}).encode())
        with patch.object(reporter.urllib.request, "urlopen", side_effect=fake):
            self.assertTrue(self.reporter.send_report(payload)["ok"])
            second = self.reporter.send_report(payload)
        self.assertEqual(seen, ["https://example.invalid/aac-report"])
        self.assertIn("最多上报 1 次", second["error"])

    def test_the_recovery_sentence_comes_from_the_injected_help(self):
        result = self.reporter.remember_error("读屏检查", None, "boom: UIAUTOMATION_BUSY")
        self.assertEqual(result["recovery"], self.Help.UI_RECOVERY)
        self.assertEqual(result["error"], self.Help.UI_RECOVERY + "\n\nboom: UIAUTOMATION_BUSY")
        self.assertEqual(result["detail"], "boom: UIAUTOMATION_BUSY")
        self.assertNotIn("recovery", self.reporter.remember_error("读屏检查", None, "普通异常"))

    def test_the_payload_is_exactly_the_server_schema(self):
        view = self.view(lines=["▶ 收尾", "已经干净"], results=[
            {"title": "关闭营销通知", "rc": 1, "sec": 12},
            {"title": "收尾", "rc": 0, "sec": 1},
            {"title": "关闭各 App 里的广告开关", "rc": 3, "sec": 0, "skipped": True},
            {"title": "被停止的步骤", "rc": 0, "sec": 2, "stopped": True}])
        payload = self.reporter.report_payload(
            {"info": {"brand": "Xiaomi", "name": "Xiaomi 17", "model": "25113PN0EC",
                      "os": "OS3.0.40.0", "build": "BP2A", "android": "16"}}, view)
        self.assertEqual(payload, {
            "client_version": "9.9.9",
            "platform": f"试验机（{reporter.platform.machine()}）",
            "phone_brand": "Xiaomi",
            "phone_model": "Xiaomi 17",
            "phone_system": "OS3.0.40.0",
            "android": "16",
            "steps": [
                {"title": "关闭营销通知", "sec": 12, "result": "失败"},
                {"title": "收尾", "sec": 1, "result": "成功"},
                {"title": "关闭各 App 里的广告开关", "sec": 0, "result": "跳过"},
                {"title": "被停止的步骤", "sec": 2, "result": "已停止"}],
            "log": "▶ 收尾\n已经干净",
        })

    def test_the_payload_falls_back_within_each_phone_column(self):
        # 没有视图里的三个列表键时按空处理；型号回落到 model、系统回落到 build
        payload = self.reporter.report_payload({"info": {"model": "25113PN0EC", "build": "BP2A"}},
                                               {"serial": None})
        self.assertEqual((payload["phone_brand"], payload["phone_model"], payload["phone_system"],
                          payload["android"], payload["steps"], payload["log"]),
                         ("", "25113PN0EC", "BP2A", "", [], ""))

    def test_missing_phone_columns_stay_empty(self):
        payload = self.reporter.report_payload({"info": {}}, {"serial": None})
        self.assertEqual([payload[key] for key in ("phone_brand", "phone_model", "phone_system", "android")],
                         ["", "", "", ""])

    def test_the_phone_columns_are_cut_at_the_server_limits(self):
        info = {"brand": "B" * 41, "name": "M" * 81, "os": "O" * 161, "android": "1" * 17}
        payload = self.reporter.report_payload({"info": info}, {"serial": None})
        self.assertEqual([payload[key] for key in ("phone_brand", "phone_model", "phone_system", "android")],
                         ["B" * 40, "M" * 80, "O" * 160, "1" * 16])

    def test_the_platform_column_is_cut_at_eighty_characters(self):
        long_name = reporter.Reporter(
            app.ClientData(self.dir.name), version="9.9.9", report_url="https://example.invalid/aac-report",
            empty_report="空报告（试验）", limit=1, os_name=lambda: "长" * 100, help_of=lambda: self.Help)
        payload = long_name.report_payload({}, {"serial": None})
        self.assertEqual(payload["platform"], f"{'长' * 100}（{reporter.platform.machine()}）"[:80])

    def test_a_remembered_failure_is_appended_after_the_log(self):
        self.reporter.remember_error("读屏检查", None, "RuntimeException: boom")
        payload = self.reporter.report_payload({"info": {}}, self.view(lines=["▶ 收尾", "已经干净"]))
        self.assertEqual(payload["log"],
                         "▶ 收尾\n已经干净\n\n[最近失败：读屏检查]\nRuntimeException: boom")

    def test_diagnostic_payloads_are_appended_after_the_log(self):
        payload = self.reporter.report_payload({}, self.view(lines=["▶ 收尾"], payloads=["骨架甲", "  ", "骨架乙"]))
        self.assertEqual(payload["log"], "▶ 收尾\n\n[诊断载荷]\n骨架甲\n骨架乙")

    def test_the_log_keeps_only_the_last_twenty_thousand_characters(self):
        line = "开" + "中" * 20000
        payload = self.reporter.report_payload({}, {"serial": None, "lines": [line]})
        self.assertEqual(payload["log"], line[-20000:])

    def test_scrub_replaces_a_windows_home_and_its_escaped_form(self):
        home, serial = "E:\\Data\\rikki", "AB\\CD"

        def escaped(text):
            return text.replace("\\", "\\\\")
        text = f"日志写在 {home}/logs 与 {escaped(home)}/logs；序列号 {serial} 与 {escaped(serial)}"
        with patch.object(reporter.os.path, "expanduser", side_effect=lambda path: home if path == "~" else path):
            self.assertEqual(reporter.scrub(text, serial),
                             "日志写在 <用户目录>/logs 与 <用户目录>/logs；序列号 <序列号> 与 <序列号>")

    def test_a_remembered_failure_scrubs_the_serial_and_the_home(self):
        home, serial = "E:\\Data\\rikki", "SER\\01"

        def escaped(text):
            return text.replace("\\", "\\\\")
        detail = f"日志写在 {home}/logs 与 {escaped(home)}/logs；序列号 {serial} 与 {escaped(serial)}"
        with patch.object(reporter.os.path, "expanduser", side_effect=lambda path: home if path == "~" else path):
            result = self.reporter.remember_error("读屏检查", serial, detail)
        self.assertEqual(result["detail"],
                         "日志写在 <用户目录>/logs 与 <用户目录>/logs；序列号 <序列号> 与 <序列号>")
        self.assertEqual(self.reporter.last_error, {"operation": "读屏检查", "detail": result["detail"]})

    def test_the_summary_keeps_exception_lines_and_drops_stack_frames(self):
        detail = ("普通一行\n"
                  "java.lang.RuntimeException: boom\n"
                  "    at com.foo.ExceptionMaker.make(ExceptionMaker.java:1)\n"
                  "Caused by: 权限不足")
        self.assertEqual(self.reporter.remember_error("读屏检查", None, detail)["error"],
                         "java.lang.RuntimeException: boom\nCaused by: 权限不足")

    def test_the_summary_only_matches_cause_words_in_the_documented_case(self):
        for detail in ("普通一行\nerror: 小写", "普通一行\nERROR: 大写"):
            self.assertEqual(self.reporter.remember_error("x", None, detail)["error"], detail)

    def test_the_summary_keeps_at_most_four_causes(self):
        detail = "\n".join(f"Error {i}" for i in range(5)) + "\n非原因"
        self.assertEqual(self.reporter.remember_error("x", None, detail)["error"],
                         "Error 0\nError 1\nError 2\nError 3")

    def test_long_details_are_cut_at_six_hundred_characters(self):
        six_hundred = "甲" * 600
        self.assertEqual(self.reporter.remember_error("x", None, six_hundred)["error"], six_hundred)
        self.assertEqual(self.reporter.remember_error("x", None, "甲" * 601)["error"], "甲" * 600 + "…")

    def test_the_error_text_is_cut_at_a_thousand_characters(self):
        exactly = "Error:" + "乙" * 994
        self.assertEqual(self.reporter.remember_error("x", None, exactly)["error"], exactly)
        over = "Error:" + "乙" * 995
        self.assertEqual(self.reporter.remember_error("x", None, over)["error"],
                         over[:1000] + "…（完整原因见诊断）")

    def test_the_last_error_is_saved_and_rewritten_for_the_next_failure(self):
        folder = Path(self.dir.name, "logs")
        logs = folder / "last-error.txt"
        self.reporter.remember_error("读屏检查", None, "第一行\n第二行")
        self.assertEqual([path.name for path in folder.iterdir()], ["last-error.txt"])   # 文件名大小写也要对（APFS 不区分）
        self.assertEqual(logs.read_text(encoding="utf-8"), "客户端 9.9.9 · 读屏检查\n第一行\n第二行\n")
        # 按字节写、不转平台换行：Windows 上也必须是 LF，文本模式的 read_text 会把 CRLF 读回 LF，看不住
        self.assertEqual(logs.read_bytes(), "客户端 9.9.9 · 读屏检查\n第一行\n第二行\n".encode())
        self.assertEqual(self.reporter.last_error, {"operation": "读屏检查", "detail": "第一行\n第二行"})
        self.reporter.remember_error("连接手机", None, "更新后的原因")
        self.assertEqual(logs.read_text(encoding="utf-8"), "客户端 9.9.9 · 连接手机\n更新后的原因\n")

    def test_the_request_is_a_post_with_json_headers_and_the_constructor_url(self):
        payload = self.reporter.report_payload({}, self.view(lines=["▶ 收尾"]))
        sent = {}

        def fake(request, timeout):
            sent.update(method=request.method, content_type=request.get_header("Content-type"),
                        agent=request.get_header("User-agent"), timeout=timeout,
                        body=json.loads(request.data.decode("utf-8")), raw=request.data)
            return Response(json.dumps({"status": "ok", "id": "abc"}).encode())
        with patch.object(reporter.urllib.request, "urlopen", side_effect=fake):
            self.assertEqual(self.reporter.send_report(payload), {"ok": True, "id": "abc"})
        install = sent["body"].pop("install_id")
        self.assertEqual(sent["body"], payload)
        # `Request.method` 是显式的 POST；`get_method()` 会把 None 按带 data 兜底成 POST，看不住这一层
        self.assertEqual((sent["method"], sent["content_type"], sent["agent"], sent["timeout"]),
                         ("POST", "application/json", "AndroidAdCleaner/9.9.9", 45))
        self.assertIn("▶ 收尾".encode(), sent["raw"], "ensure_ascii 关掉，中文原样进 body")
        self.assertEqual(Path(self.dir.name, "install-id").read_text(encoding="utf-8"), install)

    def test_only_reports_inside_the_last_hour_count(self):
        payload = self.reporter.report_payload({}, self.view(lines=["▶ 收尾"]))
        reply = lambda *a, **k: Response(b'{"status":"ok","id":"x"}')
        for old, allowed in ((3600, True), (3600.5, True), (3599.5, False)):
            self.reporter.report_times = [10_000.0 - old]
            with patch.object(reporter.time, "time", return_value=10_000.0), \
                    patch.object(reporter.urllib.request, "urlopen", side_effect=reply):
                result = self.reporter.send_report(payload)
            if allowed:
                self.assertEqual(result, {"ok": True, "id": "x"})
            else:
                self.assertIn("最多上报 1 次", result["error"])

    def test_a_payload_that_is_not_an_object_is_rejected(self):
        self.assertEqual(self.reporter.send_report("不是对象"), {"error": "上报内容格式不对"})

    def test_a_payload_without_steps_needs_some_log_text(self):
        reply = lambda *a, **k: Response(b'{"status":"ok","id":"x"}')
        cases = (({"steps": [], "log": "   "}, {"error": "空报告（试验）"}),
                 ({"log": ""}, {"error": "空报告（试验）"}),
                 ({"steps": [{"title": "收尾"}], "log": ""}, {"ok": True, "id": "x"}))
        for payload, expected in cases:
            self.reporter.report_times = []
            with patch.object(reporter.urllib.request, "urlopen", side_effect=reply) as call:
                self.assertEqual(self.reporter.send_report(payload), expected)
            # 空报告在本地就挡住了，连一次请求都不发
            self.assertEqual(call.call_count, 0 if "error" in expected else 1)

    def test_server_refusals_name_the_code_and_the_message(self):
        payload = self.reporter.report_payload({}, self.view(lines=["▶ 收尾"]))

        def http(code, body):
            return urllib.error.HTTPError(self.reporter.report_url, code, "x", {}, io.BytesIO(body))
        cases = ((http(429, b'{"status":"limited"}'), {"error": "上报太频繁，请一小时后再试"}),
                 (http(400, '{"message":"安装编号格式不对"}'.encode()),
                  {"error": "服务器拒绝了这次上报（400：安装编号格式不对）"}),
                 (http(400, b'{"status":"x"}'), {"error": "服务器拒绝了这次上报（400）"}),
                 (http(500, b"not json"), {"error": "服务器拒绝了这次上报（500）"}))
        for error, expected in cases:
            self.reporter.report_times = []
            with patch.object(reporter.urllib.request, "urlopen", side_effect=error):
                self.assertEqual(self.reporter.send_report(payload), expected)
        self.assertEqual(self.reporter.report_times, [], "失败不占本地额度")

    def test_a_failed_connection_reports_the_cause(self):
        payload = self.reporter.report_payload({}, self.view(lines=["▶ 收尾"]))
        cases = ((urllib.error.URLError("timed out"), "连不上上报服务器：timed out"),
                 (ValueError("坏了"), "连不上上报服务器：坏了"),
                 (OSError("磁盘坏了"), "连不上上报服务器：磁盘坏了"))
        for error, expected in cases:
            with patch.object(reporter.urllib.request, "urlopen", side_effect=error):
                self.assertEqual(self.reporter.send_report(payload), {"error": expected})

    def test_the_success_reply_variants_are_reported_as_is(self):
        payload = self.reporter.report_payload({}, self.view(lines=["▶ 收尾"]))
        cases = ((b'{"status":"duplicate"}', {"ok": True, "duplicate": True}),
                 (b'{"status":"ok"}', {"ok": True, "id": ""}),
                 (b'{"status":"weird"}', {"error": "服务器没有确认收到"}),
                 (b'{"status":"ok","id":"abc"}', {"ok": True, "id": "abc"}))
        for body, expected in cases:
            self.reporter.report_times = []     # limit=1：每个成功回应都会占一格
            with patch.object(reporter.urllib.request, "urlopen", side_effect=lambda *a, body=body, **k: Response(body)):
                self.assertEqual(self.reporter.send_report(payload), expected)


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
