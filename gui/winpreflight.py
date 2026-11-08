"""Windows 启动失败的归因：缺 WebView2、程序文件被 Windows 标记为「来自网络」、本地 dll 被 .NET
Framework 判成「网络位置」、其他（#228、#597）；以及免安装版启动时旧名安装还在的检测（#872）。

`gui/app.py` 原来把所有启动异常都说成「缺少 WebView2」。实测 portable 包解压后，
`Python.Runtime.dll` 带 `Zone.Identifier`（MOTW），.NET 加载器拒载，`import clr` 失败，
症状与缺运行时一模一样。另有一类机器上 dll 没有 MOTW，.NET 仍按路径拒绝加载本地程序集，
表现为同一句 `Failed to resolve Python.Runtime.Loader.Initialize`（#597）。这里只做判定，
不碰界面、不碰 `tool/`。

注册表读取与 ADS 探测从外面注入，非 Windows 上也能跑这套判定。
"""
import ntpath
import os
import sys

# 这一类只能从错误原文认：失败点正是 `import clr`，此时 pythonnet 的 System 模块还不存在，
# 拿托管 dll 探一次做不到（#609 的探测方案因此不可行）。
LOAD_REJECTION_MARKS = ("Failed to resolve", "Python.Runtime")

WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# 64 位安装、32 位安装、按用户安装各一处；读到一个有值的 pv 就算装了。
WEBVIEW2_KEYS = (
    ("HKLM", r"SOFTWARE\Microsoft\EdgeUpdate\Clients" + "\\" + WEBVIEW2_CLIENT_ID),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients" + "\\" + WEBVIEW2_CLIENT_ID),
    ("HKCU", r"Software\Microsoft\EdgeUpdate\Clients" + "\\" + WEBVIEW2_CLIENT_ID),
)

# 这两个 dll 被拒载就足以让 `import clr` 失败；不全扫解压目录，避免把无关文件算进来。
BLOCKED_RELATIVE = (
    ("pythonnet", "runtime", "Python.Runtime.dll"),
    ("clr_loader", "ffi", "dlls", "amd64", "ClrLoader.dll"),
)

# 0.4.0 换了产品名，AppId 没变：0.3.2 及更早装的那份仍叫「安卓去广告」（#814、#872）。
# 卸载项的 DisplayName 不是产品名本身：Inno 的 UninstallDisplayName 默认取 AppVerName，
# 而旧的 installer.iss 只设了 AppName/AppVersion，于是它是「安卓去广告 版本 0.3.2」，只比前缀。
OLD_PRODUCT_NAME = "安卓去广告"
OLD_UNINSTALL_KEY = "{6C1E3F2A-8B7D-4E55-9A41-AAC0ADC1EA01}_is1"

# 按用户装写 HKCU、提权装写 HKLM，32 位视图还在 WOW6432Node 下；没有真机样本确认旧版到底写了哪一处，
# 四处都查，读不到就当那一处没有。
OLD_INSTALL_KEYS = (
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + OLD_UNINSTALL_KEY),
    ("HKCU", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + OLD_UNINSTALL_KEY),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + OLD_UNINSTALL_KEY),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + OLD_UNINSTALL_KEY),
)

# Inno Setup 自己写的那个先看；旧版用别的安装器时只剩它。
INSTALL_FOLDER_VALUES = ("Inno Setup: App Path", "InstallLocation")


def read_value(hive, path, name):
    """读某个键下的一个值；键或值不存在抛 FileNotFoundError。"""
    import winreg
    root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
    with winreg.OpenKey(root, path) as key:
        return winreg.QueryValueEx(key, name)[0]


def read_pv(hive, path):
    """读某个 EdgeUpdate 客户端键的 pv；键不存在抛 FileNotFoundError。"""
    return read_value(hive, path, "pv")


def has_zone_identifier(path):
    """文件带「来自网络」标记（`Zone.Identifier` 备用数据流）时为真。"""
    try:
        with open(path + ":Zone.Identifier", "rb"):
            return True
    except OSError:
        return False


def webview2_state(read=None):
    """`installed` / `missing` / `unknown`。三处键都读不到真值但至少一处报错时是 unknown。"""
    read = read or read_pv
    errored = False
    for hive, path in WEBVIEW2_KEYS:
        try:
            version = read(hive, path)
        except FileNotFoundError:           # 这台机器上没有这一处键
            continue
        except (OSError, ImportError):      # 拒绝访问、非 Windows（没有 winreg）
            errored = True
            continue
        if version:
            return "installed"
    return "unknown" if errored else "missing"


def blocked_files(root, detect=None):
    """`root` 下那两个关键 dll 里带 MOTW 的绝对路径。

    `root` 传 `sys._MEIPASS`：PyInstaller 6 的 onedir 把它指到 `_internal`，依赖就在这一层。
    文件不在就不探测——`detect` 只在真存在时才被调用。
    """
    detect = detect or has_zone_identifier
    found = []
    for rel in BLOCKED_RELATIVE:
        path = os.path.join(root, *rel)
        if os.path.isfile(path) and detect(path):
            found.append(path)
    return tuple(found)


def load_rejected(error):
    """启动异常原文表明 `Python.Runtime.dll` 被 .NET 按路径拒载（#597）。

    只认原文里的两个子串，不新起探测进程；库把这句话改写之后要同步维护 `LOAD_REJECTION_MARKS`。
    """
    text = str(error or "")
    return all(mark in text for mark in LOAD_REJECTION_MARKS)


def describe(root, read=None, detect=None, error=None):
    """给 `--smoke-gui` 打的一行结论，CI 日志里能分清环境问题与代码回归。"""
    blocked = blocked_files(root, detect)
    return (f"webview2={webview2_state(read)} motw={'yes' if blocked else 'no'} "
            f"load={'unresolved' if load_rejected(error) else 'no'}")


def same_dir(left, right):
    """两个 Windows 路径是否指向同一个目录：不看大小写，也不看末尾分隔符。"""
    return ntpath.normcase(ntpath.normpath(left)) == ntpath.normcase(ntpath.normpath(right))


def old_install_present(read=None, exe_dir=None):
    """旧产品名的安装还在、且当前程序不是从它那个目录跑的（#872）。

    免安装版与安装版共用同一个 AppId，便携版完全在注册表之外，所以旧的安装原样留在机器上。
    只做判定；读注册表出任何问题都当「读不出」，不拦启动。
    """
    read = read or read_value
    exe_dir = exe_dir if exe_dir is not None else os.path.dirname(sys.executable)
    for hive, path in OLD_INSTALL_KEYS:
        try:
            name = read(hive, path, "DisplayName")
        except (OSError, ImportError):      # 键不存在、拒绝访问、非 Windows（没有 winreg）
            continue
        if not (name or "").strip().startswith(OLD_PRODUCT_NAME):
            continue
        folder = ""
        for value in INSTALL_FOLDER_VALUES:
            try:
                folder = read(hive, path, value) or ""
            except (OSError, ImportError):
                continue
            if folder:
                break
        # 读不出目录就没法证明新版已经顶掉它；提示只是提示，不动任何文件。
        return not (folder and same_dir(folder, exe_dir))
    return False
