package com.ahuamiao.adcleaner.ui

import com.ahuamiao.adcleaner.Native
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * 现在在哪一页。页面流程只有这一个状态，每次切换都经过 [AppModel] 的方法（ADR-0017）。
 *
 * ```
 * Boot → Setup ⇄ Home → Prepare → Run → Done → Home
 *                  ↓       ↓       ↑
 *                Choose ←──┘───────┘
 * ```
 */
sealed interface Screen {
    data object Boot : Screen
    data class Failed(val reason: String) : Screen
    /** need_dev / need_wifi / need_pair 是首次设置三步；old / stopped / ask / denied 走 Shizuku；nodev 是已授权却读不到手机。 */
    data class Setup(val state: String) : Screen
    data object Home : Screen
    /** 一键的准备页，at 是做到第几件。 */
    data class Prepare(val at: Int) : Screen
    data object Choose : Screen
    data object Run : Screen
    data class Done(val run: RunProgress) : Screen
}

sealed interface Sheet {
    data object More : Sheet
    data object Restore : Sheet
    data class Feedback(val kind: String, val diag: String) : Sheet
    data class Report(val payload: JSONObject) : Sheet
    data object Log : Sheet
}

data class Notice(
    val title: String,
    val text: String = "",
    val detail: String = "",
    val confirm: String = "好",
    val onConfirm: (() -> Unit)? = null,
    val dismiss: String? = null,
)

enum class RunMode { Deciding, Background, Foreground }

data class BrandGuide(val tap: String = "「关于手机」里的「版本号」", val xiaomi: Boolean = false)

data class NewVersion(val version: String, val url: String)

/** 进程级：Activity 被系统回收、从通知点回来，都接着这一份。 */
class AppModel(backend: Backend, private val scope: CoroutineScope, private val brand: String) {
    private var backend by mutableStateOf(backend)

    var screen by mutableStateOf<Screen>(Screen.Boot)
        private set
    var sheet by mutableStateOf<Sheet?>(null)
    var notice by mutableStateOf<Notice?>(null)

    var version by mutableStateOf("")
        private set
    var newVersion by mutableStateOf<NewVersion?>(null)
        private set
    var guide by mutableStateOf(BrandGuide())
        private set
    var device by mutableStateOf<Device?>(null)
        private set

    var selection by mutableStateOf<Selection?>(null)
        private set
    var detecting by mutableStateOf(false)
        private set

    var progress by mutableStateOf(RunProgress())
        private set
    var runMode by mutableStateOf(RunMode.Deciding)
        private set
    val log = mutableStateListOf<String>()

    /** 还原进行中 / 刚还原完的结果，显示在还原面板里。 */
    var restoring by mutableStateOf(false)
        private set
    var restoreResult by mutableStateOf("")
        private set

    /** Activity 看得见时半秒问一次进度，看不见时放慢。 */
    var visible = true

    private var booted = false
    private var stallNoticed = false
    private var flow: Job? = null
    private var refreshing = false
    private var refreshAgain = false

    /** 换一条页面流程：上一条没做完的就此作废，它的结果不会再改页面。 */
    private fun flow(block: suspend CoroutineScope.() -> Unit) {
        flow?.cancel()
        flow = scope.launch(block = block)
    }

    fun start() {
        if (booted) return refresh()
        booted = true
        flow {
            try {
                version = backend.boot()
            } catch (e: EngineError) {
                screen = Screen.Failed(e.message.orEmpty())
                return@flow
            }
            launch { loadExtras() }
            // 执行期间界面可能被系统回收：重新打开时后台的执行还在跑，接回执行页
            val run = runCatching { poll(0) }.getOrNull()
            if (run != null && run.running) follow() else refresh()
        }
    }

    private suspend fun loadExtras() {
        runCatching {
            val o = backend.call("view.brand_guide", brand) as JSONObject
            guide = BrandGuide(o.optString("tap"), o.optBoolean("xiaomi"))
        }
        runCatching {
            val o = backend.call("latest_version") as? JSONObject ?: return@runCatching
            val v = o.optString("version")
            if (v.isNotEmpty()) newVersion = NewVersion(v, o.optString("url"))
        }
    }

