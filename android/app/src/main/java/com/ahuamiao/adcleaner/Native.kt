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

    @JvmStatic
    fun openUrl(url: String) = main.post {
        app.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    @JvmStatic
    fun copy(text: String) = main.post {
        val cm = app.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("安卓去广告", text))
        Toast.makeText(app, "已复制", Toast.LENGTH_SHORT).show()
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

    /** 执行开始 / 结束：前台服务保住进程（执行中本 App 在后台，系统可能回收它）。 */
    @JvmStatic
    fun busy(on: Boolean) = main.post {
        val intent = Intent(app, KeepAliveService::class.java)
        if (on) app.startForegroundService(intent) else app.stopService(intent)
    }

    private var capsule: View? = null

    /**
     * 执行期间屏幕左边缘的「去广告中」胶囊。小米 HyperOS 会冻结退到后台的 App（前台服务、省电白名单都挡不住），
     * 冻住后脚本停在当时那一行；有可见悬浮窗的 App 不冻（18 Pro Max 实测）。胶囊点击穿透，不挡引擎的点按；
     * 放在左边缘，不盖住右侧的开关（截图取色看开关颜色）。
     */
    @JvmStatic
    fun capsule(on: Boolean) = main.post {
        val wm = app.getSystemService(WindowManager::class.java)
        capsule?.let { runCatching { wm.removeView(it) } }
        capsule = null
        if (!on || !Settings.canDrawOverlays(app)) return@post
        val dp = app.resources.displayMetrics.density
        val view = TextView(app).apply {
            text = "净 去广告中"
            textSize = 11f
            setTextColor(0xFFFFFFFF.toInt())
            setPadding((8 * dp).toInt(), (5 * dp).toInt(), (10 * dp).toInt(), (5 * dp).toInt())
            background = GradientDrawable().apply { setColor(0xCC2F6FEC.toInt()); cornerRadius = 14 * dp }
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.START or Gravity.CENTER_VERTICAL }
        runCatching { wm.addView(view, lp); capsule = view }
    }

    /** 执行完回到本 App，让用户看到结果（引擎最后会回桌面）。 */
    @JvmStatic
    fun bringToFront() = main.post {
        app.startActivity(Intent(app, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
    }
}
