"""标准输出 / 错误流的 UTF-8 重配置：全仓唯一出口（#995）。

Windows 控制台与管道默认不是 UTF-8（cp1252 / GBK），打印中文与 ✓ / ✗ 会 `UnicodeEncodeError`，
所以每个入口都要转一次。转不动时照常跑——`io.StringIO`、已分离的 `TextIOWrapper` 与手机版
`aac_android/inproc.py` 包出来的 `_Router` 都没有 `reconfigure()`，为了打印而崩掉工具本身是
本末倒置。

调用点一律 `use_utf8_console()`，不再各写一份 try/except：`tests/test_rules_guards.py` 的
`StdioGuards` 扫源码，别的文件里出现 `reconfigure(encoding=` 即红。
"""
import sys


def use_utf8_console():
    """把标准流转成 UTF-8，出错字节替换；不支持重配置的流静默跳过。"""
    for stream in (sys.stdout, sys.stderr):
        # `sys.stdout` 的静态类型 `TextIO` 没声明 `reconfigure`，所以先取属性再判有无；
        # 与「直接调用后捕获 AttributeError」行为一致，但不靠异常兜住属性的缺失。
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