    /** 重新查一次授权状态。只有授权相关的页面才跟着变；查询要等几秒，同时只跑一个，期间再来的合并成下一次。 */
    fun refresh() {
        if (!booted || !watchesShell()) return
        if (refreshing) {
            refreshAgain = true
            return
        }
        refreshing = true
        scope.launch {
            try {
                do {
                    refreshAgain = false
                    refreshOnce()
                } while (refreshAgain)
            } finally {
                refreshing = false
            }
        }
    }

    private fun watchesShell() = screen.let { it is Screen.Boot || it is Screen.Setup || it is Screen.Home }

    private suspend fun refreshOnce() {
        val state = backend.shellState()
        if (!watchesShell()) return
        if (state != "ready") {
            screen = Screen.Setup(state)
            return
        }
        val dev = runCatching { (backend.call("devices") as JSONObject).optJSONArray("list").objects().firstOrNull() }.getOrNull()
        if (!watchesShell()) return
        if (dev == null) {
            screen = Screen.Setup("nodev")
            return
        }
        device = Device.parse(dev)
        // 引擎在跑（比如进程没死、界面被回收过）：回执行页，不能让用户在首页再点一次开始
        if (runCatching { poll(0).running }.getOrDefault(false)) {
            flow { follow() }
            return
        }
        screen = Screen.Home
    }

    /** 一键：把检测、扫描、开始连起来。中途要用户处理（锁屏、展开的折叠屏、没有可关的项目）就落到「自己选」页。 */
    fun oneTap() = flow {
        val serial = device?.serial ?: return@flow
        screen = Screen.Prepare(0)
        val selection = detect(serial) ?: return@flow goHome()
        if (selection.detection.blocked) {
            screen = Screen.Choose
            scan(serial, selection)
            return@flow
        }
        screen = Screen.Prepare(1)
        scan(serial, selection)
        if (selection.scan is ScanState.Failed || selection.count == 0) {
            screen = Screen.Choose
            return@flow
        }
        screen = Screen.Prepare(2)
        begin(serial, selection.plan())
    }

    fun openChoose() = flow {
        val serial = device?.serial ?: return@flow
        selection = null
        screen = Screen.Choose
        val selection = detect(serial) ?: return@flow goHome()
        scan(serial, selection)      // 只读；被挡住（锁屏、展开的折叠屏）也先列出来，处理完直接能开始
    }

    fun redetect() = openChoose()

    fun rescan() = flow {
        val serial = device?.serial ?: return@flow
        val selection = selection ?: return@flow
        scan(serial, selection)
    }

    private suspend fun detect(serial: String): Selection? {
        detecting = true
        try {
            val o = try {
                backend.call("view.detect", serial) as JSONObject
            } catch (e: EngineError) {
                notice = Notice("检测失败", e.message.orEmpty())
                return null
            }
            if (o.has("error")) {
                notice = Notice("检测失败", o.optString("error"))
                return null
            }
            return Selection(Detection.parse(o)).also { selection = it }
        } finally {
            detecting = false
        }
    }

    private suspend fun scan(serial: String, selection: Selection) {
        selection.scan = ScanState.Loading
        try {
            val o = backend.call("chan_scan", serial) as JSONObject
            if (o.has("error")) {
                selection.scan = ScanState.Failed(o.optString("error"), o.optString("detail").ifEmpty { o.optString("error") })
            } else {
                selection.fill(o.optJSONArray("chans").objects().map(::Channel), o.optJSONArray("notes").strings())
            }
        } catch (e: EngineError) {
            selection.scan = ScanState.Failed(e.message.orEmpty(), e.message.orEmpty())
        }
    }

    fun startChosen() = flow {
        val serial = device?.serial ?: return@flow
        val selection = selection ?: return@flow
        if (selection.count == 0) {
            notice = Notice("还没选任何一项", "选好要关的项目再开始。都不用关的话，可以去完成页关闭开发者模式。",
                confirm = "去完成页", onConfirm = { screen = Screen.Done(RunProgress()) }, dismiss = "返回")
            return@flow
        }
        begin(serial, selection.plan())
    }

