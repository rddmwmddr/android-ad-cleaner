@file:OptIn(ExperimentalMaterial3ExpressiveApi::class)

package com.ahuamiao.adcleaner.ui

import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ButtonGroup
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/** 页面内容宽度：折叠屏内屏和横屏时不铺满，居中。 */
val PageWidth = 600.dp

@Composable
fun Page(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Column(
            modifier = Modifier
                .widthIn(max = PageWidth)
                .fillMaxSize()
                .safeDrawingPadding()
                .padding(horizontal = 16.dp),
            content = content,
        )
    }
}

/**
 * 有主形状的页面：中间是形状和文字，底下是操作。手机横放时高度不够，改成左右排。
 * [middle] 拿到的是自己能用的宽高，形状大小按剩余高度算。
 */
@Composable
fun HeroPage(
    topBar: @Composable () -> Unit = {},
    middle: @Composable (maxWidth: Dp, maxHeight: Dp) -> Unit,
    actions: @Composable ColumnScope.() -> Unit,
) {
    if (LocalConfiguration.current.screenHeightDp < 480) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
            Column(
                Modifier
                    .widthIn(max = 900.dp)
                    .fillMaxSize()
                    .safeDrawingPadding()
                    .padding(horizontal = 16.dp),
            ) {
                topBar()
                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                    BoxWithConstraints(
                        Modifier
                            .weight(1f)
                            .fillMaxHeight(),
                        contentAlignment = Alignment.Center,
                    ) { middle(maxWidth, maxHeight) }
                    Spacer(Modifier.width(16.dp))
                    Column(Modifier.weight(1f), content = actions)
                }
            }
        }
    } else {
        Page {
            topBar()
            BoxWithConstraints(
                Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) { middle(maxWidth, maxHeight) }
            actions()
        }
    }
}

@Composable
fun Glyph(@DrawableRes id: Int, modifier: Modifier = Modifier, label: String? = null) {
    Icon(painterResource(id), contentDescription = label, modifier = modifier)
}

/** 主按钮：屏幕够高用 L（96dp）；矮屏用 M（56dp），把位置留给内容。 */
@Composable
fun ctaHeight(): Dp =
    if (LocalConfiguration.current.screenHeightDp < 700) ButtonDefaults.MediumContainerHeight else ButtonDefaults.LargeContainerHeight

/** 顶栏跟内容同宽：折叠屏内屏和横屏时标题才和卡片对齐。 */
@Composable
fun CenteredBar(content: @Composable () -> Unit) {
    Box(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceContainer),
        contentAlignment = Alignment.TopCenter,
    ) {
        Box(Modifier.widthIn(max = PageWidth)) { content() }
    }
}

/** 按高度取官方的尺寸规格：形状、按下形变、内边距、图标、字号都跟着按钮大小走。 */
@Composable
fun SizedButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    height: Dp = ButtonDefaults.MediumContainerHeight,
    @DrawableRes icon: Int? = null,
    enabled: Boolean = true,
    tonal: Boolean = false,
    interactionSource: MutableInteractionSource? = null,
) {
    Button(
        onClick = onClick,
        shapes = ButtonDefaults.shapesFor(height),
        modifier = modifier.heightIn(min = height),
        enabled = enabled,
        colors = if (tonal) ButtonDefaults.filledTonalButtonColors() else ButtonDefaults.buttonColors(),
        contentPadding = ButtonDefaults.contentPaddingFor(height),
        interactionSource = interactionSource,
    ) {
        ButtonLabel(text, height, icon)
    }
}

@Composable
fun RowScope.ButtonLabel(text: String, height: Dp, @DrawableRes icon: Int? = null) {
    if (icon != null) {
        Glyph(icon, Modifier.size(ButtonDefaults.iconSizeFor(height)))
        Spacer(Modifier.width(ButtonDefaults.iconSpacingFor(height)))
    }
    Text(text, style = ButtonDefaults.textStyleFor(height).copy(fontWeight = FontWeight.SemiBold), maxLines = 1)
}

data class GroupAction(
    val text: String,
    val icon: Int?,
    val enabled: Boolean = true,
    val outlined: Boolean = false,
    val onClick: () -> Unit,
)

/** 一排两个操作：官方标准按钮组，按下的一个变宽、旁边的让位。文字始终留着。 */
@Composable
fun ActionPair(first: GroupAction, second: GroupAction) {
    val height = ButtonDefaults.MediumContainerHeight
    val sources = remember { listOf(MutableInteractionSource(), MutableInteractionSource()) }
    ButtonGroup(
        overflowIndicator = {},
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        listOf(first, second).forEachIndexed { i, action ->
            customItem(
                buttonGroupContent = {
                    val modifier = Modifier
                        .animateWidth(sources[i])
                        .weight(1f)
                        .heightIn(min = height)
                    val label: @Composable RowScope.() -> Unit = { ButtonLabel(action.text, height, action.icon) }
                    if (action.outlined) {
                        OutlinedButton(
                            onClick = action.onClick,
                            shapes = ButtonDefaults.shapesFor(height),
                            modifier = modifier,
                            enabled = action.enabled,
                            contentPadding = ButtonDefaults.contentPaddingFor(height),
                            interactionSource = sources[i],
                            content = label,
                        )
                    } else {
                        FilledTonalButton(
                            onClick = action.onClick,
                            shapes = ButtonDefaults.shapesFor(height),
                            modifier = modifier,
                            enabled = action.enabled,
                            contentPadding = ButtonDefaults.contentPaddingFor(height),
                            interactionSource = sources[i],
                            content = label,
                        )
                    }
                },
                menuContent = {},
            )
        }
    }
}

/** 分段列表：段间 2dp，首尾外角大、中间小。 */
@Composable
fun Segments(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(ListItemDefaults.SegmentedGap), content = content)
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier, trailing: @Composable (RowScope.() -> Unit)? = null) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = 40.dp)
            .padding(start = 16.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text,
            style = MaterialTheme.typography.titleSmallEmphasized,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.weight(1f),
        )
        trailing?.invoke(this)
    }
}

/** 带开关的分段行：开没开看开关，整行不染色（选中色整块铺开太抢，文字对比度也不稳）。 */
@Composable
fun toggleRowColors() = ListItemDefaults.segmentedColors(
    selectedContainerColor = MaterialTheme.colorScheme.surface,
    selectedContentColor = MaterialTheme.colorScheme.onSurface,
    selectedLeadingContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    selectedTrailingContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    selectedOverlineContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    selectedSupportingContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
)

/** 顶栏和页面同色，滚动时也不变，靠大标题收起表达层次。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun pageBarColors() = TopAppBarDefaults.topAppBarColors(
    containerColor = MaterialTheme.colorScheme.surfaceContainer,
    scrolledContainerColor = MaterialTheme.colorScheme.surfaceContainer,
)

fun formatDuration(sec: Int): String = if (sec < 60) "$sec 秒" else "${sec / 60} 分 ${sec % 60} 秒"
