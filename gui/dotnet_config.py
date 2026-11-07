"""随包的 .NET 配置文件：让包内托管 dll 不被 .NET Framework 判成「网络位置」（#597）。

部分机器上 `Assembly.LoadFile` 对本地 dll 也抛 `NotSupportedException (0x80131515)`，
`import clr` 因此失败、窗口起不来。放宽的只有「按路径加载本地程序集」这一条，包内没有从外部
路径加载代码的通路，取舍记在 ADR-0003 的增补段。只在打包时由 `windows.spec` 调用，
不随运行时 bundle 分发。
"""
import os

CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <runtime>
    <loadFromRemoteSources enabled="true" />
  </runtime>
</configuration>
"""


def write(dist_dir, exes):
    """在每个 exe 旁写一份配置：路径是 exe 文件名再拼 `.config`（`AndroidAdCleaner.exe.config`）。"""
    paths = []
    for exe in exes:
        path = os.path.join(dist_dir, exe + ".exe.config")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(CONFIG)
        paths.append(path)
    return tuple(paths)
