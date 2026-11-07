@file:OptIn(ExperimentalMaterial3ExpressiveApi::class)

package com.ahuamiao.adcleaner.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularWavyProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialShapes
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedListItem
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.WavyProgressIndicatorDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.min
import com.ahuamiao.adcleaner.R

// ---------- 正在准备 ---------- //

private val PrepareItems = listOf("检测手机型号和系统", "扫描营销通知")

@Composable
fun PrepareScreen(model: AppModel, at: Int) {
    val colors = MaterialTheme.colorScheme
    HeroPage(
        middle = { maxWidth, maxHeight ->
            val size = min(maxWidth * 0.5f, maxHeight - 88.dp)
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Hero(MaterialShapes.Circle, colors.primaryContainer, Modifier.size(size)) {
                    LoadingIndicator(Modifier.size(size * 0.72f), color = colors.onPrimaryContainer)
                }
                Spacer(Modifier.height(20.dp))
                Text("正在准备", style = MaterialTheme.typography.headlineMediumEmphasized)
            }
        },
        actions = {
        Segments {
            PrepareItems.forEachIndexed { i, label ->
                val done = i < at
                val current = i == at
                SegmentedListItem(
                    shapes = ListItemDefaults.segmentedShapes(i, PrepareItems.size),
                    leadingContent = {
                        val shape = if (done) MaterialShapes.Sunny else MaterialShapes.Circle
                        ShapeBadge(
                            shape,
                            if (done) colors.tertiary else colors.surfaceContainerHighest,
                            Modifier.size(32.dp),
                        ) {
                            when {
                                done -> CompositionLocalProvider(LocalContentColor provides colors.onTertiary) {
                                    Glyph(R.drawable.ic_check, Modifier.size(18.dp))
                                }
                                current -> LoadingIndicator(Modifier.size(28.dp))
                                else -> Text("${i + 1}", style = MaterialTheme.typography.labelLarge)
                            }
                        }
                    },
                ) {
                    Text(
                        label,
                        style = if (current) MaterialTheme.typography.titleMediumEmphasized else MaterialTheme.typography.titleMedium,
                    )
                }
            }
        }
        Box(
            Modifier
                .fillMaxWidth()
                .height(64.dp),
            contentAlignment = Alignment.Center,
        ) {
            TextButton(onClick = model::goHomeNow, shapes = ButtonDefaults.shapes()) { Text("取消") }
        }
        },
    )
}

// ---------- 执行 ---------- //

private val RunShapes by lazy {
    listOf(
        MaterialShapes.Cookie9Sided, MaterialShapes.Clover4Leaf, MaterialShapes.Cookie6Sided, MaterialShapes.Pentagon,
        MaterialShapes.Cookie7Sided, MaterialShapes.Gem, MaterialShapes.SoftBoom, MaterialShapes.Puffy,
        MaterialShapes.Cookie12Sided, MaterialShapes.Flower,
    )
}

private data class RunStatus(val text: String, val attention: Boolean)

private fun runStatus(run: RunProgress, mode: RunMode) = when {
    run.cancel -> RunStatus("正在停止", true)
    run.stalled > 0 -> RunStatus("已经 ${formatDuration(run.stalled)}没有进展，可能卡住了。可以停止后重新开始", true)
    run.paused -> RunStatus("已暂停，可以用手机", false)
    run.pause -> RunStatus("正在暂停，先别碰手机", true)
    mode == RunMode.Background -> RunStatus("在后台屏上进行，可以照常用手机", false)
    mode == RunMode.Foreground -> RunStatus("要借用当前屏幕，请不要碰手机", true)
    else -> RunStatus("正在开始", false)
}

