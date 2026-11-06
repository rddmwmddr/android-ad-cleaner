package com.ahuamiao.adcleaner

import java.io.DataInputStream
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * 与 ShellServer 对话：请求按编号发、回应按编号收，协议见 ShellServer.java。
 *
 * 两条后端共用：内置无线调试给它一条 adb `exec:` 流（AdbShell），Shizuku 给它一个远程进程的输入输出
 * （ShizukuShell）。读屏（#623）也走这条流，所以手机版不再需要 u2.jar 那个监听 9008 端口的服务。
 *
 * 一切都异步：Python 侧轮询 `isDone()`。姿势上不能反过来在 Java 方法里等——Chaquopy 调 Java 期间
 * 不放解释器锁，一条卡住的命令会把停止键、界面轮询与看门狗一起冻住（小米 18 Pro Max 上实测 122 秒）。
 */
class ServerClient(input: InputStream, private val output: OutputStream, private val onClose: () -> Unit) {
    private val pending = ConcurrentHashMap<Int, Job>()
    private val nextId = AtomicInteger(1)
    private val ready = CountDownLatch(1)
    @Volatile var closed = false
        private set

    inner class Job internal constructor(internal val id: Int) : ShellJob {
        @Volatile private var finished = false
        @Volatile private var code = -1
        @Volatile private var out = ByteArray(0)
        @Volatile private var err = ByteArray(0)

        fun complete(code: Int, out: ByteArray, err: ByteArray) {
            this.code = code; this.out = out; this.err = err
            finished = true
        }

        override fun isDone(): Boolean = finished

        override fun result(timedOut: Boolean) = Shell.Result(code, out, err, timedOut)

        /**
         * 超时：先把这条 id 从待回队列摘掉，再让命令服务真把远端进程杀掉（类型 4，不回包）。
         * 只摘队列不够——远端命令会一直跑完，占着设置页和 CPU。
         */
        override fun cancel() {
            finished = true
            pending.remove(id)
            sendIfOpen(id, TYPE_CANCEL, ByteArray(0))
        }
    }

    init {
        thread(isDaemon = true, name = "server-reader") {
            try {
                val data = DataInputStream(input)
                while (true) {
                    val id = data.readInt()
                    val code = data.readInt()
                    val o = ByteArray(data.readInt()).also { data.readFully(it) }
                    val e = ByteArray(data.readInt()).also { data.readFully(it) }
                    if (id == 0) ready.countDown() else pending.remove(id)?.complete(code, o, e)
                }
            } catch (e: Exception) {
                android.util.Log.w("AacShell", "命令服务断开：$e")
            } finally {
                closed = true
                pending.values.toList().forEach { it.complete(-1, ByteArray(0), "命令服务断开".toByteArray()) }
                pending.clear()
                onClose()
            }
        }
    }

    /** 等服务报「ready」。 */
    fun awaitReady(timeoutMs: Long): Boolean = ready.await(timeoutMs, TimeUnit.MILLISECONDS)

    fun submit(cmd: String, stdin: ByteArray?): ShellJob =
        request(TYPE_RUN, field(cmd.toByteArray()) + field(stdin ?: ByteArray(0)))

    fun daemon(name: String, cmd: String): ShellJob =
        request(TYPE_DAEMON, field(name.toByteArray()) + cmd.toByteArray())

    fun stopDaemon(name: String): ShellJob = request(TYPE_STOP, name.toByteArray())

    /** 读屏：第 display 块屏的窗口（-1 = 所有屏），回与 uiautomator 同格式的 XML。 */
    fun dump(display: Int): ShellJob = request(TYPE_DUMP, display.toString().toByteArray())

    /** 第 display 块屏的逻辑尺寸「宽 高」。 */
    fun size(display: Int): ShellJob = request(TYPE_SIZE, display.toString().toByteArray())

    private fun request(type: Int, body: ByteArray): Job {
        val job = Job(nextId.getAndIncrement())
        if (closed) {
            job.complete(-1, ByteArray(0), "命令服务已断开".toByteArray())
            return job
        }
        pending[job.id] = job
        try {
            write(job.id, type, body)
        } catch (e: Exception) {
            pending.remove(job.id)
            job.complete(-1, ByteArray(0), "命令服务不可用：$e".toByteArray())
        }
        return job
    }

    /**
     * 只在已经连着的流上写一条（取消用）：断了就算了，**别为一条取消去重建连接**——
     * 重建要新开流并等「ready」，而取消恰恰发生在「流刚断、命令超时」这条路径上。
     */
    private fun sendIfOpen(id: Int, type: Int, body: ByteArray) {
        if (closed) return
        try {
            write(id, type, body)
        } catch (_: Exception) {
        }
    }

    /** 整包一次写出（adb 流上每次 write 都要等对端回 OKAY，拆开写会慢）。 */
    private fun write(id: Int, type: Int, body: ByteArray) {
        val buf = ByteBuffer.allocate(9 + body.size).putInt(id).put(type.toByte()).putInt(body.size).put(body).array()
        synchronized(output) {
            output.write(buf)
            output.flush()
        }
    }

    private fun field(data: ByteArray): ByteArray = ByteBuffer.allocate(4 + data.size).putInt(data.size).put(data).array()

    companion object {
        // 协议类型，与 ShellServer.java 的注释一一对应
        const val TYPE_RUN = 1
        const val TYPE_DAEMON = 2
        const val TYPE_STOP = 3
        const val TYPE_CANCEL = 4
        const val TYPE_DUMP = 5
        const val TYPE_SIZE = 6

        /** 起服务的命令：本 APK 当类路径，以调用者（shell）身份跑；stderr 丢掉，免得混进二进制协议。 */
        fun command(apk: String) =
            "CLASSPATH=$apk exec app_process / com.ahuamiao.adcleaner.ShellServerMain 2>/dev/null"
    }
}