    /** 交给引擎。发出去就不能取消了，不然引擎在跑、界面却回了首页。 */
    private suspend fun begin(serial: String, plan: JSONObject) {
        val result = withContext(NonCancellable) {
            runCatching { backend.call("start", serial, plan) as JSONObject }
        }
        val error = result.fold({ if (it.has("error")) it.optString("error") else null }, { it.message.orEmpty() })
        if (error != null) {
            // 已经有一轮在跑：跟上它，别把用户留在选择页上以为没开始
            if (runCatching { poll(0).running }.getOrDefault(false)) return follow()
            notice = Notice("没法开始", error)
            if (selection == null) goHome() else screen = Screen.Choose
            return
        }
        follow()
    }

    private suspend fun poll(since: Int) = RunProgress.parse(backend.call("view.poll", since) as JSONObject)

    /** 执行页：跟到执行结束。同一时刻只有这一个循环，上一次回来才发下一次。 */
    private suspend fun follow() = coroutineScope {
        log.clear()
        progress = RunProgress(running = true)
        runMode = RunMode.Deciding
        screen = Screen.Run
        val mode = launch { watchMode() }
        var next = 0
        var idle = 0
        while (isActive) {
            val run = try {
                poll(next)
            } catch (_: EngineError) {
                delay(1000)
                continue
            }
            next = run.next
            log.addAll(run.lines)
            progress = run
            noticeStall(run)
            if (run.finished) {
                mode.cancel()
                screen = Screen.Done(run)
                return@coroutineScope
            }
            // 没在跑、又没有结果：这次执行根本没起来（比如进程重启过），别一直停在执行页
            idle = if (run.running) 0 else idle + 1
            if (idle > 30) {
                mode.cancel()
                goHomeNow()
                return@coroutineScope
            }
            delay(if (visible) 500 else 2000)
        }
    }

    /** 卡住时用户多半在用别的 App：通知栏说一声；有进展了就收回。 */
    private fun noticeStall(run: RunProgress) {
        val stalled = run.stalled > 0
        if (stalled == stallNoticed) return
        stallNoticed = stalled
        if (!stalled) Native.stallNotice(false) else if (!visible) Native.stallNotice(true)
    }

    /** 建后台屏要一两秒才有结论：建好了说「照常用手机」，建不了才说「别碰」。 */
    private suspend fun watchMode() {
        val until = System.currentTimeMillis() + 15000
        var settled = 0
        while (true) {
            val m = runCatching { backend.call("run_mode") as JSONObject }.getOrNull()
            if (m != null) {
                if (m.optBoolean("background")) {
                    runMode = RunMode.Background
                    return
                }
                if (!(m.optBoolean("deciding") && System.currentTimeMillis() < until) && ++settled >= 8) {
                    runMode = RunMode.Foreground
                    return
                }
            }
            delay(500)
        }
    }

    fun togglePause() = scope.launch {
        runCatching { backend.call(if (progress.pause) "resume" else "pause") }
    }

    fun stopRun() = scope.launch { runCatching { backend.call("stop") } }

    fun goHomeNow() = flow { goHome() }

    private suspend fun goHome() {
        selection = null
        screen = if (device != null) Screen.Home else Screen.Boot
        refreshOnceSafely()
    }

    private suspend fun refreshOnceSafely() {
        runCatching { refreshOnce() }
    }

    /** 系统返回。返回 false 表示这一页不接管（交给系统退到桌面）。 */
    fun back(): Boolean {
        if (!canGoBack()) return false
        goHomeNow()
        return true
    }

    /** 准备页的最后一件是把计划交给引擎，那一步发出去就收不回来了。 */
    fun canGoBack() = screen.let { it is Screen.Choose || it is Screen.Done || (it is Screen.Prepare && it.at < 2) }

    // ---------- 还原 ---------- //

    fun openRestore() {
        restoreResult = ""
        sheet = Sheet.Restore
    }

    fun restore(what: String) {
        val serial = device?.serial
        if (serial == null) {
            restoreResult = "还没连上这台手机，先完成首页的设置。"
            return
        }
        if (restoring) return
        restoring = true
        restoreResult = ""
        scope.launch {
            restoreResult = try {
                backend.call("restore", serial, what)?.toString().orEmpty().trim().ifEmpty { "已处理。" }
            } catch (e: EngineError) {
                e.message.orEmpty()
            }
            restoring = false
        }
    }

    // ---------- 收尾 ---------- //

