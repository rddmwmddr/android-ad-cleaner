"""`tool/stdio.py` 的唯一出口：尽力而为、失败静默（#995）。

Windows 控制台与管道默认不是 UTF-8，打印中文与 ✓ / ✗ 会 `UnicodeEncodeError`；各入口都要转一次，
但「转不动就照常跑」——`io.StringIO` 与手机版包出来的 `_Router` 都没有 `reconfigure()`。
断言打在助手本身，不打在十几个调用点上（父票的 Testing Decisions）。
"""
import io
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))

from stdio import use_utf8_console  # noqa: E402


class FixedStream:
    """只有 `reconfigure()` 的流：记下收到的参数，供断言。"""

    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


class AngryStream:
    """有 `reconfigure()` 但会拒绝：已分离的 `TextIOWrapper` 就是这个样子。"""

    def reconfigure(self, **kwargs):
        raise ValueError("underlying buffer has been detached")


@contextmanager
def streams(out, err):
    """临时换掉两个标准流，退出时还原——助手读的就是 `sys.stdout/stderr`，没有别的入口。"""
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        yield
    finally:
        sys.stdout, sys.stderr = saved


class UseUtf8ConsoleTests(unittest.TestCase):
    def test_streams_get_utf8_with_replacement(self):
        out, err = FixedStream(), FixedStream()
        with streams(out, err):
            use_utf8_console()
        self.assertEqual([out.calls, err.calls],
                         [[{"encoding": "utf-8", "errors": "replace"}]] * 2,
                         "两个流都要转，参数与各处内联写法逐字一致")

    def test_stream_without_reconfigure_does_not_raise(self):
        with streams(io.StringIO(), io.StringIO()):
            use_utf8_console()   # 不抛异常即通过

    def test_refusing_stream_does_not_raise(self):
        err = FixedStream()
        with streams(AngryStream(), err):
            use_utf8_console()
        self.assertEqual(err.calls, [{"encoding": "utf-8", "errors": "replace"}],
                         "一个流转不动不该拦住另一个")


if __name__ == "__main__":
    unittest.main()
