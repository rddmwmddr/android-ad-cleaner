@file:OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)

package com.ahuamiao.adcleaner.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ContainedLoadingIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.FloatingToolbarDefaults
import androidx.compose.material3.HorizontalFloatingToolbar
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MediumFlexibleTopAppBar
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedListItem
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.TriStateCheckbox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import com.ahuamiao.adcleaner.R

@Composable
fun ChooseScreen(model: AppModel) {
    val bar = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val selection = model.selection
    val colors = MaterialTheme.colorScheme
    Scaffold(
        modifier = Modifier.nestedScroll(bar.nestedScrollConnection),
        containerColor = colors.surfaceContainer,
        topBar = {
            CenteredBar {
            MediumFlexibleTopAppBar(
                title = { Text("确认关闭哪些", style = MaterialTheme.typography.headlineMediumEmphasized) },
                subtitle = selection?.let { s -> { Text(s.detection.name) } },
                navigationIcon = {
                    IconButton(onClick = model::goHomeNow, shapes = IconButtonDefaults.shapes()) {
                        Glyph(R.drawable.ic_arrow_back, label = "返回")
                    }
                },
                colors = pageBarColors(),
                scrollBehavior = bar,
            )
            }
        },
    ) { inner ->
        Box(
            Modifier
                .fillMaxSize()
                .padding(top = inner.calculateTopPadding()),
            contentAlignment = Alignment.TopCenter,
        ) {
            if (selection == null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    ContainedLoadingIndicator(Modifier.size(72.dp))
                }
            } else {
                ChooseList(model, selection)
                StartToolbar(model, selection, Modifier.align(Alignment.BottomCenter))
            }
        }
    }
}

@Composable
private fun StartToolbar(model: AppModel, selection: Selection, modifier: Modifier) {
    val blocked = selection.detection.blocked
    val height = ButtonDefaults.MinHeight
    HorizontalFloatingToolbar(
        expanded = true,
        modifier = modifier
            .navigationBarsPadding()
            .padding(bottom = 16.dp)
            .height(FloatingToolbarDefaults.ContainerSize),
        colors = FloatingToolbarDefaults.vibrantFloatingToolbarColors(),
    ) {
        Text(
            "已选 ${selection.count} 项",
            style = MaterialTheme.typography.titleSmallEmphasized.merge(TextStyle(fontFeatureSettings = TABULAR)),
            modifier = Modifier
                .align(Alignment.CenterVertically)
                .padding(horizontal = 12.dp),
        )
        Spacer(Modifier.width(8.dp))
        Button(
            onClick = model::startChosen,
            shapes = ButtonDefaults.shapesFor(height),
            enabled = !blocked,
        ) {
            ButtonLabel("开始", height, R.drawable.ic_play_arrow)
        }
    }
}

