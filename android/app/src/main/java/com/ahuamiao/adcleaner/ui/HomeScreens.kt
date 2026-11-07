@file:OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalMaterial3Api::class)

package com.ahuamiao.adcleaner.ui

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ContainedLoadingIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LargeFlexibleTopAppBar
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialShapes
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedListItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.min
import com.ahuamiao.adcleaner.R

@Composable
fun BootScreen() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        ContainedLoadingIndicator(Modifier.size(72.dp))
    }
}

@Composable
fun FailedScreen(reason: String) {
    Page {
        Spacer(Modifier.weight(1f))
        Text("启动失败", style = MaterialTheme.typography.headlineMediumEmphasized)
        Spacer(Modifier.height(12.dp))
        SelectionContainer {
            Text(
                reason,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.verticalScroll(rememberScrollState()),
            )
        }
        Spacer(Modifier.weight(1f))
    }
}

private val HomeShapes by lazy {
    listOf(
        MaterialShapes.Cookie12Sided, MaterialShapes.Sunny, MaterialShapes.Clover8Leaf,
        MaterialShapes.Flower, MaterialShapes.SoftBurst, MaterialShapes.Cookie9Sided,
    )
}

@Composable
fun HomeScreen(model: AppModel) {
    val haptic = LocalHapticFeedback.current
    val colors = MaterialTheme.colorScheme
    val press = remember { MutableInteractionSource() }
    val pressed by press.collectIsPressedAsState()
    var shapeAt by rememberSaveable { mutableIntStateOf(0) }
    val device = model.device

    HeroPage(
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Image(
                    painterResource(R.mipmap.ic_launcher_art),
                    contentDescription = null,
                    modifier = Modifier
                        .padding(start = 4.dp)
                        .size(28.dp)
                        .clip(RoundedCornerShape(8.dp)),
                )
                Text(
                    "肉呆去广告",
                    style = MaterialTheme.typography.titleMediumEmphasized,
                    modifier = Modifier
                        .weight(1f)
                        .padding(start = 8.dp),
                )
                Box {
                    IconButton(onClick = { model.sheet = Sheet.More }, shapes = IconButtonDefaults.shapes()) {
                        Glyph(R.drawable.ic_more_horiz, label = "更多")
                    }
                    if (model.newVersion != null) {
                        Box(
                            Modifier
                                .align(Alignment.TopEnd)
                                .padding(10.dp)
                                .size(8.dp)
                                .clip(CircleShape)
                                .background(colors.error),
                        )
                    }
                }
            }
        },
        middle = { maxWidth, maxHeight ->
            val size = min(maxWidth * 0.72f, maxHeight - 112.dp)
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Hero(
                    polygon = HomeShapes[shapeAt],
                    color = colors.primaryContainer,
                    modifier = Modifier.size(size),
                    pressed = pressed,
                    onTap = {
                        haptic.performHapticFeedback(HapticFeedbackType.SegmentTick)
                        shapeAt = (shapeAt + 1) % HomeShapes.size
                    },
                ) {
                    Glyph(R.drawable.ic_ad_off, Modifier.size(size * 0.36f))
                }
                Spacer(Modifier.height(20.dp))
                Text(
                    device?.title.orEmpty(),
                    style = MaterialTheme.typography.headlineMediumEmphasized,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                )
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    ShapeBadge(MaterialShapes.Cookie4Sided, colors.tertiary, Modifier.size(10.dp)) {}
                    Spacer(Modifier.width(8.dp))
                    Text("已就绪", style = MaterialTheme.typography.labelLarge, color = colors.onSurfaceVariant)
                }
            }
        },
        actions = {
            SizedButton(
                text = "一键去广告",
                onClick = {
                    haptic.performHapticFeedback(HapticFeedbackType.Confirm)
                    model.oneTap()
                },
                modifier = Modifier.fillMaxWidth(),
                height = ctaHeight(),
                interactionSource = press,
            )
            Spacer(Modifier.height(8.dp))
            SizedButton(
                text = "还原",
                onClick = model::openRestore,
                modifier = Modifier.fillMaxWidth(),
                icon = R.drawable.ic_history,
                tonal = true,
            )
            Spacer(Modifier.height(8.dp))
        },
    )
}

// ---------- 首次设置 ---------- //

@Composable
fun SetupScreen(model: AppModel, state: String, host: HostActions) {
    val at: Int? = model.setup.at[state]
    val steps = model.setup.steps
    when {
        // 三步清单还没从 view.py 取到：还不知道这一步该说什么（只有演示路径会碰上）
        at == null -> if (steps.isEmpty()) BootScreen() else StatusScreen(state, host)
        at > steps.lastIndex -> BootScreen()
        else -> SetupSteps(model, at, host)
    }
}

/** 三步的按钮落到哪个系统动作；文案不在这里（view.py 的 setup_guide，#646）。 */
private fun runStep(step: SetupStep, host: HostActions) = when (step.key) {
    "about" -> host.openSettings("about")
    "dev" -> host.openSettings("dev")
    "pair" -> host.startPairing()
    else -> Unit
}

