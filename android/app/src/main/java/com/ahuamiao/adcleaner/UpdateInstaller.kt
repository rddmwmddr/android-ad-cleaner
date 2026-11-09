package com.ahuamiao.adcleaner

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit

/** 不调用 shell 安装；权限与安装确认均由系统界面交给机主。 */
internal object UpdateInstaller {
    @Suppress("DEPRECATION")
    private fun identity(info: PackageInfo): UpdateIdentity {
        val signatures = if (Build.VERSION.SDK_INT >= 28) info.signingInfo?.apkContentsSigners else info.signatures
        val signers = signatures.orEmpty().map { signature ->
            MessageDigest.getInstance("SHA-256").digest(signature.toByteArray()).joinToString("") { "%02x".format(it.toInt() and 0xff) }
        }.toSet()
        val code = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()
        return UpdateIdentity(info.packageName, info.versionName.orEmpty(), code, signers)
    }

    @Suppress("DEPRECATION")
    fun install(context: Context, path: String, version: String): String = try {
        val file = File(path).canonicalFile
        val root = File(context.filesDir, "data/updates").canonicalFile
        require(file.parentFile == root && file.isFile && file.extension == "apk") { "更新文件不在本 App 的更新目录里" }
        val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
        val pm = context.packageManager
        val current = identity(pm.getPackageInfo(context.packageName, flags))
        val candidate = pm.getPackageArchiveInfo(file.path, flags) ?: error("无法读取 APK，请重新下载")
        current.rejection(identity(candidate), version)?.let { error(it) }
        val (intent, message) = if (!pm.canRequestPackageInstalls()) {
            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")) to
                "请在系统页面允许本 App 安装应用，回来后再点「安装更新」"
        } else {
            val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", file)
            Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION) to "请在系统页面确认更新；如果取消，可以再次点「安装更新」"
        }
        val start = FutureTask {
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        if (Looper.myLooper() == Looper.getMainLooper()) start.run() else Handler(Looper.getMainLooper()).post(start)
        start.get(5, TimeUnit.SECONDS)
        JSONObject().put("message", message).toString()
    } catch (e: Exception) {
        JSONObject().put("error", e.cause?.message ?: e.message ?: "无法打开系统安装界面").toString()
    }
}
