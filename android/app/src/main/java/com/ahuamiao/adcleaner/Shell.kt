package com.ahuamiao.adcleaner

/** 一条在跑的命令：Python 侧轮询 isDone()，超时自己 cancel()，结束后取 result()。 */
interface ShellJob {
    fun isDone(): Boolean
    fun result(timedOut: Boolean): Shell.Result
    fun cancel()
}

/**
 * 起命令服务时后端没就绪。`text` 已经是给用户看的整句，`failureText()` 不会再给它加前缀（#1034）。
 */
internal class ShellUnavailable(val text: String) : java.io.IOException(text)

/** 起命令服务失败要报给用户的那句：后端没就绪用它的整句，别的异常照旧带上前缀。 */
internal fun failureText(e: Throwable): String =
    (e as? ShellUnavailable)?.text ?: "命令服务不可用：$e"

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
    fun connected(): Boolean = backend(connect = false) !is ShellBackend.Missing

    /**
     * 去试着连上：内置无线调试要找端口，最多 4 秒；连不上后 10 秒内不再试。
     * `wait-for-device` 用它。
     */
    @JvmStatic
    fun ensure(): Boolean = backend(connect = true) !is ShellBackend.Missing

    /**
     * 现在该用哪个后端。只有 `connect = true` 时才去试连无线调试——那一步要等 mDNS，最多 4 秒；
     * Shizuku 就绪时连试都不试。
     */
    private fun backend(connect: Boolean): ShellBackend {
        val shizuku = ShizukuShell.ready()
        val wireless = !shizuku && (AdbShell.ready() || (connect && AdbShell.connect(4000)))
        return ShellBackend.pick(shizuku, wireless)
    }

    private fun client(connect: Boolean): ServerClient = when (val choice = backend(connect)) {
        ShellBackend.Shizuku -> ShizukuShell.client()
        ShellBackend.Wireless -> AdbShell.client()
        is ShellBackend.Missing -> throw ShellUnavailable(choice.reason)
    }

    /** 四条起命令服务的路共用一种收场：后端没就绪报它那句整话，别的异常照旧带前缀（#1034）。 */
    private fun startJob(block: () -> ShellJob): ShellJob = try {
        block()
    } catch (e: Exception) {
        Failed(failureText(e))
    }

    @JvmStatic
    fun submit(cmd: String, stdin: ByteArray?): ShellJob =
        startJob { client(connect = true).submit(cmd, stdin) }

    @JvmStatic
    fun daemon(name: String, cmd: String): Boolean {
        client(connect = true).daemon(name, cmd)
        return true
    }

    /** 停常驻进程只对已有通道做事：断了就算了，不为它去等 mDNS。 */
    @JvmStatic
    fun stopDaemon(name: String) {
        try {
            client(connect = false).stopDaemon(name)
        } catch (_: Exception) {
        }
    }

    /** 读屏（-1 = 所有屏）：Python 侧轮询 isDone() 后取 result()，不要在 Java 方法里等。 */
    @JvmStatic
    fun dumpJob(display: Int): ShellJob = startJob { client(connect = true).dump(display) }

    /** 某块屏的逻辑尺寸（随旋转）。 */
    @JvmStatic
    fun sizeJob(display: Int): ShellJob = startJob { client(connect = true).size(display) }
}
