package com.ahuamiao.adcleaner

/** 一条在跑的命令：Python 侧轮询 isDone()，超时自己 cancel()，结束后取 result()。 */
interface ShellJob {
    fun isDone(): Boolean
    fun result(timedOut: Boolean): ShizukuShell.Result
    fun cancel()
}

/**
 * 以 shell 身份执行命令的门面，Python 只认这一个类（aac_android/bridge.py）。
 * 两条路：用户装了并授权了 Shizuku 就用 Shizuku；否则用内置无线调试（#622），不用另装 App。
 */
object Shell {
    @JvmStatic
    fun backend(): String = when {
        ShizukuShell.ready() -> "shizuku"
        AdbShell.ready() || AdbShell.connect(4000) -> "adb"
        else -> ""
    }

    @JvmStatic
    fun ready(): Boolean = backend().isNotEmpty()

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
