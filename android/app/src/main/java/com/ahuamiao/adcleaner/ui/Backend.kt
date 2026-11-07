package com.ahuamiao.adcleaner.ui

import com.ahuamiao.adcleaner.AacApp
import com.ahuamiao.adcleaner.ShellAccess
import com.chaquo.python.Python
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

class EngineError(message: String) : Exception(message)

/** 界面能向后台要的全部东西。真的后台是 Python；debug 构建的演示数据也实现它（见 src/debug）。 */
interface Backend {
    /** 等引擎解压、Python 起来，返回版本号。 */
    suspend fun boot(): String

    /** 普通方法名落到 gui/app.py 的 Api，`view.xxx` 落到 aac_android/view.py。 */
    suspend fun call(method: String, vararg args: Any?): Any?

    /** 能不能以 shell 身份执行、差哪一步，见 [ShellAccess.state]。 */
    suspend fun shellState(): String
}

class PythonBackend(private val app: AacApp) : Backend {
    private val dispatcher = app.worker.asCoroutineDispatcher()

    override suspend fun boot(): String = withContext(dispatcher) {
        try {
            app.booted.get()
        } catch (e: Exception) {
            throw EngineError(e.cause?.toString() ?: e.toString())
        }
    }

    override suspend fun call(method: String, vararg args: Any?): Any? = withContext(dispatcher) {
        val payload = JSONArray().apply { args.forEach { put(it ?: JSONObject.NULL) } }.toString()
        val raw = Python.getInstance().getModule("aac_android.main").callAttr("call", method, payload).toString()
        val result = JSONObject(raw)
        if (!result.has("ok")) throw EngineError(result.optString("error", "未知错误"))
        result.get("ok").takeUnless { it == JSONObject.NULL }
    }

    override suspend fun shellState(): String = withContext(dispatcher) {
        runCatching { ShellAccess.state(app) }.getOrDefault("need_pair")
    }
}