@Composable
fun RunScreen(model: AppModel) {
    val run = model.progress
    val colors = MaterialTheme.colorScheme
    val haptic = LocalHapticFeedback.current
    val density = LocalDensity.current

    // 每进一步，中间的形状变一次、手上轻轻一下
    LaunchedEffect(run.idx) {
        if (run.idx > 1) haptic.performHapticFeedback(HapticFeedbackType.SegmentTick)
    }
    // 卡住时动画不能还在动，不然看着像有进展：波浪收平，形状转灰，手上震一下
    val still = run.pause || run.stalled > 0
    LaunchedEffect(run.stalled > 0) {
        if (run.stalled > 0) haptic.performHapticFeedback(HapticFeedbackType.Reject)
    }

    HeroPage(
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 4.dp),
                horizontalArrangement = Arrangement.End,
            ) {
                IconButton(onClick = { model.sheet = Sheet.Log }, shapes = IconButtonDefaults.shapes()) {
                    Glyph(R.drawable.ic_receipt_long, label = "详细记录")
                }
            }
        },
        middle = { maxWidth, maxHeight ->
            val ring = min(maxWidth * 0.82f, maxHeight - 152.dp)
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Box(contentAlignment = Alignment.Center) {
                    val stroke = with(density) { Stroke(width = 10.dp.toPx(), cap = StrokeCap.Round) }
                    val track = with(density) { Stroke(width = 10.dp.toPx(), cap = StrokeCap.Round) }
                    val target = if (run.total > 0) ((run.idx - if (run.running) 0.5f else 0f) / run.total).coerceIn(0f, 1f) else 0f
                    val progress by animateFloatAsState(target, WavyProgressIndicatorDefaults.ProgressAnimationSpec)
                    if (run.total > 0) {
                        CircularWavyProgressIndicator(
                            progress = { progress },
                            modifier = Modifier.size(ring),
                            stroke = stroke,
                            trackStroke = track,
                            amplitude = { if (still) 0f else WavyProgressIndicatorDefaults.indicatorAmplitude(it) },
                            wavelength = 44.dp,
                        )
                    } else {
                        CircularWavyProgressIndicator(
                            modifier = Modifier.size(ring),
                            stroke = stroke,
                            trackStroke = track,
                            wavelength = 44.dp,
                        )
                    }
                    val polygon = RunShapes[run.idx.coerceAtLeast(0) % RunShapes.size]
                    Hero(polygon, if (still) colors.surfaceContainerHighest else colors.primaryContainer, Modifier.size(ring * 0.72f), spin = !still) {
                        StepCounter(run)
                    }
                }
                Spacer(Modifier.height(16.dp))
                val slide = MaterialTheme.motionScheme.defaultSpatialSpec<IntOffset>()
                AnimatedContent(
                    targetState = run.title.ifEmpty { "准备中" },
                    transitionSpec = {
                        (slideInVertically(slide) { it / 2 } + fadeIn()) togetherWith
                            (slideOutVertically(slide) { -it / 2 } + fadeOut())
                    },
                    label = "step",
                ) { title ->
                    Text(
                        title,
                        style = MaterialTheme.typography.titleLargeEmphasized,
                        textAlign = TextAlign.Center,
                        maxLines = 2,
                        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    )
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    formatDuration(run.sec),
                    style = MaterialTheme.typography.bodyLarge.merge(TextStyle(fontFeatureSettings = TABULAR)),
                    color = colors.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                val status = runStatus(run, model.runMode)
                Surface(
                    shape = RoundedCornerShape(20.dp),
                    color = if (status.attention) colors.tertiaryContainer else colors.surfaceContainerHigh,
                    contentColor = if (status.attention) colors.onTertiaryContainer else colors.onSurfaceVariant,
                ) {
                    Text(
                        status.text,
                        style = MaterialTheme.typography.labelLarge,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    )
                }
            }
        },
        actions = {
        ActionPair(
            GroupAction(
                text = if (run.pause) "继续" else "暂停",
                icon = if (run.pause) R.drawable.ic_play_arrow else R.drawable.ic_pause,
                enabled = run.running && !run.cancel,
                onClick = { model.togglePause() },
            ),
            GroupAction("停止", R.drawable.ic_stop, enabled = !run.cancel, outlined = true, onClick = { model.stopRun() }),
        )
        Spacer(Modifier.height(16.dp))
        },
    )
}

@Composable
private fun StepCounter(run: RunProgress) {
    val big = MaterialTheme.typography.displayLargeEmphasized.merge(TextStyle(fontFeatureSettings = TABULAR))
    val small = MaterialTheme.typography.titleLarge
    if (run.total == 0) return
    Text(
        buildAnnotatedString {
            append("${run.idx}")
            withStyle(SpanStyle(fontSize = small.fontSize, fontWeight = small.fontWeight)) { append(" / ${run.total}") }
        },
        style = big,
    )
}

// ---------- 完成 ---------- //

private data class DoneCopy(val title: String, val note: String)

