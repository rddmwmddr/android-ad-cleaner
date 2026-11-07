package com.ahuamiao.adcleaner.ui

import android.content.Intent
import org.json.JSONArray
import org.json.JSONObject

/**
 * 只在 debug 构建里：不连手机、不跑引擎，逐屏验收界面。
 * `adb shell am start -n com.ahuamiao.adcleaner/.MainActivity --es demo home [--es sheet more]`
 * 页面：setup1 setup2 setup3 setup3mi old stopped-sh ask denied nodev home prepare0 prepare1 choose
 * blocked norecipe scanfail run paused pausing stalled fgmode stopping done failed stopped failed2
 * 面板：more newer restore restored feedback report log；对话框：devoff
 *
 * 首次设置的三个演示页仍从真的 view.py 取三步文案（#646）：要先等 Python 启动，期间显示启动页。
 */
object Demo {
    private val device = Device("demo", "OPPO Find X10 Pro Max", "PKD110")

    fun handle(intent: Intent?, model: AppModel) {
        intent?.getStringExtra("plan")?.let {        // 真引擎验收：--es plan '<计划 JSON>'
            model.debugStart(JSONObject(it))
            return
        }
        if (intent?.getStringExtra("call") == "pause") {   // 真引擎验收：让它停在步骤边界，再用真按钮点继续 / 停止
            model.togglePause()
            return
        }
        val name = intent?.getStringExtra("demo") ?: return
        val sheet = intent.getStringExtra("sheet")
        model.demoVersion("0.3.2", if (sheet == "newer") NewVersion("0.3.3", "https://example.invalid") else null)
        model.demoBrand(if (name == "setup3mi") "Xiaomi" else "OPPO")

        val backend = DemoBackend(when (name) {
            "setup1" -> "need_dev"
            "setup2" -> "need_wifi"
            "setup3", "setup3mi" -> "need_pair"
            "old", "ask", "denied" -> name
            "stopped-sh" -> "stopped"
            else -> "ready"
        }, name != "nodev")
        val selection = when (name) {
            "choose" -> selection(detection())
            "blocked" -> Selection(Detection.parse(detection().put("blocked", true).put("warnings", JSONArray(listOf("手机锁屏了。解锁并保持亮屏，再重新检测。")))))
            "norecipe" -> selection(detection().put("steps", JSONArray()).put("manual_name", "OPPO / ColorOS").put("manual_url", "https://example.invalid"))
            "scanfail" -> Selection(Detection.parse(detection())).apply { scan = ScanState.Failed("读屏连接超时", "详细信息") }
            else -> null
        }
        val run = when (name) {
            "run" -> RunProgress(running = true, idx = 3, total = 8, title = "关闭营销通知", sec = 142)
            "paused" -> RunProgress(running = true, idx = 5, total = 8, title = "系统广告", sec = 318, pause = true, paused = true)
            "pausing" -> RunProgress(running = true, idx = 5, total = 8, title = "系统广告", sec = 318, pause = true)
            "stalled" -> RunProgress(running = true, idx = 3, total = 8, title = "关闭各 App 里的广告开关", sec = 212, stalled = 95)
            "fgmode" -> RunProgress(running = true, idx = 2, total = 8, title = "存快照", sec = 12)
            "stopping" -> RunProgress(running = true, idx = 4, total = 8, title = "浏览器", sec = 201, cancel = true)
            "done", "failed", "failed2", "stopped" -> finished(name)
            else -> RunProgress()
        }
        val target: Screen = when (name) {
            "setup1" -> Screen.Setup("need_dev")
            "setup2" -> Screen.Setup("need_wifi")
            "setup3", "setup3mi" -> Screen.Setup("need_pair")
            "old", "stopped-sh", "ask", "denied", "nodev" -> Screen.Setup(name.removeSuffix("-sh"))
            "prepare0" -> Screen.Prepare(0)
            "prepare1" -> Screen.Prepare(1)
            "choose", "blocked", "norecipe", "scanfail" -> Screen.Choose
            "run", "paused", "pausing", "stalled", "fgmode", "stopping" -> Screen.Run
            "done", "failed", "failed2", "stopped" -> Screen.Done(run)
            else -> Screen.Home
        }
        val lines = (1..40).map { "[$it] 关闭 com.example.app$it 的营销渠道" }
        model.jump(backend, target, device, selection, run, lines)
        model.demoMode(if (name == "fgmode") RunMode.Foreground else RunMode.Background)
        model.notice = null
        model.sheet = null
        when (sheet) {
            "more", "newer" -> model.sheet = Sheet.More
            "restore" -> model.openRestore()
            "restored" -> {
                model.openRestore()
                model.restore("quickapp")
            }
            "feedback" -> model.sheet = Sheet.Feedback("bug", "版本 0.3.2\n手机 PKD110\n系统 16\n<details>\n```text\n日志\n```\n</details>")
            "report" -> model.sheet = Sheet.Report(JSONObject().put("version", "0.3.2").put("model", "PKD110").put("log", "第一行\n第二行").put("steps", JSONArray(listOf("关闭营销通知"))))
            "log" -> model.sheet = Sheet.Log
            "devoff" -> model.notice = Notice("关闭开发者模式？", "无线调试一起关掉。以后要还原改动，重新打开开发者模式和无线调试就行，不用再配对。", confirm = "关闭", dismiss = "取消")
        }
    }

