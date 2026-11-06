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
        notifyShizuku()
    }

    override fun onDestroy() {
        Shizuku.removeBinderReceivedListener(binderListener)
        Shizuku.removeBinderDeadListener(deadListener)
        Shizuku.removeRequestPermissionResultListener(permissionListener)
        super.onDestroy()
    }

    private fun notifyShizuku() = runOnUiThread {
        if (::web.isInitialized) web.evaluateJavascript("window.__aacShizuku && window.__aacShizuku()", null)
    }

    private fun shizukuState(): String = when {
        !installed(SHIZUKU) -> "missing"
        !Shizuku.pingBinder() -> "stopped"
        Shizuku.isPreV11() -> "old"
        Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED -> "ready"
        Shizuku.shouldShowRequestPermissionRationale() -> "denied"
        else -> "ask"
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

        @JavascriptInterface
        fun shizuku(): String = try {
            shizukuState()
        } catch (_: Throwable) {
            "stopped"
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
        const val SHIZUKU = "moe.shizuku.privileged.api"
        const val SHIZUKU_PAGE = "https://shizuku.rikka.app/zh-hans/download/"
    }
}
