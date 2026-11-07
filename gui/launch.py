#!/usr/bin/env python3
"""客户端入口：命令行转发、起窗口、打包冒烟。

四种启动方式都落到这里的 `main()`：打包件（`gui/windows.spec`、`gui/build_mac.sh`）、
`python -m gui.app`、`python gui/launch.py`、`python gui/app.py`。
界面、adb 与运行时的其余部分仍在 `gui/app.py`；打包入口认的就是本文件。
"""
import json, sys, time
from pathlib import Path

if __package__:                     # `python -m gui.app`、被测试当包 import
    from . import app
else:                               # 打包件与 `python gui/launch.py`：没有父包，gui/ 在 sys.path 上
    import app


CLI_PROGRAM = "aac-cli"

USAGE = """\
用法：aac-cli --cli run.py <命令>

  aac-cli --cli run.py --help               查看全部命令
  aac-cli --cli run.py devices              列出已连接的手机
  aac-cli --cli run.py -s <序列号> check     检测指定手机

要打开窗口请运行 AndroidAdCleaner。
"""


def is_cli_program(executable=None):
    """跑的是不是打包出来的命令行程序。两个 exe 共用本文件，可执行文件基名是唯一的区别
    （`gui/windows.spec`）；以解释器运行时没有这个区别，按窗口程序处理（#573）。"""
    return Path(sys.executable if executable is None else executable).stem.lower() == CLI_PROGRAM


def dispatch(argv, executable=None):
    """这次启动去哪：'cli' 转发给引擎、'help' 打用法、'usage' 报用法错、'window' 起窗口。"""
    if len(argv) > 1 and argv[0] == "--cli":
        return "cli"
    if not is_cli_program(executable):
        return "window"
    # 打包冒烟用命令行程序起隐藏窗口做 GUI 验证（`gui/smoke_test.py`），
    # 这两个开关必须继续走窗口分支，否则标签构建会卡在冒烟（#573）。
    if any(flag in argv for flag in ("--smoke-gui", "--debug")):
        return "window"
    return "help" if argv[:1] in (["-h"], ["--help"]) else "usage"


def smoke_gui(window, result):
    """验证本地页面、图片、JS→Python 桥和模拟失败提示；不连接或修改手机。"""
    try:
        if not window.events.loaded.wait(30):
            raise RuntimeError("页面加载超时")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            ready = window.evaluate_js("typeof api !== 'undefined' && !!api && !!document.querySelector('#tutbox')")
            if ready:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("JS API 桥初始化超时")
        window.evaluate_js("window.__smokeEnv = null; api.env().then(x => window.__smokeEnv = x.version)")
        while time.monotonic() < deadline:
            report = window.evaluate_js("({url: location.href, version: window.__smokeEnv, images: [...document.querySelectorAll('#tutbox img')].every(i => i.complete && i.naturalWidth > 0)})")
            if report.get("version") == app.VERSION and report.get("images") and report.get("url", "").startswith("file://"):
                from webview import http
                if http.global_server is not None:
                    raise RuntimeError("不应启动本地 HTTP 服务")
                simulated = {"sec": 0, "cancel": False, "recovery": app._tool("troubleshooting").UI_RECOVERY,
                             "results": [{"rc": 1, "title": "读屏检查（模拟）", "sec": 0,
                                          "tail": ["UIAUTOMATION_BUSY: simulated"]}]}
                window.evaluate_js("showDone(" + json.dumps(simulated, ensure_ascii=False) + ")")
                hint_ok = window.evaluate_js("""(() => {
                    const box = document.querySelector('#ui-recovery');
                    return !!box && box.offsetHeight > 0 && box.textContent.includes('GKD') &&
                        box.textContent.includes('自动记账') && box.textContent.includes('检查读屏连接') &&
                        box.textContent.includes('复制完整诊断');
                })()""")
                if not hint_ok:
                    raise RuntimeError("读屏冲突排查提示未显示")
                result["ok"] = True
                print("GUI smoke: file 页面、教程图片、JS API 桥、读屏失败排查提示通过；未启动 HTTP 服务", flush=True)
                return
            time.sleep(0.1)
        raise RuntimeError("教程图片或 JS API 调用未通过")
    except Exception as e:
        print(f"GUI smoke failed: {e}", file=sys.stderr, flush=True)
    finally:
        window.destroy()


def main():
    action = dispatch(sys.argv[1:])
    if action == "cli":
        app.cli_main(); return
    if action != "window":
        app._fix_stdio()                # 控制台默认 GBK/cp1252，中文用法会报编码错
        if action == "help":
            print(USAGE); sys.exit(0)
        print(USAGE, file=sys.stderr); sys.exit(2)
    import webview
    api = app.client_api()
    smoke = "--smoke-gui" in sys.argv
    if smoke:
        app._fix_stdio()
        api.adb = None                     # 不枚举真机，不自动下载 adb
    result = {"ok": False}
    # 明确 file://：裸文件路径会启动 Bottle HTTP 服务，部分 Windows 环境回环连接超时（#18）。
    url = Path(app.BASE, "gui", "web", "index.html").resolve().as_uri()
    w = webview.create_window(app.APP_NAME, url, js_api=api, hidden=smoke,
                              width=1080, height=780, min_size=(900, 640))
    options = {"debug": "--debug" in sys.argv, "http_server": False}
    if smoke:
        options.update(func=smoke_gui, args=(w, result))
    if app.IS_WIN:
        try:
            webview.start(gui="edgechromium", **options)
        except Exception as e:      # 启动失败：缺 WebView2、MOTW 拦、dll 被判成远程来源、其他（#228、#597）
            if smoke:
                print(f"startup: {app.winpreflight.describe(app.BASE, error=e)}", flush=True)
                raise
            app.startup_failed(e)
    else:
        webview.start(**options)
    if smoke:
        sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