private fun doneCopy(run: RunProgress) = when (run.outcome) {
    Outcome.Ok -> DoneCopy("完成", "去负一屏、应用商店、浏览器看一眼，确认功能正常。")
    Outcome.Failed -> DoneCopy("有步骤没成功", "成功的改动已经生效，可以重新开始。")
    Outcome.Stopped -> DoneCopy("已停止", "已经关掉的不会变回去，可以重新开始。")
}

@Composable
fun DoneScreen(model: AppModel, run: RunProgress) {
    val colors = MaterialTheme.colorScheme
    val haptic = LocalHapticFeedback.current
    val copy = doneCopy(run)
    val pop = remember { Animatable(0.3f) }
    val popSpec = MaterialTheme.motionScheme.slowSpatialSpec<Float>()
    LaunchedEffect(Unit) {
        haptic.performHapticFeedback(
            if (run.outcome == Outcome.Failed) HapticFeedbackType.Reject else HapticFeedbackType.Confirm,
        )
        pop.animateTo(1f, popSpec)
    }
    val polygon = when (run.outcome) {
        Outcome.Ok -> MaterialShapes.Sunny
        Outcome.Failed -> MaterialShapes.SoftBurst
        Outcome.Stopped -> MaterialShapes.Square
    }
    val fill = when (run.outcome) {
        Outcome.Ok -> colors.primary
        Outcome.Failed -> colors.errorContainer
        Outcome.Stopped -> colors.surfaceContainerHighest
    }
    val tint = when (run.outcome) {
        Outcome.Ok -> colors.onPrimary
        Outcome.Failed -> colors.onErrorContainer
        Outcome.Stopped -> colors.onSurfaceVariant
    }
    val icon = when (run.outcome) {
        Outcome.Ok -> R.drawable.ic_check
        Outcome.Failed -> R.drawable.ic_priority_high
        Outcome.Stopped -> R.drawable.ic_stop
    }

    Page {
        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            contentPadding = PaddingValues(top = 24.dp, bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(ListItemDefaults.SegmentedGap),
        ) {
            item {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Hero(polygon, fill, Modifier.size(144.dp), spin = false) {
                        CompositionLocalProvider(LocalContentColor provides tint) {
                            Glyph(
                                icon,
                                Modifier
                                    .size(64.dp)
                                    .graphicsLayer {
                                        scaleX = pop.value
                                        scaleY = pop.value
                                    },
                            )
                        }
                    }
                    Spacer(Modifier.height(20.dp))
                    Text(copy.title, style = MaterialTheme.typography.displaySmallEmphasized)
                    Spacer(Modifier.height(8.dp))
                    if (run.sec > 0) {
                        Text(
                            "用时 ${formatDuration(run.sec)}",
                            style = MaterialTheme.typography.titleMedium.merge(TextStyle(fontFeatureSettings = TABULAR)),
                        )
                        Spacer(Modifier.height(4.dp))
                    }
                    if (run.results.isNotEmpty()) {
                        Text(
                            copy.note,
                            style = MaterialTheme.typography.bodyMedium,
                            color = colors.onSurfaceVariant,
                            textAlign = TextAlign.Center,
                        )
                    }
                    // 没做成的步由后台判定，界面只按 N 出按钮（#638）
                    if (run.retry > 0) {
                        Spacer(Modifier.height(20.dp))
                        SizedButton(
                            "重试没成功的步骤（${run.retry}）",
                            model::retry,
                            icon = R.drawable.ic_restart_alt,
                        )
                    }
                }
            }
            itemsIndexed(run.results) { i, r -> ResultRow(i, run.results.size, r) }
            if (run.recovery.isNotEmpty()) {
                item {
                    Spacer(Modifier.height(16.dp))
                    SectionTitle("排查读屏连接")
                    Segments {
                        SegmentedListItem(
                            onClick = model::checkUi,
                            shapes = ListItemDefaults.segmentedShapes(0, 2),
                            supportingContent = { Text(run.recovery) },
                        ) { Text("检查读屏连接") }
                        SegmentedListItem(
                            onClick = model::copyDiagnostics,
                            shapes = ListItemDefaults.segmentedShapes(1, 2),
                            trailingContent = { Glyph(R.drawable.ic_content_copy) },
                        ) { Text("复制完整诊断") }
                    }
                }
            }
            item {
                Spacer(Modifier.height(16.dp))
                SectionTitle("接下来")
                val failed = run.outcome == Outcome.Failed
                val rows = if (failed) 4 else 2
                Segments {
                    SegmentedListItem(
                        onClick = {
                            model.notice = Notice(
                                "关闭开发者模式？",
                                "无线调试一起关掉。以后要还原改动，重新打开开发者模式和无线调试就行，不用再配对。",
                                confirm = "关闭",
                                onConfirm = model::devOff,
                                dismiss = "取消",
                            )
                        },
                        shapes = ListItemDefaults.segmentedShapes(0, rows),
                        leadingContent = { Glyph(R.drawable.ic_developer_mode) },
                        supportingContent = {
                            Text(
                                if (failed) "还要排查或重试就先留着。部分银行、支付、游戏 App 检测到它开着会提醒或拒绝运行。"
                                else "部分银行、支付、游戏 App 检测到它开着会提醒或拒绝运行。关掉不会撤销改动。",
                            )
                        },
                    ) { Text("关闭开发者模式") }
                    if (failed) {
                        SegmentedListItem(
                            onClick = model::openReport,
                            shapes = ListItemDefaults.segmentedShapes(1, rows),
                            leadingContent = { Glyph(R.drawable.ic_upload) },
                            supportingContent = { Text("不需要账号，发送前可以看到全部内容") },
                        ) { Text("上报错误日志") }
                        SegmentedListItem(
                            onClick = { model.openFeedback("bug") },
                            shapes = ListItemDefaults.segmentedShapes(2, rows),
                            leadingContent = { Glyph(R.drawable.ic_bug_report) },
                        ) { Text("到 GitHub 反馈") }
                    }
                    SegmentedListItem(
                        onClick = { model.sheet = Sheet.Log },
                        shapes = ListItemDefaults.segmentedShapes(rows - 1, rows),
                        leadingContent = { Glyph(R.drawable.ic_receipt_long) },
                    ) { Text("查看完整日志") }
                }
            }
        }
        val height = ctaHeight()
        if (run.outcome == Outcome.Ok) {
            SizedButton("完成", model::goHomeNow, Modifier.fillMaxWidth(), height = height)
            TextButton(
                onClick = model::oneTap,
                shapes = ButtonDefaults.shapes(),
                modifier = Modifier.align(Alignment.CenterHorizontally),
            ) { Text("再做一次") }
        } else {
            SizedButton("重新开始", model::oneTap, Modifier.fillMaxWidth(), height = height, icon = R.drawable.ic_restart_alt)
            TextButton(
                onClick = model::goHomeNow,
                shapes = ButtonDefaults.shapes(),
                modifier = Modifier.align(Alignment.CenterHorizontally),
            ) { Text("回到首页") }
        }
    }
}