@Composable
private fun SetupSteps(model: AppModel, at: Int, host: HostActions) {
    val steps = model.setup.steps
    val list = rememberLazyListState()
    // 从系统设置回到 App 时定位到当前步（#646）；换一步时也滚过去。高亮由 SetupRow 按 i == at 画。
    LaunchedEffect(at, model.visible) { if (model.visible) list.animateScrollToItem(at) }
    val bar = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val colors = MaterialTheme.colorScheme
    Scaffold(
        modifier = Modifier.nestedScroll(bar.nestedScrollConnection),
        containerColor = colors.surfaceContainer,
        topBar = {
            CenteredBar {
                LargeFlexibleTopAppBar(
                    title = { Text("先做 3 个设置", style = MaterialTheme.typography.displaySmallEmphasized) },
                    subtitle = { Text("只做一次，约 1 分钟") },
                    colors = pageBarColors(),
                    scrollBehavior = bar,
                )
            }
        },
        bottomBar = {
            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                Column(
                    modifier = Modifier
                        .widthIn(max = PageWidth)
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp)
                        .navigationBarsPadding()
                        .padding(bottom = 8.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    SizedButton(
                        text = steps[at].action,
                        onClick = { runStep(steps[at], host) },
                        modifier = Modifier.fillMaxWidth(),
                        height = ctaHeight(),
                    )
                    TextButton(onClick = host::requestShizuku, shapes = ButtonDefaults.shapes()) {
                        Text("改用 Shizuku")
                    }
                }
            }
        },
    ) { inner ->
        Box(Modifier.fillMaxSize().padding(inner), contentAlignment = Alignment.TopCenter) {
            LazyColumn(
                state = list,
                modifier = Modifier
                    .widthIn(max = PageWidth)
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(ListItemDefaults.SegmentedGap),
            ) {
                itemsIndexed(steps) { i, step -> SetupRow(i, steps.size, step, i < at, i == at) }
            }
        }
    }
}

@Composable
private fun SetupRow(index: Int, count: Int, step: SetupStep, done: Boolean, current: Boolean) {
    val colors = MaterialTheme.colorScheme
    val badgeColor = when {
        done -> colors.tertiary
        current -> colors.primary
        else -> colors.surfaceContainerHigh
    }
    val badgeContent = when {
        done -> colors.onTertiary
        current -> colors.onPrimary
        else -> colors.onSurfaceVariant
    }
    val polygon = when {
        done -> MaterialShapes.Sunny
        current -> MaterialShapes.Cookie7Sided
        else -> MaterialShapes.Circle
    }
    SegmentedListItem(
        shapes = ListItemDefaults.segmentedShapes(index, count),
        modifier = Modifier.animateContentSize(MaterialTheme.motionScheme.defaultSpatialSpec()),
        colors = if (current) {
            ListItemDefaults.segmentedColors(
                containerColor = colors.secondaryContainer,
                contentColor = colors.onSecondaryContainer,
                supportingContentColor = colors.onSecondaryContainer,
                leadingContentColor = colors.onSecondaryContainer,
            )
        } else {
            ListItemDefaults.segmentedColors()
        },
        verticalAlignment = Alignment.Top,
        leadingContent = {
            ShapeBadge(polygon, badgeColor, Modifier.size(40.dp)) {
                CompositionLocalProvider(LocalContentColor provides badgeContent) {
                    if (done) Glyph(R.drawable.ic_check, Modifier.size(20.dp))
                    else Text("${index + 1}", style = MaterialTheme.typography.titleMediumEmphasized)
                }
            }
        },
        supportingContent = if (current) {
            {
                Column(Modifier.padding(top = 6.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    step.lines.forEachIndexed { k, line ->
                        Row {
                            Text(
                                "${k + 1}",
                                style = MaterialTheme.typography.labelLargeEmphasized,
                                modifier = Modifier.width(18.dp),
                            )
                            Text(line, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    if (step.note.isNotEmpty()) {
                        Text(step.note, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        } else null,
    ) {
        Text(
            step.title,
            style = if (current) MaterialTheme.typography.titleMediumEmphasized else MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(top = if (current) 0.dp else 8.dp),
        )
    }
}

// ---------- Shizuku 与读不到手机：一句话 + 一个按钮 ---------- //

private data class StatusCopy(val title: String, val text: String, val action: String, val run: (HostActions) -> Unit)

private fun statusCopy(state: String) = when (state) {
    "old" -> StatusCopy("安卓版本太低", "安卓 11 以下没有无线调试，要装 Shizuku，按它的说明连一次电脑启动。", "打开 Shizuku") { it.openShizuku() }
    "stopped" -> StatusCopy("Shizuku 还没启动", "打开 Shizuku 按说明启动。手机重启后要再启动一次。", "打开 Shizuku") { it.openShizuku() }
    "ask" -> StatusCopy("允许本 App 使用 Shizuku", "点下面的按钮，在弹窗里选「始终允许」。", "授权") { it.requestShizuku() }
    "denied" -> StatusCopy("之前拒绝了 Shizuku 授权", "打开 Shizuku →「已授权的应用」，打开「肉呆去广告」，再回到这里。", "打开 Shizuku") { it.openShizuku() }
    else -> StatusCopy("读不到这台手机", "到「开发者选项」把「无线调试」关掉再打开，然后回到这里。", "打开开发者选项") { it.openSettings("dev") }
}

@Composable
private fun StatusScreen(state: String, host: HostActions) {
    val copy = statusCopy(state)
    val colors = MaterialTheme.colorScheme
    Page {
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Hero(MaterialShapes.Pentagon, colors.tertiaryContainer, Modifier.size(160.dp)) {
                Glyph(R.drawable.ic_shield, Modifier.size(64.dp))
            }
            Spacer(Modifier.height(32.dp))
            Text(copy.title, style = MaterialTheme.typography.headlineMediumEmphasized, textAlign = TextAlign.Center)
            Spacer(Modifier.height(12.dp))
            Text(
                copy.text,
                style = MaterialTheme.typography.bodyLarge,
                color = colors.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
        SizedButton(
            text = copy.action,
            onClick = { copy.run(host) },
            modifier = Modifier.fillMaxWidth(),
            height = ctaHeight(),
        )
        Spacer(Modifier.height(16.dp))
    }
}

/** MainActivity 提供的系统动作。 */
interface HostActions {
    fun startPairing()
    fun openSettings(which: String)
    fun requestShizuku()
    fun openShizuku()
}