@Composable
private fun ChooseList(model: AppModel, selection: Selection) {
    val detection = selection.detection
    val colors = MaterialTheme.colorScheme
    LazyColumn(
        modifier = Modifier
            .widthIn(max = PageWidth)
            .fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 120.dp),
        verticalArrangement = Arrangement.spacedBy(ListItemDefaults.SegmentedGap),
    ) {
        item {
            Text(
                "开始前会存一份改动前的快照，每一项都能在「还原改动」里恢复。执行期间请保持手机亮屏、解锁。",
                style = MaterialTheme.typography.bodyMedium,
                color = colors.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 12.dp),
            )
        }
        if (detection.warnings.isNotEmpty()) {
            item {
                Surface(
                    shape = MaterialTheme.shapes.extraLarge,
                    // 不是所有提示都拦着开始（展开的折叠屏照常能关营销通知），拦不住的用中性色，别当成错误
                    color = if (detection.blocked) colors.errorContainer else colors.secondaryContainer,
                    contentColor = if (detection.blocked) colors.onErrorContainer else colors.onSecondaryContainer,
                    modifier = Modifier.padding(bottom = 12.dp),
                ) {
                    Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        detection.warnings.forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
                        Button(onClick = model::restartScan, shapes = ButtonDefaults.shapes()) {
                            ButtonLabel("重新检测", ButtonDefaults.MinHeight, R.drawable.ic_refresh)
                        }
                    }
                }
            }
        }

        item { SectionTitle("App 里的广告开关") }
        item { RecipeBlock(model, selection) }

        item {
            Spacer(Modifier.height(16.dp))
            SectionTitle(
                when {
                    selection.scan is ScanState.Ready && selection.channelCount > 0 ->
                        "营销通知 ${selection.channelSelected} / ${selection.channelCount}"
                    else -> "营销通知"
                },
            ) {
                if (selection.channelCount > 0) {
                    TextButton(onClick = { selection.setAllChannels(true) }, shapes = ButtonDefaults.shapes()) { Text("全选") }
                    TextButton(onClick = { selection.setAllChannels(false) }, shapes = ButtonDefaults.shapes()) { Text("全不选") }
                }
                if (selection.scan !is ScanState.Loading) {
                    IconButton(onClick = model::rescan, shapes = IconButtonDefaults.shapes()) {
                        Glyph(R.drawable.ic_refresh, label = "重新扫描")
                    }
                }
            }
        }
        when (val scan = selection.scan) {
            is ScanState.Loading -> item {
                Surface(shape = MaterialTheme.shapes.large, color = colors.surface) {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        LoadingIndicator(Modifier.size(32.dp))
                        Spacer(Modifier.width(12.dp))
                        Text("正在扫描", style = MaterialTheme.typography.bodyLarge)
                    }
                }
            }
            is ScanState.Failed -> item {
                Surface(shape = MaterialTheme.shapes.extraLarge, color = colors.errorContainer, contentColor = colors.onErrorContainer) {
                    Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("通知扫描未完成", style = MaterialTheme.typography.titleMediumEmphasized)
                        Text(scan.message, style = MaterialTheme.typography.bodyMedium)
                        if (scan.detail.isNotEmpty() && scan.detail != scan.message) {
                            Text(scan.detail, style = MaterialTheme.typography.bodySmall)
                        }
                        TextButton(
                            onClick = model::copyDiagnostics,
                            shapes = ButtonDefaults.shapes(),
                        ) { Text("复制完整诊断") }
                    }
                }
            }
            is ScanState.Ready -> {
                if (scan.notes.isNotEmpty()) {
                    item {
                        Text(
                            scan.notes.joinToString("\n"),
                            style = MaterialTheme.typography.bodySmall,
                            color = colors.onSurfaceVariant,
                            modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 8.dp),
                        )
                    }
                }
                if (selection.groups.isEmpty()) {
                    item {
                        Surface(shape = MaterialTheme.shapes.large, color = colors.surface) {
                            Text(
                                "没有开着的营销渠道。App 可能还没创建渠道，用一阵再扫。",
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.padding(16.dp),
                            )
                        }
                    }
                }
                itemsIndexed(selection.groups, key = { _, g -> g.label }) { i, group ->
                    ChannelGroupRow(group, i, selection.groups.size)
                }
            }
        }

        item {
            Spacer(Modifier.height(16.dp))
            SectionTitle("快应用")
        }
        item {
            if (detection.quickapps.isNotEmpty()) {
                SegmentedListItem(
                    checked = selection.quickapp,
                    onCheckedChange = { selection.quickapp = it },
                    shapes = ListItemDefaults.segmentedShapes(0, 1),
                    colors = toggleRowColors(),
                    trailingContent = { Switch(selection.quickapp, onCheckedChange = null) },
                    supportingContent = { Text(detection.quickappNote) },
                ) { Text("关闭 ${detection.quickapps.joinToString("、")}") }
            } else {
                PlainRow(detection.quickappState)
            }
        }

        item {
            Spacer(Modifier.height(16.dp))
            SectionTitle("广告组件")
        }
        if (detection.ads.isEmpty()) {
            item { PlainRow(detection.adsState) }
        } else {
            itemsIndexed(detection.ads, key = { _, a -> a.pkg }) { i, ad ->
                SegmentedListItem(
                    checked = selection.ads[ad.pkg] == true,
                    onCheckedChange = { selection.ads[ad.pkg] = it },
                    shapes = ListItemDefaults.segmentedShapes(i, detection.ads.size),
                    colors = toggleRowColors(),
                    trailingContent = { Switch(selection.ads[ad.pkg] == true, onCheckedChange = null) },
                    supportingContent = { Text("${ad.name}。挂起只是暂停运行，可还原，不影响系统更新。") },
                ) { Text("挂起 ${ad.pkg}") }
            }
        }

        item {
            Spacer(Modifier.height(16.dp))
            SegmentedListItem(
                onClick = model::checkUi,
                shapes = ListItemDefaults.segmentedShapes(0, 1),
                leadingContent = { Glyph(R.drawable.ic_smartphone) },
            ) { Text("检查读屏连接") }
        }
    }
}

