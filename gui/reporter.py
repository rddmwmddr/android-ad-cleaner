"""错误诊断与上报：记下最近一次失败、组织上报内容、脱敏、限频与发送（docs/12，ADR-0011）。

只用标准库：不碰设备、不碰 `tool/`。版本号、上报地址、空报告文案与每小时上限由构造方传入
（`gui/app.py` 仍是这几个常量的单一来源），宿主措辞与排查提示也由构造方给取值函数——手机版会
把它们整段换掉。
"""
import functools, json, os, platform, re, time, urllib.error, urllib.request, uuid
from pathlib import Path

CONTENT_TYPE = "application/json"
CONTENT_TYPE_HEADER = "Content-Type"
USER_AGENT_HEADER = "User-Agent"
# `ensure_ascii=False` 钉在函数体外：内联进函数时，它落在一整句 pragma 的豁免范围里，同一句的
# `text=None`、`body→None` 这些不等价变异会跟着被放过。
JSON_DUMPS = functools.partial(json.dumps, ensure_ascii=False)

PRIVATE = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<邮箱>"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "<手机号>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b(?!\()"), "<IP>"),   # 华为版本号「4.2.0.180(C00…)」不是 IP
    # 用户目录可能不在 C 盘（360「C 盘搬家」等把它挪到 E:\…\Users\名字），整段路径前缀一起换掉
    (re.compile(r"(?:[A-Za-z]:)?[^\s'\"<>|]*?[\\/](?:Users|home)[\\/][^/\\\s'\"<>]+", re.I), "<用户目录>"),
)


def scrub(text, serial=None):
    """序列号、用户目录、邮箱、手机号、IP 换成占位符；服务器收到后再做一遍。"""
    for private, replacement in ((serial, "<序列号>"), (os.path.expanduser("~"), "<用户目录>")):
        if private:
            text = text.replace(private, replacement).replace(private.replace("\\", "\\\\"), replacement)
    for pattern, replacement in PRIVATE:
        text = pattern.sub(replacement, text)
    return text


class Reporter:
    """错误诊断与上报：记下最近一次失败、组织上报内容、发送与限频（docs/12，ADR-0011）。

    `os_name` 与 `help_of` 是取值函数：手机版把宿主措辞整段换掉，排查提示模块按需加载，
    两者都只能在调用时取。
    """

    def __init__(self, data, *, version, report_url, empty_report, limit, os_name, help_of):
        self.data = data
        self.version = version
        self.report_url = report_url
        self.empty_report = empty_report
        self.limit = limit
        self.os_name = os_name
        self.help_of = help_of
        self.last_error = None
        self.report_times = []

    def remember_error(self, operation, serial, detail):
        # 本地保留完整异常，分享前替换序列号和用户目录；不再截掉异常开头。
        for private, replacement in ((serial, "<序列号>"), (os.path.expanduser("~"), "<用户目录>")):
            if private:
                detail = detail.replace(private, replacement).replace(private.replace("\\", "\\\\"), replacement)
        self.last_error = {"operation": operation, "detail": detail}
        folder = self.data.logs
        try:
            os.makedirs(folder, exist_ok=True)
            # 按字节写：`str.encode()` 默认就是 UTF-8，换行也不必经平台转一次
            Path(folder, "last-error.txt").write_bytes(
                f"客户端 {self.version} · {operation}\n{detail}\n".encode())
        except OSError:
            pass  # 保存日志失败也要让界面收到原始问题
        lines = detail.splitlines()
        causes = [line.strip() for line in lines if re.search(r"(?:Exception|Error|Caused by:|原始异常：|启动失败)", line)
                  and not line.lstrip().startswith("at ")]
        summary = "\n".join(causes[:4]) or (detail if len(detail) <= 600 else detail[:600] + "…")
        help_ui = self.help_of()
        recovery = help_ui.UI_RECOVERY if help_ui.is_ui_connection_error(detail) else ""
        if recovery:
            summary = recovery + "\n\n" + summary
        if len(summary) > 1000:
            summary = summary[:1000] + "…（完整原因见诊断）"
        result = {"error": summary, "detail": detail}
        if recovery:
            result["recovery"] = recovery
        return result

    def report_payload(self, status, view):
        """要上报的全部内容。界面原样展示给用户，确认后发送同一份。"""
        info = (status or {}).get("info") or {}
        serial = view.get("serial")
        log = "\n".join(l for l in view.get("lines", []) if l.strip())
        if self.last_error:
            log += f"\n\n[最近失败：{self.last_error['operation']}]\n{self.last_error['detail']}"
        payloads = [x for x in view.get("payloads", []) if x.strip()]
        if payloads:
            # 放在末尾：日志只留最后 2 万字，骨架跟着失败日志一起留下，不会被早先的成功步骤挤掉
            log += "\n\n[诊断载荷]\n" + "\n".join(payloads)
        steps = [{"title": scrub(r["title"])[:40], "sec": int(r.get("sec") or 0),
                  "result": "跳过" if r.get("skipped") else "已停止" if r.get("stopped") else ("成功" if r["rc"] == 0 else "失败")}
                 for r in view.get("results", [])][:12]
        return {
            "client_version": self.version,
            "platform": f"{self.os_name()}（{platform.machine()}）"[:80],
            "phone_brand": scrub(info.get("brand") or "")[:40],
            "phone_model": scrub(info.get("name") or info.get("model") or "")[:80],
            "phone_system": scrub(info.get("os") or info.get("build") or "")[:160],
            "android": (info.get("android") or "")[:16],
            "steps": steps,
            "log": scrub(log, serial)[-20000:],      # 只留末尾；开头是早先成功的步骤
        }

    def _install_id(self):
        """第一次上报时随机生成，只用来限频；不取任何设备或电脑标识。"""
        path = Path(self.data.install_id)
        try:
            value = path.read_bytes().decode().strip()
            if uuid.UUID(value).version == 4:
                return value
        except (OSError, ValueError):
            pass
        value = str(uuid.uuid4())
        self.data.ensure()
        path.write_bytes(value.encode())
        return value

    def send_report(self, payload):
        now = time.time()
        self.report_times = [t for t in self.report_times if now - t < 3600]
        if len(self.report_times) >= self.limit:
            return {"error": f"一小时内最多上报 {self.limit} 次，请稍后再试"}
        if not isinstance(payload, dict):
            return {"error": "上报内容格式不对"}
        if not payload.get("steps") and not str(payload.get("log") or "").strip():
            return {"error": self.empty_report}
        body = dict(payload, install_id=self._install_id())
        headers = {CONTENT_TYPE_HEADER: CONTENT_TYPE, USER_AGENT_HEADER: f"AndroidAdCleaner/{self.version}"}
        text = JSON_DUMPS(body)
        request = urllib.request.Request(
            self.report_url, data=text.encode(), method="POST", headers=headers)
        try:
            # 云函数闲置后第一次调用要加载依赖，给足时间
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return {"error": "上报太频繁，请一小时后再试"}
            try:
                message = json.loads(e.read().decode()).get("message") or ""
            except (ValueError, OSError):
                return {"error": f"服务器拒绝了这次上报（{e.code}）"}
            return {"error": f"服务器拒绝了这次上报（{e.code}{'：' + message if message else ''}）"}
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {"error": f"连不上上报服务器：{getattr(e, 'reason', e)}"}
        self.report_times.append(now)
        if result.get("status") == "duplicate":
            return {"ok": True, "duplicate": True}
        if result.get("status") != "ok":
            return {"error": "服务器没有确认收到"}
        return {"ok": True, "id": result.get("id", "")}
