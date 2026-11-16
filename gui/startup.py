"""界面起不来时告诉用户什么：归因、文案与写剪贴板，外加版本号比较（#1382）。

这段文字是用户唯一能拿出来的信息（原生弹窗选不中、只能手抄），它的协作者——`preflight` /
`notify` / `open_url` / `clipboard`——全部可注入，所以非 Windows 上也能把接线整段验完。
判据不在这里：WebView2 三态、MOTW 与原文拒载在 `gui/winpreflight.py`；程序名由调用方传
（它是 `gui/app.py` 的 `APP_NAME`）。
"""
import re
import time

try:                                # 当包导入（测试）；直接跑脚本、打包时它是顶层模块
    from . import toolpath, winpreflight
except ImportError:
    import toolpath, winpreflight


def version_key(text):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)$", (text or "").strip())
    return tuple(map(int, m.groups())) if m else ()


# 启动失败弹窗是原生 MessageBox：文字选不中，用户只能手抄命令、拍照识别（#811）。
# 整段先替用户复制好；复制不进去才退回 Ctrl+C——有焦点时 Windows 的弹窗能整段复制。
COPIED_NOTE = "这段文字已复制到剪贴板，可以直接粘贴到反馈里，不用手抄或拍照。"
MANUAL_COPY_NOTE = "自动复制没成功，在这个弹窗上按 Ctrl+C 也能复制整段文字。"


def startup_advice(state, blocked, error, rejected, copied=None):
    """窗口起不来时给用户看的文案，以及要不要跳微软官网。

    copied: None 还没试过写剪贴板；True 已写入；False 写入失败（#811）。
    """
    text, open_site = _attribution(state, blocked, error, rejected)
    if copied is not None:
        text += "\n\n" + (COPIED_NOTE if copied else MANUAL_COPY_NOTE)
    return text, open_site


def _attribution(state, blocked, error, rejected):
    """按结论选文案（#228、#597）。

    以前一律说「缺少 WebView2」，portable 包解压后文件带 MOTW 的现场被指到装不上的东西上。
    带 MOTW 的 dll 与被判成「远程来源」的 dll 报的是同一句 `Failed to resolve`，所以先看
    `blocked` 再认原文——前者的出路是解锁文件，不是补 config。
    """
    if state == "missing":
        return (
            "这台电脑缺少微软 Edge WebView2 运行时，界面没法显示。\n\n"
            "点「确定」打开微软官网，下载安装「Evergreen Bootstrapper」后重新打开本程序。\n\n"
            f"（{error}）", True)
    if blocked:
        return (
            "这台电脑可能已经装了 WebView2，但程序文件被 Windows 标记成「来自网络」，"
            "加载时被拦住了。\n\n"
            "办法一：对下载的 zip 压缩包点右键 →「属性」→ 勾选「解除锁定」→ 确定，重新解压后再打开。\n"
            "办法二：zip 已经删了，就在解压出来的文件夹里按住 Shift 点右键 →"
            "「在此处打开 PowerShell 窗口」，粘贴下面这行后回车：\n"
            "Get-ChildItem . -Recurse -File | Unblock-File\n\n"
            f"（{error}）", False)
    if rejected:
        return (
            "这台电脑的 .NET Framework 把程序自带的 dll 判成了「远程来源」，加载时被拦住了。\n\n"
            "办法一：确认程序文件夹里 AndroidAdCleaner.exe 旁边有 AndroidAdCleaner.exe.config，"
            "别把它删掉或改名。\n"
            "办法二：没有这个文件，或者有了还是这样，从官方 Release 重新下载最新版，"
            "完整解压后再打开。\n\n"
            f"（{error}）", False)
    if state == "unknown":
        return (
            "程序启动失败。这台电脑的 WebView2 状态没能确认（多半是注册表读取受限），"
            "所以下面的原因不一定是缺运行时。\n\n"
            "如果这是 Windows 10 且从没装过，先装一个再试：\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            "装过还这样，把括号里的原文发到 "
            "https://github.com/rddmwmddr/android-ad-cleaner/issues/new 。\n\n"
            f"（{error}）", False)
    return (
        "程序启动失败。WebView2 运行时在，程序文件也没有被 Windows 锁定，"
        "是按别的原因退出的。\n\n"
        "把下面括号里的原文发到 "
        "https://github.com/rddmwmddr/android-ad-cleaner/issues/new ，我们按它定位。\n\n"
        f"（{error}）", False)


def win_clipboard(text):
    """直接写 Unicode 剪贴板。以前经 PowerShell 管道，中文 Windows 按 GBK 解码，粘贴出来是乱码（#33 #50 #128）。"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    data = text.encode("utf-16-le") + b"\0\0"
    for _ in range(20):                       # 别的程序可能正占着剪贴板
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("剪贴板被占用")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))    # GMEM_MOVEABLE
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):           # CF_UNICODETEXT
            kernel32.GlobalFree(handle)
            raise OSError("写剪贴板失败")
    finally:
        user32.CloseClipboard()


def startup_failed(error, preflight=None, notify=None, open_url=None, clipboard=None, *, app_name):
    """先替用户复制、再按归因弹提示（#228、#811）。四个协作者可注入，接线本身在非 Windows 上也能验。

    `app_name` 是弹窗标题：它是 `gui/app.py` 的 `APP_NAME`，本模块不另存一份。
    """
    import ctypes, webbrowser
    preflight = preflight or winpreflight
    notify = notify or (lambda text: ctypes.windll.user32.MessageBoxW(0, text, app_name, 0x40))
    clipboard = clipboard or win_clipboard
    verdict = (preflight.webview2_state(), preflight.blocked_files(toolpath.BASE), error,
               preflight.load_rejected(error))
    text, open_site = startup_advice(*verdict, copied=True)
    try:
        clipboard(text)                       # 写进去的就是弹窗里那句，多一个字都不差
    except Exception:                         # 复制失败不能连弹窗一起吞掉：这里没有控制台
        text, open_site = startup_advice(*verdict, copied=False)
    notify(text)
    if open_site:
        (open_url or webbrowser.open)("https://developer.microsoft.com/microsoft-edge/webview2/")
