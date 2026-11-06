package com.ahuamiao.adcleaner

import android.content.Context
import android.os.Build
import io.github.muntashirakon.adb.AdbStream
import io.github.muntashirakon.adb.android.AdbMdns
import java.io.DataInputStream
import java.nio.ByteBuffer
import kotlin.concurrent.thread

/**
 * 内置无线调试的命令通道（#622），与 ShizukuShell 同一组接口：submit 返回 Job，Python 侧轮询。
 *
 * 连上本机 adbd 后只开一条常驻 `exec:` 流，跑本 APK 里的 ShellServer（shell 身份），所有命令按编号经它收发，
 * 分得开 stdout / stderr、带回退出码。不给每条命令单开 adb 流：libadb 在对端关流时有竞态，
 * 模拟器上小命令会丢掉全部输出和退出码。
 */
object AdbShell {
    lateinit var app: Context
    @Volatile private var failedAt = 0L      // 上次连不上的时刻：10 秒内不再试，免得每次查状态都等 mDNS

    /** 已连上本机 adbd。 */
    @JvmStatic
    fun ready(): Boolean = try {
        AdbManager.get(app).isConnected
    } catch (_: Throwable) {
        false
    }

    /**
     * 连上本机 adbd：先看已有连接；没有就经 mDNS 找无线调试的连接端口连 127.0.0.1。
     * 无线调试被关了（重启、换 Wi-Fi）且本 App 已有 WRITE_SECURE_SETTINGS（首次连上时经 shell 自授），
     * 自己写 adb_wifi_enabled=1 再连。需要配对时返回 false（界面引导用户配对）。
     */
    @JvmStatic
    @Synchronized
    fun connect(timeoutMs: Long): Boolean {
        if (Build.VERSION.SDK_INT < 30) return false
        val m = AdbManager.get(app)
        if (m.isConnected) return true
        if (System.currentTimeMillis() - failedAt < 10_000) return false
        val restarted = !AdbManager.wirelessOn(app)
        if (restarted) {
            try {
                android.provider.Settings.Global.putInt(app.contentResolver, "adb_wifi_enabled", 1)
            } catch (_: SecurityException) {
                android.util.Log.w("AacAdb", "无线调试被关了，本 App 没有权限自己打开（WRITE_SECURE_SETTINGS 没授上？）")
                return false
            }
        }
        val port = AdbManager.discover(app, AdbMdns.SERVICE_TYPE_TLS_CONNECT, timeoutMs)
        val ok = port > 0 && try {
            m.connect("127.0.0.1", port)
        } catch (e: Throwable) {
            android.util.Log.w("AacAdb", "连接本机 adbd 失败（端口 $port）：$e")
            false
        }
        if (ok) {
            grantSelf()
            // 重开成功才说，免得「已重新打开」配着一条连不上的实际情况
            if (restarted && !MainActivity.inForeground()) noticeWirelessRestarted()
        } else {
            if (port <= 0) android.util.Log.w("AacAdb", "没找到无线调试的连接端口（${timeoutMs}ms）")
            failedAt = System.currentTimeMillis()
        }
        return ok
    }

