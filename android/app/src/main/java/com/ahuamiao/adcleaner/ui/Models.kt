package com.ahuamiao.adcleaner.ui

import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import org.json.JSONArray
import org.json.JSONObject
import java.text.Collator
import java.util.Locale

/** JSON 里的 null 取出来是空字符串，不是 "null"。 */
internal fun JSONObject.text(key: String): String = if (isNull(key)) "" else optString(key)

internal fun JSONArray?.objects(): List<JSONObject> =
    if (this == null) emptyList() else List(length()) { getJSONObject(it) }

internal fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList() else List(length()) { getString(it) }

/** 切到系统设置时通知栏里那条指引。 */
data class SetupNote(val title: String, val text: String)

/** 首次设置的一步；文案来自 view.py 的 setup_guide（#646）。key 决定按哪个按钮走哪个系统动作。 */
data class SetupStep(
    val key: String,
    val title: String,
    val lines: List<String>,
    val note: String,
    val action: String,
    val notice: SetupNote?,
)

data class SetupGuide(
    val steps: List<SetupStep> = emptyList(),
    /** 授权状态（need_dev / need_wifi / need_pair）到这个状态是第几步。 */
    val at: Map<String, Int> = emptyMap(),
) {
    companion object {
        fun parse(o: JSONObject) = SetupGuide(
            steps = o.optJSONArray("steps").objects().map { s ->
                SetupStep(
                    key = s.text("key"),
                    title = s.text("title"),
                    lines = s.optJSONArray("lines").strings(),
                    note = s.text("note"),
                    action = s.text("action"),
                    notice = s.optJSONObject("notice")?.let { SetupNote(it.text("title"), it.text("text")) },
                )
            },
            at = buildMap { o.optJSONObject("at")?.let { a -> a.keys().forEach { put(it, a.optInt(it)) } } },
        )
    }
}

data class Device(val serial: String, val title: String, val model: String) {
    companion object {
        fun parse(o: JSONObject) = Device(
            serial = o.text("serial"),
            title = o.text("name").ifEmpty { "${o.text("brand")} ${o.text("model")}".trim() }.ifEmpty { o.text("serial") },
            model = o.text("model"),
        )
    }
}

data class StepResult(
    val title: String,
    val ok: Boolean,
    val sec: Int,
    val summary: String,
    val skipped: Boolean,
    val stopped: Boolean,
) {
    companion object {
        fun parse(o: JSONObject) = StepResult(
            title = o.text("title"),
            ok = o.optInt("rc", -1) == 0,
            sec = o.optInt("sec"),
            summary = o.text("summary"),
            skipped = o.optBoolean("skipped"),
            stopped = o.optBoolean("stopped"),
        )
    }
}

enum class Outcome { Ok, Failed, Stopped }

data class RunProgress(
    val running: Boolean = false,
    val next: Int = 0,
    val idx: Int = 0,
    val total: Int = 0,
    val title: String = "",
    val sec: Int = 0,
    val cancel: Boolean = false,
    val pause: Boolean = false,
    val paused: Boolean = false,
    val recovery: String = "",
    val results: List<StepResult> = emptyList(),
    val outcome: Outcome = Outcome.Ok,
    val lines: List<String> = emptyList(),
    /** 已经多少秒没有进展；0 表示正常（判断在 view.py 的 StallWatch）。 */
    val stalled: Int = 0,
    /** 还能重试几步；0 表示结果页不出重试按钮（判断在 gui/app.py 的 retryable，#638）。 */
    val retry: Int = 0,
) {
    /** 执行结束了吗。停在第一步时还没有结果，也算结束（#632）。 */
    val finished get() = !running && (results.isNotEmpty() || cancel)

    companion object {
        fun parse(o: JSONObject) = RunProgress(
            running = o.optBoolean("running"),
            next = o.optInt("next"),
            idx = o.optInt("idx"),
            total = o.optInt("total"),
            title = o.text("title"),
            sec = o.optInt("sec"),
            cancel = o.optBoolean("cancel"),
            pause = o.optBoolean("pause"),
            paused = o.optBoolean("paused"),
            recovery = o.text("recovery"),
            results = o.optJSONArray("results").objects().map(StepResult::parse),
            outcome = when (o.optString("outcome")) {
                "failed" -> Outcome.Failed
                "stopped" -> Outcome.Stopped
                else -> Outcome.Ok
            },
            lines = o.optJSONArray("lines").strings(),
            stalled = o.optInt("stalled"),
            retry = o.optInt("retry"),
        )
    }
}

data class AdItem(val pkg: String, val name: String)

