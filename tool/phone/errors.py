"""引擎向调用方抛的手机状态异常（ADR-0033）。

`ScreenLocked` 原先定义在门面 `tool/fast.py`，搬到这里是与它的语义对齐：这是手机状态，
不是传输错误（`adb_link.DeviceLost`）也不是某个阶段的约定，库层与运行时都该从这里取。
门面仍 re-export 这个名字——`from fast import ScreenLocked` 是 ADR-0033 冻结的对外面，
机型脚本与 `tests/` 在用。
"""


class ScreenLocked(RuntimeError):
    """手机锁屏了：调用方等机主解锁，或停下整批，不逐项报同一个原因。"""