@Composable
private fun ResultRow(index: Int, count: Int, r: StepResult) {
    val colors = MaterialTheme.colorScheme
    val fill = when {
        r.skipped || r.stopped -> colors.surfaceContainerHighest
        r.ok -> colors.tertiaryContainer
        else -> colors.errorContainer
    }
    val tint = when {
        r.skipped || r.stopped -> colors.onSurfaceVariant
        r.ok -> colors.onTertiaryContainer
        else -> colors.onErrorContainer
    }
    val icon = when {
        r.skipped -> R.drawable.ic_close
        r.stopped -> R.drawable.ic_stop
        r.ok -> R.drawable.ic_check
        else -> R.drawable.ic_priority_high
    }
    val state = when {
        r.skipped -> "跳过"
        r.stopped -> "已停止"
        r.ok -> ""
        else -> "失败"
    }
    SegmentedListItem(
        shapes = ListItemDefaults.segmentedShapes(index, count),
        leadingContent = {
            ShapeBadge(if (r.ok) MaterialShapes.Cookie6Sided else MaterialShapes.Circle, fill, Modifier.size(36.dp)) {
                CompositionLocalProvider(LocalContentColor provides tint) {
                    Glyph(icon, Modifier.size(20.dp))
                }
            }
        },
        supportingContent = {
            val parts = listOf(state, r.summary, "${r.sec} 秒").filter { it.isNotEmpty() }
            Text(parts.joinToString(" · "), maxLines = 3)
        },
    ) {
        Text(r.title)
    }
}