data class Detection(
    val name: String,
    val model: String,
    val warnings: List<String>,
    val blocked: Boolean,
    val steps: List<String>,
    val ref: Boolean,
    val recipeLabel: String,
    val recipeNote: String,
    val manualName: String,
    val manualUrl: String,
    val quickapps: List<String>,
    val quickappNote: String,
    val quickappState: String,
    val ads: List<AdItem>,
    val adsState: String,
) {
    companion object {
        fun parse(o: JSONObject) = Detection(
            name = o.text("name"),
            model = o.text("model"),
            warnings = o.optJSONArray("warnings").strings(),
            blocked = o.optBoolean("blocked"),
            steps = o.optJSONArray("steps").strings(),
            ref = o.optBoolean("ref"),
            recipeLabel = o.text("recipe_label"),
            recipeNote = o.text("recipe_note"),
            manualName = o.text("manual_name"),
            manualUrl = o.text("manual_url"),
            quickapps = o.optJSONArray("quickapps").strings(),
            quickappNote = o.text("quickapp_note"),
            quickappState = o.text("quickapp_state"),
            ads = o.optJSONArray("ads").objects().map { AdItem(it.optString("pkg"), it.optString("name")) },
            adsState = o.text("ads_state"),
        )
    }
}

class Channel(val raw: JSONObject) {
    val app: String = raw.text("app")
    val pkg: String = raw.text("pkg")
    val name: String = raw.text("name")
    var checked by mutableStateOf(raw.optBoolean("checked"))

    fun plan(): JSONObject = JSONObject(raw.toString()).put("checked", true)
}

class ChannelGroup(val label: String, val channels: List<Channel>) {
    val selected: Int by derivedStateOf { channels.count { it.checked } }
}

sealed interface ScanState {
    data object Loading : ScanState
    data class Failed(val message: String, val detail: String) : ScanState
    data class Ready(val notes: List<String>) : ScanState
}

/** 确认页的勾选。默认值和桌面版一致：参考脚本不勾，快应用、广告组件不勾。 */
class Selection(val detection: Detection) {
    var recipe by mutableStateOf(detection.steps.isNotEmpty() && !detection.ref)
        private set
    val steps = mutableStateMapOf<String, Boolean>().apply { detection.steps.forEach { put(it, !detection.ref) } }
    var quickapp by mutableStateOf(false)
    val ads = mutableStateMapOf<String, Boolean>()
    var scan by mutableStateOf<ScanState>(ScanState.Loading)
    val groups = mutableStateListOf<ChannelGroup>()

    val channelCount: Int by derivedStateOf { groups.sumOf { it.channels.size } }
    val channelSelected: Int by derivedStateOf { groups.sumOf { it.selected } }
    private val stepsSelected: Int by derivedStateOf { if (recipe) steps.values.count { it } else 0 }
    val count: Int by derivedStateOf {
        stepsSelected + channelSelected + (if (quickapp) 1 else 0) + ads.values.count { it }
    }

    fun chooseRecipe(on: Boolean) {
        recipe = on
        detection.steps.forEach { steps[it] = on }
    }

    fun setStep(step: String, on: Boolean) {
        steps[step] = on
        recipe = steps.values.any { it }
    }

    fun setAllChannels(on: Boolean) = groups.forEach { g -> g.channels.forEach { it.checked = on } }

    /** 同一个软件的渠道排在一起；读不到软件名的按包名排在后面。 */
    fun fill(channels: List<Channel>, notes: List<String>) {
        val zh = Collator.getInstance(Locale.CHINA)
        groups.clear()
        channels.groupBy { it.app.ifEmpty { it.pkg } }.entries
            .sortedWith(compareBy<Map.Entry<String, List<Channel>>> { it.value.first().app.isEmpty() }
                .thenComparator { a, b -> zh.compare(a.key, b.key) })
            .forEach { (label, list) -> groups += ChannelGroup(label, list.sortedWith { a, b -> zh.compare(a.name, b.name) }) }
        scan = ScanState.Ready(notes)
    }

    fun plan(): JSONObject = JSONObject()
        .put("backup", true)
        .put("model", detection.model)
        .put("steps", JSONArray(if (recipe) detection.steps.filter { steps[it] == true } else emptyList<String>()))
        .put("ref", detection.ref)
        .put("channels", JSONArray(groups.flatMap { it.channels }.filter { it.checked }.map { it.plan() }))
        .put("quickapp", quickapp)
        .put("ads", JSONArray(detection.ads.filter { ads[it.pkg] == true }.map { it.pkg }))
}
