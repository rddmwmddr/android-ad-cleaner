package com.ahuamiao.adcleaner

import android.app.Application
import android.os.Build
import com.ahuamiao.adcleaner.ui.AppModel
import com.ahuamiao.adcleaner.ui.PythonBackend
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.Future
import kotlinx.coroutines.MainScope
import rikka.sui.Sui

/**
 * 进程级：解出引擎文件、起 Python、调 aac_android.main.boot。界面打开前就在后台开始，界面等它。
 */
class AacApp : Application() {
    lateinit var booted: Future<String>
    val worker = Executors.newCachedThreadPool()

    /** 页面状态：Activity 被系统回收后重新打开，接着这一份。 */
    val model by lazy { AppModel(PythonBackend(this), MainScope(), Build.BRAND) }

    override fun onCreate() {
        super.onCreate()
        Native.app = this
        AdbShell.app = this
        // Sui（#1451）：在 Zygisk 里直接递来 binder，不经 ShizukuProvider；不是 Sui 时返回 false，什么也不做。
        ShellAccess.sui = runCatching { Sui.init(packageName) }.getOrDefault(false)
        booted = worker.submit<String> {
            val base = extract()
            if (!Python.isStarted()) Python.start(AndroidPlatform(this))
            Python.getInstance().getModule("aac_android.main")
                .callAttr("boot", base.path, File(filesDir, "data").path, cacheDir.path, packageName).toString()
        }
    }

    /** assets/aac → files/aac。App 更新（lastUpdateTime 变了）才重新解，备份在 files/data，不受影响。 */
    private fun extract(): File {
        val base = File(filesDir, "aac")
        val stamp = File(filesDir, "aac.stamp")
        val want = packageManager.getPackageInfo(packageName, 0).lastUpdateTime.toString()
        if (stamp.exists() && stamp.readText() == want && base.isDirectory) return base
        base.deleteRecursively()
        copy("aac", base)
        stamp.writeText(want)
        return base
    }

    private fun copy(path: String, to: File) {
        val children = assets.list(path).orEmpty()
        if (children.isEmpty()) {
            to.parentFile?.mkdirs()
            assets.open(path).use { input -> to.outputStream().use { input.copyTo(it) } }
            return
        }
        to.mkdirs()
        for (child in children) copy("$path/$child", File(to, child))
    }
}
