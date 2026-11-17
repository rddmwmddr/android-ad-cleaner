"""读屏 adapter 的接口：Phone 只看这一组能力，不管是手机上的读屏库还是测试里的假页面。

实现必须允许覆写 `shell`：`Connection` 会把带断线语义的版本换上去（见 `_resilient_shell`），
所以 `shell` 在这里是可写的属性，不是方法。

门面上没有它的转发属性：实体归 `Connection`，读 `p.conn.reader`；脚本侧经门面动词
（`p.shell` / `p.tap_id` …）做事，不直接碰这个对象（ADR-0045、#1479）。
"""
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class Reader(Protocol):
    shell: Callable[..., Any]
    settings: Any

    def dump_hierarchy(self) -> str: ...

    def window_size(self) -> tuple[int, int]: ...

    def screenshot(self) -> Any: ...

    def app_stop(self, package: str) -> Any: ...

    def close(self) -> None: ...

    @property
    def jsonrpc(self) -> Any: ...

    def __call__(self, **selectors: Any) -> Any: ...
