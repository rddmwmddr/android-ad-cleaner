package com.ahuamiao.adcleaner

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import com.chaquo.python.Python
import org.json.JSONObject
import rikka.shizuku.Shizuku
import java.io.File

/**
 * 界面就是桌面版的 gui/web/index.html；assets/mobile/ 里的脚本补上 pywebview 桥和手机上的首页（Shizuku 状态 + 一键开始）。
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private val app get() = application as AacApp

    private val binderListener = Shizuku.OnBinderReceivedListener { notifyShizuku() }
    private val deadListener = Shizuku.OnBinderDeadListener { notifyShizuku() }
    private val permissionListener = Shizuku.OnRequestPermissionResultListener { _, _ -> notifyShizuku() }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        web = WebView(this)
        // targetSdk 35 起强制全屏绘制：外面套一层让出状态栏、导航栏的高度（WebView 自己不认 padding）
        val frame = android.widget.FrameLayout(this)
        frame.addView(web)
        setContentView(frame)
        // 状态栏底色跟页面（index.html 的 --bg），浅色模式下图标用深色，不然时间、电量看不见
        val night = resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK ==
            android.content.res.Configuration.UI_MODE_NIGHT_YES
        frame.setBackgroundColor(if (night) 0xFF16181C.toInt() else 0xFFEEF0F4.toInt())
        if (Build.VERSION.SDK_INT >= 30 && !night) window.insetsController?.setSystemBarsAppearance(
            android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
            android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS)
        if (Build.VERSION.SDK_INT >= 30) frame.setOnApplyWindowInsetsListener { v, insets ->
            val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        WebView.setWebContentsDebuggingEnabled(applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.allowFileAccess = true
        web.addJavascriptInterface(Host(), "AacHost")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.scheme == "file") return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                val css = assets.open("mobile/mobile.css").bufferedReader().readText()
                val js = assets.open("mobile/mobile.js").bufferedReader().readText()
                view.evaluateJavascript("(function(){const s=document.createElement('style');s.textContent=" +
                    JSONObject.quote(css) + ";document.head.appendChild(s);})();\n" + js, null)
            }
        }
        Shizuku.addBinderReceivedListenerSticky(binderListener)
        Shizuku.addBinderDeadListener(deadListener)
        Shizuku.addRequestPermissionResultListener(permissionListener)
        app.worker.execute {
            val error = try {
                app.booted.get(); null
            } catch (e: Exception) {
                e.cause?.toString() ?: e.toString()
            }
            runOnUiThread {
                if (error != null) {
                    web.loadData("<h3>启动失败</h3><pre>${android.text.Html.escapeHtml(error)}</pre>", "text/html; charset=utf-8", null)
                } else {
                    web.loadUrl(Uri.fromFile(File(filesDir, "aac/gui/web/index.html")).toString())
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        current = this
        notifyShizuku()
    }

    override fun onPause() {
        if (current === this) current = null
        super.onPause()
    }

    override fun onDestroy() {
        Shizuku.removeBinderReceivedListener(binderListener)
        Shizuku.removeBinderDeadListener(deadListener)
        Shizuku.removeRequestPermissionResultListener(permissionListener)
        super.onDestroy()
    }

    /** 让页面重新问一次权限状态（页面收到后调 AacHost.checkState()）。 */
    private fun notifyShizuku() = runOnUiThread {
        if (::web.isInitialized) web.evaluateJavascript("window.__aacShizuku && window.__aacShizuku()", null)
    }

    /**
     * 能不能以 shell 身份执行，以及差哪一步。两条路任一可用就是 ready：
     * - Shizuku：装了且在跑，沿用它的授权流程（ask / denied）；
     * - 内置无线调试（#622，安卓 11 起）：need_dev 没开开发者选项 → need_wifi 没开无线调试 → need_pair 没配对。
     * 安卓 10 及以下没有无线调试：old（没装 Shizuku）/ stopped（装了没启动）。
     * 连接要经 mDNS 找端口，最多等几秒，只在后台线程调。
     */
    private fun shellState(): String {
        val shizukuUp = installed(SHIZUKU) && runCatching { Shizuku.pingBinder() }.getOrDefault(false)
        if (shizukuUp && !Shizuku.isPreV11() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) return "ready"
        if (Build.VERSION.SDK_INT < 30) {
            return when {
                !installed(SHIZUKU) -> "old"
                !shizukuUp -> "stopped"
                Shizuku.shouldShowRequestPermissionRationale() -> "denied"
                else -> "ask"
            }
        }
        if (AdbShell.ready() || AdbShell.connect(4000)) return "ready"
        if (shizukuUp) return if (Shizuku.shouldShowRequestPermissionRationale()) "denied" else "ask"
        return when {
            !AdbManager.developerOn(this) -> "need_dev"
            !AdbManager.wirelessOn(this) -> "need_wifi"
            else -> "need_pair"
        }
    }

    private fun installed(pkg: String) = try {
        packageManager.getPackageInfo(pkg, 0); true
    } catch (_: PackageManager.NameNotFoundException) {
        false
    }

    inner class Host {
        /** 界面的一次 api 调用：后台线程跑 Python，结果回调给页面里的 __aacDone(id, json)。 */
        @JavascriptInterface
        fun call(id: Int, method: String, args: String) {
            app.worker.execute {
                val result = try {
                    Python.getInstance().getModule("aac_android.main").callAttr("call", method, args).toString()
                } catch (e: Throwable) {
                    JSONObject().put("error", e.toString()).toString()
                }
                runOnUiThread { web.evaluateJavascript("window.__aacDone($id, ${JSONObject.quote(result)})", null) }
            }
        }

        /** 异步查权限状态，结果回调给页面里的 __aacState(状态)。 */
        @JavascriptInterface
        fun checkState() {
            app.worker.execute {
                val state = try {
                    shellState()
                } catch (_: Throwable) {
                    "need_pair"
                }
                runOnUiThread { web.evaluateJavascript("window.__aacState && window.__aacState('$state')", null) }
            }
        }

        @JavascriptInterface
        fun startPairing() = runOnUiThread { Pairing.start(this@MainActivity) }

        @JavascriptInterface
        fun openSettings(which: String) = runOnUiThread {
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

        @JavascriptInterface
        fun requestShizuku() = runOnUiThread {
            try {
                Shizuku.requestPermission(1)
            } catch (_: Throwable) {
                notifyShizuku()
            }
        }

        @JavascriptInterface
        fun openShizuku() = runOnUiThread {
            val launch = packageManager.getLaunchIntentForPackage(SHIZUKU)
            startActivity(launch ?: Intent(Intent.ACTION_VIEW, Uri.parse(SHIZUKU_PAGE)))
        }

        @JavascriptInterface
        fun openUrl(url: String) = Native.openUrl(url)
    }

    companion object {
        @Volatile private var current: MainActivity? = null

        /** 配对成功等事件：让开着的界面重新查一次状态。 */
        @JvmStatic
        fun refreshState() {
            current?.notifyShizuku()
        }

        const val SHIZUKU = "moe.shizuku.privileged.api"
        const val SHIZUKU_PAGE = "https://shizuku.rikka.app/zh-hans/download/"
    }
}