    private fun finished(name: String): RunProgress {
        val ok = listOf(
            StepResult("保存快照", true, 4, "已保存", false, false),
            StepResult("系统广告", true, 86, "关了 12 个开关", false, false),
            StepResult("负一屏与搜索", true, 54, "关了 7 个开关", false, false),
            StepResult("关闭营销通知", true, 121, "关了 38 个渠道", false, false),
            StepResult("恢复插电常亮", true, 1, "插电常亮已改回 15", false, false),
        )
        return when (name) {
            "failed" -> RunProgress(sec = 266, outcome = Outcome.Failed, results = ok.take(2) + StepResult("负一屏与搜索", false, 30, "入口没找到", false, false))
            "failed2" -> RunProgress(sec = 266, outcome = Outcome.Failed, recovery = "读屏连接断开了。先检查读屏连接，再重新开始。", results = ok.take(1) + StepResult("系统广告", false, 3, "读屏连接断开", false, false))
            "stopped" -> RunProgress(sec = 100, cancel = true, outcome = Outcome.Stopped, results = ok.take(2) + StepResult("负一屏与搜索", false, 10, "", false, true))
            else -> RunProgress(sec = 266, outcome = Outcome.Ok, results = ok)
        }
    }

    private fun detection(): JSONObject = JSONObject()
        .put("name", device.title).put("model", device.model).put("warnings", JSONArray()).put("blocked", false)
        .put("steps", JSONArray(listOf("系统广告", "负一屏", "搜索", "应用商店", "浏览器", "主题", "视频", "游戏中心")))
        .put("ref", false)
        .put("recipe_label", "按机型脚本自动关")
        .put("recipe_note", "系统广告、负一屏、搜索、商店、浏览器、主题等 App 里的推荐和广告开关。「限制广告跟踪」这类保护开关会打开。")
        .put("manual_name", "").put("manual_url", "")
        .put("quickapps", JSONArray(listOf("快应用服务")))
        .put("quickapp_note", "广告常用 hap:// 链接跳进快应用。关闭后系统会拦截 hap:// 入口。确认负一屏快递卡片等常用服务不依赖它。可还原。")
        .put("quickapp_state", "")
        .put("ads", JSONArray(listOf(JSONObject().put("pkg", "com.opos.ads").put("name", "OPPO 广告服务"))))
        .put("ads_state", "")

    private fun selection(detection: JSONObject) = Selection(Detection.parse(detection)).apply {
        fun channel(app: String, pkg: String, name: String, checked: Boolean = true) =
            Channel(JSONObject().put("app", app).put("pkg", pkg).put("id", name).put("name", name).put("checked", checked))
        fill(
            listOf(
                channel("淘宝", "com.taobao.taobao", "优惠活动"), channel("淘宝", "com.taobao.taobao", "直播提醒", false),
                channel("淘宝", "com.taobao.taobao", "猜你喜欢"), channel("支付宝", "com.eg.android.AlipayGphone", "营销推广"),
                channel("京东", "com.jingdong.app.mall", "促销通知"), channel("京东", "com.jingdong.app.mall", "秒杀提醒"),
                channel("美团", "com.sankuai.meituan", "优惠券"), channel("小红书", "com.xingin.xhs", "推荐内容"),
                channel("哔哩哔哩", "tv.danmaku.bili", "推荐视频"), channel("", "com.example.noname", "活动通知"),
            ),
            emptyList(),
        )
    }

    private class DemoBackend(private val state: String, private val hasDevice: Boolean) : Backend {
        override suspend fun boot() = "0.3.2"
        override suspend fun shellState() = state
        override suspend fun call(method: String, vararg args: Any?): Any? = when (method) {
            "devices" -> JSONObject().put("list", JSONArray(if (hasDevice) listOf(JSONObject().put("serial", device.serial).put("name", device.title).put("model", device.model)) else emptyList()))
            "diagnostics" -> "版本 0.3.2\n手机 PKD110"
            "restore" -> "已恢复 2 个快应用组件。"
            "report_payload" -> JSONObject().put("steps", JSONArray()).put("log", "")
            "ui_check" -> JSONObject().put("message", "读屏连接正常。")
            else -> JSONObject()
        }
    }
}
