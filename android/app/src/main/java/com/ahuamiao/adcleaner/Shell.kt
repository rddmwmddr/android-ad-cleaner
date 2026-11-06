package com.ahuamiao.adcleaner

/** 一条在跑的命令：Python 侧轮询 isDone()，超时自己 cancel()，结束后取 result()。 */
interface ShellJob {
    fun isDone(): Boolean
    fun result(timedOut: Boolean): Shell.Result
    fun cancel()
}

/**
 * 以 shell 身份执行命令的门面，Python 只认这一个类（aac_android/bridge.py）。
 * 两条路：用户装了并授权了 Shizuku 就用 Shizuku；否则用内置无线调试（#622），不用另装 App。
 * 已授权的 Shizuku 永远优先，不记后端偏好。
 */
object Shell {
    class Result(
        @JvmField val code: Int,
        @JvmField val out: ByteArray,
        @JvmField val err: ByteArray,
        @JvmField val timedOut: Boolean,
    )

    /**
     * 现在能用吗：纯查询，不建连接。`devices` / `get-state` 用它，
     * 每轮状态轮询不能为此等 mDNS。
     */
    @JvmStatic
    fun connected(): Boolean =
        if (ShizukuShell.ready()) true else AdbShell.ready()

    /**
     * 去试着连上：内置无线调试要找端口，最多 4 秒；连不上后 10 秒内不再试。
     * `wait-for-device` 用它。
     */
    @JvmStatic
    fun ensure(): Boolean =
        if (ShizukuShell.ready()) true else AdbShell.ready() || AdbShell.connect(4000)

    @JvmStatic
    fun submit(cmd: String, stdin: ByteArray?): ShellJob =
        if (ShizukuShell.ready()) ShizukuShell.submit(cmd, stdin) else AdbShell.submit(cmd, stdin)

    @JvmStatic
    fun daemon(name: String, cmd: String): Boolean =
        if (ShizukuShell.ready()) ShizukuShell.daemon(name, cmd) else AdbShell.daemon(name, cmd)

    @JvmStatic
    fun stopDaemon(name: String) {
        ShizukuShell.stopDaemon(name)
        AdbShell.stopDaemon(name)
    }
}
