package com.ahuamiao.adcleaner

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.media.MediaPlayer
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import android.widget.Toast
import java.io.File

/**
 * Python 侧要用到的系统能力：打开网页、复制、提示音、执行期间保活。桌面版在这些地方用 webbrowser / afplay / winsound。
 * 由 aac_android 经 Chaquopy 的 jclass 调用，全部是静态方法。
 */
object Native {
    lateinit var app: Context
    private val main = Handler(Looper.getMainLooper())

    /** 从后台线程切回主线程做一件事。 */
    fun onMain(block: () -> Unit) {
        main.post(block)
    }

    @JvmStatic
    fun openUrl(url: String) = main.post {
        app.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    @JvmStatic
    fun copy(text: String) = main.post {
        val cm = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("肉呆去广告", text))
        Toast.makeText(app, "已复制", Toast.LENGTH_SHORT).show()
    }

    /**
     * 引擎往输入框里写中文：先放进剪贴板，紧接着发粘贴键（读屏不经选择器写字）。
     * 不走 `main.post`：粘贴键随后就到，晚一步会粘出上一份内容。
     */
    @JvmStatic
    fun setClipboard(text: String) {
        val cm = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("肉呆去广告", text))
    }

    @JvmStatic
    fun toast(text: String) = main.post { Toast.makeText(app, text, Toast.LENGTH_LONG).show() }

    @JvmStatic
    fun chime(path: String) = main.post {
        val file = File(path)
        if (!file.exists()) return@post
        try {
            MediaPlayer().apply {
                setDataSource(file.path)
                setOnCompletionListener { it.release() }
                prepare()
                start()
            }
        } catch (_: Exception) {
        }
    }

    /** 执行开始 / 结束：前台服务保住进程（执行中本 App 在后台，系统可能回收它）。屏幕锁随服务的生命周期走，见下面一对入口。 */
    @JvmStatic
    fun busy(on: Boolean, background: Boolean) = main.post {
        val intent = Intent(app, KeepAliveService::class.java).putExtra(KeepAliveService.BACKGROUND, background)
        if (on) app.startForegroundService(intent) else app.stopService(intent)
    }

    private var awake: PowerManager.WakeLock? = null

    /** 三小时。远长于任何单轮，只在 `onDestroy` 也跑不到（进程被厂商冻结）时兜底。 */
    private const val AWAKE_TIMEOUT_MS = 3 * 60 * 60 * 1000L

    /**
     * 执行期间保持亮屏（#728）。手机版多半没插电，引擎设的「插电常亮」不起作用，手机放着就锁屏，后面几段全断。
     * 悬浮胶囊带 FLAG_KEEP_SCREEN_ON；没给悬浮窗权限、或本 App 在前台收起胶囊时，靠这把屏幕锁。
     *
     * 锁的持有与释放只由前台服务的生命周期决定（#769）：`KeepAliveService` 转成前台时调这里，`onDestroy`
     * 调 [releaseAwake]，`busy()` 不再碰锁——否则服务被单独停掉时锁会一直留到进程结束。
     *
     * 超时是兜底而不是执行上限：进程被冻结时 `onDestroy` 也跑不到，只能等系统到点收走。三小时远长于任何
     * 单轮，正常执行撞不上，#746「整轮超过一小时不再丢锁」的结论没变。也没选「定时续期」：那要多一个
     * 常驻定时器，换来的效果和到点收回一样。用户自己按电源键息屏不拦，引擎照旧等解锁。
     */
    @Suppress("DEPRECATION")   // 后台服务没有窗口可挂 FLAG_KEEP_SCREEN_ON，只能用屏幕锁
    internal fun acquireAwake() {
        releaseAwake()
        val pm = app.getSystemService(PowerManager::class.java)
        awake = pm.newWakeLock(PowerManager.SCREEN_DIM_WAKE_LOCK or PowerManager.ON_AFTER_RELEASE, "aac:run").apply {
            setReferenceCounted(false)
            acquire(AWAKE_TIMEOUT_MS)
        }
    }

    /** 放锁。超时已经自动收走时 `isHeld` 为假，这里什么也不做。 */
    internal fun releaseAwake() {
        awake?.let { if (it.isHeld) it.release() }
        awake = null
    }

    private var capsule: View? = null

    /**
     * 执行期间屏幕左边缘的「去广告中」胶囊。小米 HyperOS 会冻结退到后台的 App（前台服务、省电白名单都挡不住），
     * 冻住后脚本停在当时那一行；有可见悬浮窗的 App 不冻（18 Pro Max 实测）。胶囊点击穿透，不挡引擎的点按；
     * 放在左边缘，不盖住右侧的开关（截图取色看开关颜色）。窗口带 FLAG_KEEP_SCREEN_ON：看得见胶囊时，
     * 不管前台是哪个 App 都不息屏（#728）。
     */
    @JvmStatic
    fun capsule(on: Boolean, label: String) = main.post {
        val wm = app.getSystemService(WindowManager::class.java)
        capsule?.let { runCatching { wm.removeView(it) } }
        capsule = null
        if (!on || !Settings.canDrawOverlays(app)) return@post
        val dp = app.resources.displayMetrics.density
        val view = TextView(app).apply {
            text = label.ifEmpty { "肉呆去广告中" }
            textSize = 11f
            setTextColor(0xFFFFFFFF.toInt())
            setPadding((8 * dp).toInt(), (5 * dp).toInt(), (10 * dp).toInt(), (5 * dp).toInt())
            background = GradientDrawable().apply { setColor(0xCC2F6FEC.toInt()); cornerRadius = 14 * dp }
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
            PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.START or Gravity.CENTER_VERTICAL }
        view.visibility = if (MainActivity.inForeground()) View.GONE else View.VISIBLE
        runCatching { wm.addView(view, lp); capsule = view }
    }

    /**
     * 本 App 在前台时收起胶囊：它是给后台防冻结用的，盖在自己的页面上多余。
     * 「在不在前台」只记在 MainActivity 一处（#662），这里只跟着它改胶囊的显隐。
     */
    @JvmStatic
    fun foreground(on: Boolean) = main.post {
        capsule?.visibility = if (on) View.GONE else View.VISIBLE
    }

    /** 后台屏模式跑完：不抢前台（用户可能正在用别的 App），发一条通知，点它回到本 App 看结果。 */
    @JvmStatic
    fun done(title: String, text: String) = main.post {
        val nm = app.getSystemService(android.app.NotificationManager::class.java)
        nm.createNotificationChannel(android.app.NotificationChannel(DONE_CHANNEL, "执行结果",
            android.app.NotificationManager.IMPORTANCE_DEFAULT))
        val open = android.app.PendingIntent.getActivity(app, 2, Intent(app, MainActivity::class.java),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(2, android.app.Notification.Builder(app, DONE_CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build())
    }

    /**
     * 首次设置时用户切到系统设置：通知栏说明这一步做什么（#646）。title 传 null 收回。
     * 与配对的前台通知分开一条（不同 ID），免得两边互相盖掉。
     * 不设 ongoing：设置阶段没有前台服务保活，进程被系统收掉后就没人来撤它了，留一条划不掉的旧步号；
     * 启动时 `AppModel.start()` 会补一次收回。
     */
    @JvmStatic
    fun setupNotice(title: String?, text: String) = main.post {
        val nm = app.getSystemService(android.app.NotificationManager::class.java)
        if (title == null) {
            nm.cancel(SETUP_ID)
            return@post
        }
        nm.createNotificationChannel(android.app.NotificationChannel(SETUP_CHANNEL, "首次设置",
            android.app.NotificationManager.IMPORTANCE_LOW))
        val open = android.app.PendingIntent.getActivity(app, 7, Intent(app, MainActivity::class.java),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(SETUP_ID, android.app.Notification.Builder(app, SETUP_CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(android.app.Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build())
    }

    /** 执行好一阵没有进展：用户可能正在用别的 App，看不到执行页。有进展了就收回。 */
    fun stallNotice(on: Boolean) = main.post {
        val nm = app.getSystemService(android.app.NotificationManager::class.java)
        if (!on) {
            nm.cancel(STALL_ID)
            return@post
        }
        nm.createNotificationChannel(android.app.NotificationChannel(DONE_CHANNEL, "执行结果",
            android.app.NotificationManager.IMPORTANCE_DEFAULT))
        val open = android.app.PendingIntent.getActivity(app, 5, Intent(app, MainActivity::class.java),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(STALL_ID, android.app.Notification.Builder(app, DONE_CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_warning)
            .setContentTitle("去广告可能卡住了")
            .setContentText("已经 1 分钟没有进展，点这里看看")
            .setContentIntent(open)
            .setAutoCancel(true)
            .build())
    }

    private const val STALL_ID = 5
    private const val DONE_CHANNEL = "done"
    private const val SETUP_ID = 7
    private const val SETUP_CHANNEL = "setup"

    /** 执行完回到本 App，让用户看到结果（引擎最后会回桌面）。 */
    @JvmStatic
    fun bringToFront() = main.post {
        app.startActivity(Intent(app, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
    }
}
