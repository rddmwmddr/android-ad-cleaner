"""gui/ 下各模块按需加载 tool/ 的单一出口：根目录与 sys.path 垫片只在这里。

gui/app.py 顶层故意不 import tool/：手机版要先 configure 再 import app，桌面入口完全不垫。
"""
import importlib, os, sys

BASE = ""
TOOL = ""


def configure(base):
    """设定客户端根目录；tool/ 是它下面的 tool。手机版在 import gui.app 之前调用。"""
    global BASE, TOOL
    BASE = os.fspath(base)
    TOOL = os.path.join(BASE, "tool")


def tool(name):
    """按名字加载 tool/ 下的模块；没 configure 过就报可读的错，别让它退化成 ImportError。"""
    if not TOOL:
        raise RuntimeError(f"gui.toolpath 还没有 configure(base)：tool/ 的路径没定，加载不了 {name}")
    if TOOL not in sys.path:
        sys.path.insert(0, TOOL)
    return importlib.import_module(name)
