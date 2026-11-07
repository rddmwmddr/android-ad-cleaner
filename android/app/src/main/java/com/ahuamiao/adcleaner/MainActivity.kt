package com.ahuamiao.adcleaner

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import com.ahuamiao.adcleaner.ui.App
import com.ahuamiao.adcleaner.ui.Demo
import com.ahuamiao.adcleaner.ui.HostActions
import rikka.shizuku.Shizuku

/** 界面在 ui/（Compose，ADR-0018）；这里只放要 Activity 才做得了的系统动作。页面状态在进程级的 AppModel。 */
class MainActivity : ComponentActivity(), HostActions {
    private val app get() = application as AacApp

    private val binderListener = Shizuku.OnBinderReceivedListener { refreshState() }
    private val deadListener = Shizuku.OnBinderDeadListener { refreshState() }
    private val permissionListener = Shizuku.OnRequestPermissionResultListener { _, _ -> refreshState() }

    private val capture = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val data = result.data
        if (result.resultCode == RESULT_OK && data != null && Build.VERSION.SDK_INT >= 30) {
            PairingService.start(this, result.resultCode, data)
            Pairing.openWireless(this)
        } else {
            Pairing.start(this)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        Demo.handle(intent, app.model)
        setContent { App(app.model, this) }
        Shizuku.addBinderReceivedListenerSticky(binderListener)
        Shizuku.addBinderDeadListener(deadListener)
        Shizuku.addRequestPermissionResultListener(permissionListener)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Demo.handle(intent, app.model)
    }

    override fun onStart() {
        super.onStart()
        app.model.setForeground(true)
    }

    override fun onResume() {
        super.onResume()
        current = this
        Native.foreground(true)
        app.model.start()
    }

    override fun onPause() {
        if (current === this) current = null
        Native.foreground(false)
        super.onPause()
    }

    override fun onStop() {
        app.model.setForeground(false)
        super.onStop()
    }

    override fun onDestroy() {
        Shizuku.removeBinderReceivedListener(binderListener)
        Shizuku.removeBinderDeadListener(deadListener)
        Shizuku.removeRequestPermissionResultListener(permissionListener)
        super.onDestroy()
    }

    /**
     * 开始授权（#634）：先请求一次截取屏幕，允许了就由 PairingService 自动读配对码；
     * 不允许或安卓版本不支持，退回通知栏手动填写。
     */
    override fun startPairing() {
        if (PairingService.waiting) {                 // 已经在等配对码了：别再要一次截屏许可（#662）
            Pairing.openWireless(this)
            return
        }
        val mpm = getSystemService(android.media.projection.MediaProjectionManager::class.java)
        val ask = if (Build.VERSION.SDK_INT >= 34)
            mpm.createScreenCaptureIntent(android.media.projection.MediaProjectionConfig.createConfigForDefaultDisplay())
        else mpm.createScreenCaptureIntent()
        try {
            capture.launch(ask)
        } catch (_: Exception) {
            Pairing.start(this)
        }
    }

    override fun openSettings(which: String) {
        val action = when (which) {
            "about" -> android.provider.Settings.ACTION_DEVICE_INFO_SETTINGS
            else -> android.provider.Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS
        }
        try {
            startActivity(Intent(action))
        } catch (_: Exception) {
            startActivity(Intent(android.provider.Settings.ACTION_SETTINGS))
        }
    }

    /**
     * 授权 Shizuku。没装 → 下载页；装了没启动，或拒绝过（系统不再弹窗）→ 打开 Shizuku 自己处理。
     * 只在这两种情况下拿到 binder 之外的结果都是一样的：让用户去 Shizuku 那边动手，
     * 否则这里只会抛异常、页面重查还是原样，点了像没反应。设置页的次级入口也落到这里。
     */
    override fun requestShizuku() {
        val up = ShellAccess.installed(this, ShellAccess.SHIZUKU) && runCatching { Shizuku.pingBinder() }.getOrDefault(false)
        if (!up || runCatching { Shizuku.shouldShowRequestPermissionRationale() }.getOrDefault(false)) {
            openShizuku()
            return
        }
        try {
            Shizuku.requestPermission(1)
        } catch (_: Throwable) {
            openShizuku()
        }
    }

    override fun openShizuku() {
        val launch = packageManager.getLaunchIntentForPackage(ShellAccess.SHIZUKU)
        startActivity(launch ?: Intent(Intent.ACTION_VIEW, Uri.parse(ShellAccess.SHIZUKU_PAGE)))
    }

    companion object {
        @Volatile private var current: MainActivity? = null

        /** 配对成功等事件：让界面重新查一次状态。 */
        @JvmStatic
        fun refreshState() {
            Native.onMain { (Native.app as AacApp).model.refresh() }
        }

        /** 界面正开着（用户在看着）：后台自动做的事（重开无线调试）不必再发通知。 */
        @JvmStatic
        fun inForeground(): Boolean = current != null
    }
}
