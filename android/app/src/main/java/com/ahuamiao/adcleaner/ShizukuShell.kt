package com.ahuamiao.adcleaner

import android.content.pm.PackageManager
import rikka.shizuku.Shizuku
import rikka.shizuku.ShizukuRemoteProcess
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * 经 Shizuku 以 shell 身份执行命令：桌面版经 adb 做的事，手机上都走这里（Python 侧见 aac_android/adb.py）。
 *
 * Shizuku 13 起 newProcess 不再公开，官方建议 UserService；这里只需要执行一条 sh 命令、拿退出码与输出，
 * 反射调用它是 Shizuku 文档里认可的做法（rish 走的也是同一个接口）。
 */
object ShizukuShell {

    class Result(
        @JvmField val code: Int,
        @JvmField val out: ByteArray,
        @JvmField val err: ByteArray,
        @JvmField val timedOut: Boolean,
    )

    private val newProcess by lazy {
        Shizuku::class.java.getDeclaredMethod(
            "newProcess", Array<String>::class.java, Array<String>::class.java, String::class.java,
        ).apply { isAccessible = true }
    }

    /** Shizuku 在运行、并且已授权本 App。 */
    @JvmStatic
    fun ready(): Boolean = try {
        Shizuku.pingBinder() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    } catch (e: Throwable) {
        false
    }

    private fun start(cmd: String): ShizukuRemoteProcess =
        newProcess.invoke(null, arrayOf("sh", "-c", cmd), null, null) as ShizukuRemoteProcess

    private fun drain(stream: InputStream, into: ByteArrayOutputStream) = thread(isDaemon = true) {
        try {
            stream.copyTo(into)
        } catch (_: Exception) {
        }
    }

    /**
     * 一条命令在后台线程里跑，Python 侧轮询 isDone() 并自己掐超时。
     *
     * 不能在 Python 调用的 Java 方法里等命令结束：Chaquopy 调 Java 期间不放解释器锁，
     * 一条命令卡住（小米 18 Pro Max 上经 Shizuku 跑 monkey 卡了 122 秒），停止、界面轮询、看门狗全跟着停。
     * 也不能靠 waitForTimeout 掐超时：同一次实测里 60 秒的超时没有生效。
     */
    class Job internal constructor(cmd: String, stdin: ByteArray?) {
        private val process = start(cmd)
        private val out = ByteArrayOutputStream()
        private val err = ByteArrayOutputStream()
        @Volatile private var finished = false
        @Volatile private var code = -1

        init {
            val readers = listOf(drain(process.inputStream, out), drain(process.errorStream, err))
            thread(isDaemon = true) {
                try {
                    process.outputStream.use { if (stdin != null) it.write(stdin) }
                } catch (_: Exception) {
                }
            }
            thread(isDaemon = true) {
                code = try {
                    process.waitFor()
                } catch (_: Exception) {
                    -1
                }
                readers.forEach { it.join(2000) }
                finished = true
            }
        }

        fun isDone(): Boolean = finished

        fun result(timedOut: Boolean) = Result(code, out.toByteArray(), err.toByteArray(), timedOut)

        fun cancel() {
            try {
                process.destroy()
            } catch (_: Exception) {
            }
        }
    }

    @JvmStatic
    fun submit(cmd: String, stdin: ByteArray?): Job = Job(cmd, stdin)

    private val daemons = mutableMapOf<String, ShizukuRemoteProcess>()

    /** 常驻进程（读屏服务 u2.jar）：同名的还活着就不再起；输出读掉丢弃，免得管道写满把它卡住。 */
    @JvmStatic
    @Synchronized
    fun daemon(name: String, cmd: String): Boolean {
        daemons[name]?.let { if (alive(it)) return false }
        val process = start(cmd)
        drain(process.inputStream, ByteArrayOutputStream())
        drain(process.errorStream, ByteArrayOutputStream())
        process.outputStream.close()
        daemons[name] = process
        return true
    }

    /** isAlive 同样走 exitValue()，换成 0 毫秒的 waitForTimeout。 */
    private fun alive(process: ShizukuRemoteProcess) = try {
        !process.waitForTimeout(0, TimeUnit.MILLISECONDS)
    } catch (_: Exception) {
        false
    }

    @JvmStatic
    @Synchronized
    fun stopDaemon(name: String) {
        daemons.remove(name)?.destroy()
    }
}