    /**
     * 自己把无线调试重新打开了：界面在后台（多半是执行期间）时发一条「执行状态」通知，
     * 免得用户以为手机出问题。界面正开着时用户看得见，不发。
     */
    private fun noticeWirelessRestarted() {
        try {
            val nm = app.getSystemService(android.app.NotificationManager::class.java)
            nm.createNotificationChannel(android.app.NotificationChannel(
                KeepAliveService.CHANNEL, KeepAliveService.CHANNEL_NAME,
                android.app.NotificationManager.IMPORTANCE_LOW))
            val open = android.app.PendingIntent.getActivity(app, 5,
                android.content.Intent(app, MainActivity::class.java),
                android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
            nm.notify(5, android.app.Notification.Builder(app, KeepAliveService.CHANNEL)
                .setSmallIcon(android.R.drawable.ic_popup_sync)
                .setContentTitle("无线调试已自动重新打开")
                .setContentText("已重新连上，可以照常用手机")
                .setContentIntent(open)
                .setAutoCancel(true)
                .build())
        } catch (_: Throwable) {
        }
    }

    /** 首次连上：给本 App 授 WRITE_SECURE_SETTINGS，以后无线调试被关时 App 能自己打开、不用用户再操作。 */
    private fun grantSelf() {
        thread(isDaemon = true) {
            try {
                submit("pm grant ${app.packageName} android.permission.WRITE_SECURE_SETTINGS", null).let { job ->
                    val deadline = System.currentTimeMillis() + 10_000
                    while (!job.isDone() && System.currentTimeMillis() < deadline) Thread.sleep(50)
                }
            } catch (_: Throwable) {
            }
        }
    }

    /** 配对：用户在通知栏填了 6 位配对码，当场找配对端口（配对对话框还开着）再配。 */
    @JvmStatic
    fun pair(code: String, timeoutMs: Long): Boolean {
        val port = AdbManager.discover(app, AdbMdns.SERVICE_TYPE_TLS_PAIRING, timeoutMs)
        if (port <= 0) return false
        val ok = try {
            AdbManager.get(app).pair("127.0.0.1", port, code)
        } catch (_: Throwable) {
            false
        }
        if (ok) failedAt = 0L       // 刚配对：马上可以连
        return ok
    }

    // ----- 命令服务：一条常驻流，所有命令都经它（见 ShellServer.java）-----
    /** 协议类型（与 ShellServer.java 的注释一一对应）。 */
    private const val TYPE_RUN = 1
    private const val TYPE_DAEMON = 2
    private const val TYPE_STOP = 3
    private const val TYPE_CANCEL = 4

    private var server: AdbStream? = null
    private var output: java.io.OutputStream? = null
    private val pending = java.util.concurrent.ConcurrentHashMap<Int, Job>()
    private val nextId = java.util.concurrent.atomic.AtomicInteger(1)

    /** 起命令服务（已在跑就直接用）：经 exec: 流以 shell 身份跑本 APK 里的 ShellServer，等它报「ready」。 */
    @Synchronized
    private fun ensureServer(): AdbStream {
        server?.let { if (!it.isClosed) return it }
        val apk = app.applicationInfo.sourceDir
        // exec: 流里 stderr 与 stdout 混在一起，会打乱二进制协议：stderr 丢掉
        val stream = AdbManager.get(app).openStream(
            "exec:CLASSPATH=$apk exec app_process / com.ahuamiao.adcleaner.ShellServer 2>/dev/null")
        val ready = java.util.concurrent.CountDownLatch(1)
        thread(isDaemon = true) {
            try {
                val input = DataInputStream(stream.openInputStream())
                while (true) {
                    val id = input.readInt()
                    val code = input.readInt()
                    val o = ByteArray(input.readInt()).also { input.readFully(it) }
                    val e = ByteArray(input.readInt()).also { input.readFully(it) }
                    if (id == 0) ready.countDown() else pending.remove(id)?.complete(code, o, e)
                }
            } catch (e: Exception) {
                android.util.Log.w("AacAdb", "命令服务断开：$e")
            } finally {
                synchronized(this) { if (server === stream) server = null }
                pending.values.toList().forEach { it.complete(-1, ByteArray(0), "命令服务断开".toByteArray()) }
                pending.clear()
            }
        }
        output = stream.openOutputStream()
        server = stream
        if (!ready.await(15, java.util.concurrent.TimeUnit.SECONDS)) {
            stream.close()
            throw java.io.IOException("命令服务没有启动")
        }
        return stream
    }

    /** 发一条请求：整包一次写出（每次 write 都要等对端回 OKAY，拆开写会慢）。 */
    private fun send(id: Int, type: Int, body: ByteArray) {
        ensureServer()
        val buf = ByteBuffer.allocate(9 + body.size).putInt(id).put(type.toByte()).putInt(body.size).put(body).array()
        synchronized(this) {
            output!!.write(buf)
            output!!.flush()
        }
    }

    /**
     * 只在已经连着的服务上写一条（取消用）：断了就算了，**别为一条取消去重建连接**——
     * `send()` 会经 `ensureServer()` 新开 adb 流并等「ready」最多 15 秒，正卡在 Python 的轮询线程上，
     * 而取消恰恰发生在「流刚断、命令超时」这条路径上。
     */
    @Synchronized
    private fun sendIfOpen(id: Int, type: Int, body: ByteArray) {
        if (server?.isClosed != false) return
        val o = output ?: return
        val buf = ByteBuffer.allocate(9 + body.size).putInt(id).put(type.toByte()).putInt(body.size).put(body).array()
        o.write(buf)
        o.flush()
    }

    private fun field(data: ByteArray): ByteArray = ByteBuffer.allocate(4 + data.size).putInt(data.size).put(data).array()

    class Job internal constructor(private val id: Int) : ShellJob {
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
         * 超时：先把这条 id 从待回队列摘掉，再让命令服务真把远端进程杀掉（协议类型 4，不回包）。
         * 只摘队列不够——远端命令会一直跑完，占着设置页和 CPU。
         */
        override fun cancel() {
            finished = true
            AdbShell.pending.remove(id)
            try {
                AdbShell.sendIfOpen(id, TYPE_CANCEL, ByteArray(0))
            } catch (_: Exception) {
            }
        }
    }

    @JvmStatic
    fun submit(cmd: String, stdin: ByteArray?): ShellJob {
        val id = nextId.getAndIncrement()
        val job = Job(id)
        pending[id] = job
        try {
            send(id, TYPE_RUN, field(cmd.toByteArray()) + field(stdin ?: ByteArray(0)))
        } catch (e: Exception) {
            pending.remove(id)
            job.complete(-1, ByteArray(0), "命令服务不可用：$e".toByteArray())
        }
        return job
    }

    /**
     * 常驻进程（读屏服务、后台屏）：交给命令服务起，名字相同且还活着就不再起。
     * 不等应答：与 ShizukuShell.daemon 不同，这里返回的 true 只表示请求发出去了，
     * 是否真的新起由服务端的同名判断决定。现有调用点都不读返回值，所以发不出去时要照旧抛出去——
     * 否则「建不了屏 / 读屏服务起不来」的真实原因就被吞成 false，调用方只能空等超时。
     */
    @JvmStatic
    fun daemon(name: String, cmd: String): Boolean {
        val id = nextId.getAndIncrement()
        pending[id] = Job(id)
        return try {
            send(id, TYPE_DAEMON, field(name.toByteArray()) + cmd.toByteArray())
            true
        } catch (e: Exception) {
            pending.remove(id)
            throw e
        }
    }

    @JvmStatic
    fun stopDaemon(name: String) {
        if (server?.isClosed != false) return
        // 类型 3 的回包没有人等：不登记 pending，到了直接丢掉
        try {
            send(nextId.getAndIncrement(), TYPE_STOP, name.toByteArray())
        } catch (_: Exception) {
        }
    }
}
