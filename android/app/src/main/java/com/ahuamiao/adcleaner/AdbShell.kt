package com.ahuamiao.adcleaner

import android.content.Context
import android.os.Build
import io.github.muntashirakon.adb.AdbStream
import io.github.muntashirakon.adb.android.AdbMdns
import kotlin.concurrent.thread

/**
 * 内置无线调试（#622）：配对、连本机 adbd，再开一条常驻 `exec:` 流跑本 APK 里的 ShellServer（shell 身份），
 * 之后所有命令与读屏都经 ServerClient 收发。
 *
 * 不给每条命令单开 adb 流：libadb 在对端关流时有竞态，模拟器上小命令会丢掉全部输出和退出码。
 */
object AdbShell {
    lateinit var app: Context
    @Volatile private var failedAt = 0L      // 上次连不上的时刻：10 秒内不再试（开关没变的话），免得每次查状态都等 mDNS
    @Volatile private var failedWireless = false     // 连不上那会儿无线调试开没开：用户改过开关就不必等满 10 秒（#662）

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
        if (System.currentTimeMillis() - failedAt < 10_000 && AdbManager.wirelessOn(app) == failedWireless) return false
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
            failedWireless = AdbManager.wirelessOn(app)
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
        thread(isDaemon = true) { exec("pm grant ${app.packageName} android.permission.WRITE_SECURE_SETTINGS") }
    }

    /** 以 shell 身份跑一条命令，不关心输出；失败不抛。 */
    @JvmStatic
    fun exec(command: String, timeoutMs: Long = 10_000) {
        try {
            client().submit(command, null).let { job ->
                val deadline = System.currentTimeMillis() + timeoutMs
                while (!job.isDone() && System.currentTimeMillis() < deadline) Thread.sleep(50)
            }
        } catch (_: Throwable) {
        }
    }

    /** 配对：用户在通知栏填了 6 位配对码，当场找配对端口（配对对话框还开着）再配。 */
    @JvmStatic
    fun pair(code: String, timeoutMs: Long): Boolean {
        val port = AdbManager.discover(app, AdbMdns.SERVICE_TYPE_TLS_PAIRING, timeoutMs)
        if (port <= 0) {
            android.util.Log.i("AacPair", "没找到配对端口：对话框关了，或 mDNS 没收到")
            return false
        }
        return try {
            pairAt(port, code)
        } catch (e: Throwable) {
            android.util.Log.w("AacPair", "配对失败", e)
            false
        }
    }

    /** 已知配对端口时直接配（自动识别配对码时用，#634）；失败抛异常，由调用方记日志。 */
    @JvmStatic
    fun pairAt(port: Int, code: String): Boolean {
        val ok = AdbManager.get(app).pair("127.0.0.1", port, code)
        if (ok) failedAt = 0L       // 刚配对：马上可以连
        return ok
    }

    // ----- 命令服务：一条常驻 exec: 流跑 ShellServer，所有命令与读屏都经它 -----
    private var client: ServerClient? = null

    /** 起命令服务（已在跑就直接用）：流断了就重开一条并等它报「ready」。 */
    @JvmStatic
    @Synchronized
    fun client(): ServerClient {
        client?.let { if (!it.closed) return it }
        val stream: AdbStream = AdbManager.get(app)
            .openStream("exec:" + ServerClient.command(app.applicationInfo.sourceDir))
        val c = ServerClient(stream.openInputStream(), stream.openOutputStream()) {
            synchronized(this) { if (client?.closed == true) client = null }
        }
        if (!c.awaitReady(15_000)) {
            stream.close()
            throw java.io.IOException("命令服务没有启动")
        }
        client = c
        return c
    }
}