    fun devOff() {
        val serial = device?.serial ?: return
        scope.launch {
            runCatching { backend.call("dev_off", serial) }
            notice = Notice("已关闭", "打开 设置，搜索「开发者选项」，确认总开关是关着的。")
        }
    }

    fun checkUi() {
        val serial = device?.serial ?: return
        scope.launch {
            notice = try {
                val o = backend.call("ui_check", serial) as JSONObject
                if (o.has("error")) {
                    Notice("读屏连接未就绪", o.optString("error"), detail = o.optString("detail"),
                        confirm = "复制诊断", onConfirm = ::copyDiagnostics, dismiss = "关闭")
                } else {
                    Notice("读屏连接正常", o.optString("message"))
                }
            } catch (e: EngineError) {
                Notice("检查未完成", e.message.orEmpty())
            }
        }
    }

    fun copyDiagnostics() {
        scope.launch {
            runCatching {
                backend.call("copy_text", backend.call("diagnostics")?.toString().orEmpty())
            }.onFailure { notice = Notice("复制失败", it.message.orEmpty()) }
        }
    }

    // ---------- 反馈 ---------- //

    fun openFeedback(kind: String = "bug") {
        scope.launch {
            val diag = runCatching { backend.call("diagnostics")?.toString().orEmpty() }.getOrDefault("")
            sheet = Sheet.Feedback(kind, diag)
        }
    }

    /** 回调告诉面板这次有没有把诊断截短。 */
    fun sendFeedback(kind: String, text: String, diag: String, done: (Boolean) -> Unit) {
        scope.launch {
            val trimmed = runCatching {
                (backend.call("view.send_feedback", kind, text, diag) as JSONObject).optBoolean("trimmed")
            }.getOrDefault(false)
            done(trimmed)
        }
    }

    fun openReport() {
        scope.launch {
            val payload = try {
                backend.call("report_payload") as JSONObject
            } catch (e: EngineError) {
                notice = Notice("上报错误日志", e.message.orEmpty())
                return@launch
            }
            val empty = (payload.optJSONArray("steps")?.length() ?: 0) == 0 && payload.optString("log").isBlank()
            if (empty) {        // 没执行过：只有手机型号，看不出问题（10-28 六份空报告）
                sheet = null
                notice = Notice("还没有执行记录", "这份报告只有手机型号，看不出问题。先执行一次再上报；还没执行就遇到问题，到 GitHub 反馈。",
                    confirm = "到 GitHub 反馈", onConfirm = { openFeedback() }, dismiss = "关闭")
            } else {
                sheet = Sheet.Report(payload)
            }
        }
    }

    /** 回调给面板：发送结果的文字、是否成功。 */
    fun sendReport(payload: JSONObject, done: (String, Boolean) -> Unit) {
        scope.launch {
            try {
                val r = backend.call("send_report", payload) as JSONObject
                when {
                    r.has("error") -> done(r.optString("error"), false)
                    r.optBoolean("duplicate") -> done("这份日志一小时内上报过，不用重复发送。", true)
                    else -> done("上报成功。报告编号 ${r.opt("id")}；要删除这份记录，到 GitHub 提 Issue 附上编号。", true)
                }
            } catch (e: EngineError) {
                done(e.message.orEmpty(), false)
            }
        }
    }

    fun openUrl(url: String) {
        scope.launch { runCatching { backend.call("open_url", url) } }
    }

    /** debug 构建的演示：换后台、跳到指定页（src/debug/.../Demo.kt）。release 没有调用方。 */
    internal fun jump(demo: Backend, target: Screen, device: Device?, selection: Selection?, run: RunProgress?, lines: List<String>) {
        flow?.cancel()
        backend = demo
        booted = true
        this.device = device
        this.selection = selection
        run?.let { progress = it }
        log.clear()
        log.addAll(lines)
        screen = target
    }

    /** debug 构建的真引擎验收：不经勾选，直接把计划交给引擎（模拟器上没有营销渠道可选）。 */
    internal fun debugStart(plan: JSONObject) = flow {
        val serial = device?.serial ?: return@flow
        begin(serial, plan)
    }

    internal fun demoMode(mode: RunMode) {
        runMode = mode
    }

    internal fun demoGuide(guide: BrandGuide) {
        this.guide = guide
    }

    internal fun demoVersion(version: String, newer: NewVersion?) {
        this.version = version
        newVersion = newer
    }
}
