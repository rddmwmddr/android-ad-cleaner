package com.ahuamiao.adcleaner

/** 一条在跑的命令：Python 侧轮询 isDone()，超时自己 cancel()，结束后取 result()。 */
interface ShellJob {
    fun isDone(): Boolean
    fun result(timedOut: Boolean): Shell.Result
    fun cancel()
}

/**
 * 以 shell 身份执行命令、读屏的门面，Python 只认这一个类（`aac_android/bridge.py`、`aac_android/u2.py`）。
 * 两条路起的是同一个命令服务（ShellServer）：装了并授权 Shizuku 就经 Shizuku 起，否则经内置无线调试（#622）。
 * 已授权的 Shizuku 永远优先，不记后端偏好。
 */
object Shell {
    class Result(
        @JvmField val code: Int,
        @JvmField val out: ByteArray,
        @JvmField val err: ByteArray,
        @JvmField val timedOut: Boolean,
    )

    /** 命令服务起不来时的那条结果：已经「结束」，Python 取 result() 就拿到原因。 */
    private class Failed(private val reason: String) : ShellJob {
        override fun isDone() = true
        override fun result(timedOut: Boolean) = Result(-1, ByteArray(0), reason.toByteArray(), timedOut)
        override fun cancel() {
        }
    }

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

    private fun client(): ServerClient =
        if (ShizukuShell.ready()) ShizukuShell.client() else AdbShell.client()

    @JvmStatic
    fun submit(cmd: String, stdin: ByteArray?): ShellJob = try {
        client().submit(cmd, stdin)
    } catch (e: Exception) {
        Failed("命令服务不可用：$e")
    }

    @JvmStatic
    fun daemon(name: String, cmd: String): Boolean {
        client().daemon(name, cmd)
        return true
    }

    @JvmStatic
    fun stopDaemon(name: String) {
        try {
            client().stopDaemon(name)
        } catch (_: Exception) {
        }
    }

    /** 读屏（-1 = 所有屏）：Python 侧轮询 isDone() 后取 result()，不要在 Java 方法里等。 */
    @JvmStatic
    fun dumpJob(display: Int): ShellJob = try {
        client().dump(display)
    } catch (e: Exception) {
        Failed("命令服务不可用：$e")
    }

    /** 某块屏的逻辑尺寸（随旋转）。 */
    @JvmStatic
    fun sizeJob(display: Int): ShellJob = try {
        client().size(display)
    } catch (e: Exception) {
        Failed("命令服务不可用：$e")
    }
}
