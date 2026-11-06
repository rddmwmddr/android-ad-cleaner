package com.ahuamiao.adcleaner

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Log
import android.view.WindowManager
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import io.github.muntashirakon.adb.android.AdbMdns
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * 授权时自动读配对码（#634）。用户允许一次截取屏幕后，这里等「使用配对码配对设备」对话框出现（mDNS 上冒出配对端口），
 * 截一帧、在本机识别 6 位数字、直接配对并连上。用户不用输入，也不用拉通知栏。
 *
 * 不用悬浮窗：系统设置的基类（SettingsBaseActivity）默认隐藏第三方悬浮窗，引导卡在设置页里会消失。
 * 截屏帧只在内存里识别，不存盘、不外传；配对完成、超时或用户点「停止」都立刻停止截屏。
 * 认不出（截到黑屏、识别不到数字、配对被拒）时退回通知栏手动填写。
 */
@androidx.annotation.RequiresApi(30)
class PairingService : Service() {
    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private lateinit var looper: HandlerThread
    @Volatile private var stopped = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            finish(null)
            return START_NOT_STICKY
        }
        @Suppress("DEPRECATION") val data = intent?.getParcelableExtra<Intent>(DATA)
        val code = intent?.getIntExtra(CODE, 0) ?: 0
        startForeground(ID, status("正在等你打开配对码", "在「无线调试」里点「使用配对码配对设备」，本 App 会读出屏幕上的 6 位数字完成授权。"),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        if (data == null || projection != null) return START_NOT_STICKY
        looper = HandlerThread("aac-pair").also { it.start() }
        val handler = Handler(looper.looper)
        val mp = getSystemService(MediaProjectionManager::class.java).getMediaProjection(code, data)
        projection = mp
        mp.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() = finish(null)
        }, handler)
        val bounds = getSystemService(WindowManager::class.java).maximumWindowMetrics.bounds
        // 识别数字用不着全分辨率：宽缩到 1080 以内，省内存
        val scale = minOf(1f, 1080f / bounds.width())
        val w = (bounds.width() * scale).toInt()
        val h = (bounds.height() * scale).toInt()
        val r = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        reader = r
        display = mp.createVirtualDisplay("aac-pair", w, h, resources.displayMetrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, r.surface, null, handler)
        thread(name = "aac-pair-watch") { watch() }
        return START_NOT_STICKY
    }

    /**
     * 等配对端口出现 → 截帧识别 → 配对 → 连接。整体最多等 5 分钟。
     * 端口要先确认有人在听：mDNS 会把上一次对话框的端口留一会儿（模拟器实测），连过去被拒，那不是数字认错了。
     */
    private fun watch() {
        AdbShell.app = applicationContext
        val deadline = System.currentTimeMillis() + 5 * 60_000
        val tried = mutableSetOf<String>()      // 这个端口上配对被拒过的数字
        val dead = mutableSetOf<Int>()
        var port = -1
        var seenAt = 0L
        var black = 0
        while (!stopped && System.currentTimeMillis() < deadline) {
            if (port <= 0 || !AdbManager.alive(port)) {
                if (port > 0) dead += port
                port = AdbManager.discover(applicationContext, AdbMdns.SERVICE_TYPE_TLS_PAIRING, 3000, dead)
                if (port > 0 && !AdbManager.alive(port)) {
                    dead += port; port = -1
                }
                if (port <= 0) continue
                Log.i(TAG, "配对对话框开了，端口 $port")
                tried.clear(); seenAt = System.currentTimeMillis(); black = 0     // 新对话框是新的数字
            }
            val frame = grab()
            if (frame == null) {
                Thread.sleep(300); continue
            }
            if (dark(frame)) {
                frame.recycle()
                if (++black >= 4) return fallback("这台手机的配对页不让截屏，请手动填写 6 位数字。")
                Thread.sleep(500); continue
            }
            val codes = read(frame).filter { it !in tried }
            frame.recycle()
            if (codes.isEmpty()) {
                if (System.currentTimeMillis() - seenAt > 15_000) return fallback("没认出屏幕上的 6 位数字，请手动填写。")
                Thread.sleep(400); continue
            }
            for (c in codes) {
                val paired = try {
                    AdbShell.pairAt(port, c)
                } catch (e: java.net.ConnectException) {
                    Log.i(TAG, "端口 $port 已关闭"); dead += port; port = -1; break
                } catch (e: Throwable) {
                    Log.w(TAG, "配对被拒：${e.javaClass.simpleName}"); false
                }
                if (!paired) {
                    tried += c; continue
                }
                val connected = AdbShell.connect(8000)
                Log.i(TAG, "配对成功，连接${if (connected) "成功" else "未成功"}")
                finish(if (connected) "授权完成，以后不用再做" else "授权完成")
                // 用户还停在系统设置里：连上了就以 shell 身份把本 App 调回前台（后台服务自己起不了界面）
                if (connected) AdbShell.exec("am start -n $packageName/.MainActivity")
                return
            }
        }
        if (!stopped) fallback("等了 5 分钟没有看到配对码。回到「安卓去广告」再点一次「开始授权」。", input = false)
    }

    private fun grab(): Bitmap? {
        val image = reader?.acquireLatestImage() ?: return null
        return try {
            val plane = image.planes[0]
            val pad = plane.rowStride - plane.pixelStride * image.width
            val bmp = Bitmap.createBitmap(image.width + pad / plane.pixelStride, image.height, Bitmap.Config.ARGB_8888)
            bmp.copyPixelsFromBuffer(plane.buffer)
            if (pad == 0) bmp else Bitmap.createBitmap(bmp, 0, 0, image.width, image.height).also { bmp.recycle() }
        } finally {
            image.close()
        }
    }

    /** 整帧几乎全黑：页面设了禁止截屏。抽 400 个点看。 */
    private fun dark(bmp: Bitmap): Boolean {
        var lit = 0
        for (i in 0 until 400) {
            val p = bmp.getPixel((i * 7919) % bmp.width, (i * 104729) % bmp.height)
            if ((p shr 16 and 0xff) + (p shr 8 and 0xff) + (p and 0xff) > 60) lit++
        }
        return lit < 8
    }

    /** 帧里独立成段的 6 位数字。IP、端口挨着「.」「:」，不算。 */
    private fun read(bmp: Bitmap): List<String> {
        val text = try {
            Tasks.await(TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
                .process(InputImage.fromBitmap(bmp, 0)), 8, TimeUnit.SECONDS)
        } catch (e: Exception) {
            Log.w(TAG, "识别失败", e); return emptyList()
        }
        return codes(text.textBlocks.flatMap { b -> b.lines.map { it.text } })
    }

    private fun finish(done: String?) {
        if (stopped) return
        stopped = true
        runCatching { display?.release() }
        runCatching { reader?.close() }
        runCatching { projection?.stop() }
        if (::looper.isInitialized) looper.quitSafely()
        stopForeground(STOP_FOREGROUND_REMOVE)
        if (done != null) Pairing.notify(this, done, "点这里回到「安卓去广告」开始去广告")
        MainActivity.refreshState()
        stopSelf()
    }

    private fun fallback(why: String, input: Boolean = true) {
        Log.i(TAG, "退回手动：$why")
        finish(null)
        if (input) Pairing.notify(this, "请手动填写 6 位数字", why + "下拉通知栏，点这条通知下方的「填写」。", input = true)
        else Pairing.notify(this, "授权没有完成", why)
    }

    private fun status(title: String, text: String): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "授权", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(this, 5, Intent(this, PairingService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "停止", stop).build())
            .build()
    }

    companion object {
        private const val TAG = "AacPair"
        private const val ID = 6
        private const val CHANNEL = "pair-watch"
        private const val STOP = "stop"
        const val DATA = "data"
        const val CODE = "code"

        /** 识别结果里的配对码候选：整行就是 6 位数字（中间可有空格），或行里独立的 6 位数字。 */
        @JvmStatic
        fun codes(lines: List<String>): List<String> {
            val out = linkedSetOf<String>()
            for (line in lines) {
                val compact = line.replace(" ", "")
                if (Regex("\\d{6}").matches(compact)) out += compact
                Regex("(?<![\\d.:])\\d{6}(?![\\d.:])").findAll(line).forEach { out += it.value }
            }
            return out.toList()
        }

        fun start(context: Context, code: Int, data: Intent) {
            context.startForegroundService(Intent(context, PairingService::class.java).putExtra(CODE, code).putExtra(DATA, data))
        }
    }
}