@Composable
private fun PlainRow(text: String) {
    SegmentedListItem(shapes = ListItemDefaults.segmentedShapes(0, 1)) {
        Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun RecipeBlock(model: AppModel, selection: Selection) {
    val detection = selection.detection
    val manual = detection.manualUrl.isNotEmpty()
    Segments {
        if (detection.steps.isNotEmpty()) {
            val rows = if (manual) 3 else 2
            SegmentedListItem(
                checked = selection.recipe,
                onCheckedChange = selection::chooseRecipe,
                shapes = ListItemDefaults.segmentedShapes(0, rows),
                colors = toggleRowColors(),
                trailingContent = { Switch(selection.recipe, onCheckedChange = null) },
                supportingContent = { Text(detection.recipeNote) },
            ) { Text(detection.recipeLabel) }
            SegmentedListItem(shapes = ListItemDefaults.segmentedShapes(1, rows)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    detection.steps.forEach { step ->
                        val on = selection.steps[step] == true
                        FilterChip(
                            selected = on,
                            onClick = { selection.setStep(step, !on) },
                            label = { Text(step) },
                            leadingIcon = if (on) {
                                { Glyph(R.drawable.ic_check, Modifier.size(FilterChipDefaults.IconSize)) }
                            } else null,
                        )
                    }
                }
            }
            if (manual) ManualRow(model, detection, 2, rows)
        } else {
            ManualRow(model, detection, 0, 1)
        }
    }
}

@Composable
private fun ManualRow(model: AppModel, detection: Detection, index: Int, count: Int) {
    SegmentedListItem(
        onClick = { model.openUrl(detection.manualUrl) },
        shapes = ListItemDefaults.segmentedShapes(index, count),
        trailingContent = { Glyph(R.drawable.ic_open_in_new) },
        supportingContent = {
            Text(if (detection.steps.isEmpty()) "这个型号还没有脚本，App 里的开关要照清单手动关" else "这个型号没有专用脚本，没关到的照清单手动关")
        },
    ) { Text("${detection.manualName} 手动清单".trim()) }
}

@Composable
private fun ChannelGroupRow(group: ChannelGroup, index: Int, count: Int) {
    var expanded by rememberSaveable(group.label) { mutableStateOf(false) }
    val motion = MaterialTheme.motionScheme
    val turn by animateFloatAsState(if (expanded) 180f else 0f, motion.defaultSpatialSpec())
    val colors = MaterialTheme.colorScheme
    val shapes = ListItemDefaults.segmentedShapes(index, count)
    val clear = ListItemDefaults.colors(containerColor = Color.Transparent)
    val clearToggle = ListItemDefaults.colors(containerColor = Color.Transparent, selectedContainerColor = Color.Transparent)
    Surface(shape = shapes.shape, color = colors.surface) {
        Column {
            ListItem(
                onClick = { expanded = !expanded },
                colors = clear,
                leadingContent = {
                    TriStateCheckbox(
                        state = when (group.selected) {
                            0 -> ToggleableState.Off
                            group.channels.size -> ToggleableState.On
                            else -> ToggleableState.Indeterminate
                        },
                        onClick = {
                            val on = group.selected != group.channels.size
                            group.channels.forEach { it.checked = on }
                        },
                    )
                },
                trailingContent = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "${group.selected} / ${group.channels.size}",
                            style = MaterialTheme.typography.labelLarge.merge(TextStyle(fontFeatureSettings = TABULAR)),
                            color = colors.onSurfaceVariant,
                        )
                        Spacer(Modifier.width(4.dp))
                        CompositionLocalProvider(LocalContentColor provides colors.onSurfaceVariant) {
                            Glyph(R.drawable.ic_expand_more, Modifier.rotate(turn))
                        }
                    }
                },
            ) { Text(group.label, maxLines = 2) }
            AnimatedVisibility(
                visible = expanded,
                enter = expandVertically(motion.defaultSpatialSpec()) + fadeIn(motion.defaultEffectsSpec()),
                exit = shrinkVertically(motion.fastSpatialSpec()) + fadeOut(motion.fastEffectsSpec()),
            ) {
                Column {
                    group.channels.forEach { channel ->
                        ListItem(
                            checked = channel.checked,
                            onCheckedChange = { channel.checked = it },
                            colors = clearToggle,
                            leadingContent = { Checkbox(channel.checked, onCheckedChange = null) },
                        ) { Text(channel.name, style = MaterialTheme.typography.bodyMedium) }
                    }
                }
            }
        }
    }
}
