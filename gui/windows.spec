# Windows 打包：一次分析，两个 exe 共用 _internal
#   AndroidAdCleaner.exe  窗口程序（用户双击）
#   aac-cli.exe           命令行程序（客户端在后台调用，有正常的标准输出）
# 用法（仓库根目录）：pyinstaller --noconfirm --distpath gui/dist --workpath gui/build gui/windows.spec
import os, sys
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, os.path.join(ROOT, "gui"))
from bundle_data import bundle_data
import dotnet_config
datas = bundle_data(ROOT)
binaries, hidden = [], ["uiautomator2", "adbutils", "PIL"]
for pkg in ("uiautomator2", "adbutils", "webview"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h

# exe 名只有这一处：COLLECT 的目录名与随包 .config 的文件名都从这里取
APP_EXE, CLI_EXE = "AndroidAdCleaner", "aac-cli"

a = Analysis([os.path.join(ROOT, "gui", "launch.py")], pathex=[ROOT], binaries=binaries, datas=datas, hiddenimports=hidden)
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, "gui", "icon.ico")
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_EXE, console=False, icon=icon)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name=CLI_EXE, console=True, icon=icon)
coll = COLLECT(gui, cli, a.binaries, a.datas, name=APP_EXE)
# COLLECT 之后写：Inno Setup 从 dist\AndroidAdCleaner\* 递归收文件，便携 zip 也打这一层
dotnet_config.write(os.path.join(DISTPATH, APP_EXE), (APP_EXE, CLI_EXE))
