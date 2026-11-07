@file:OptIn(ExperimentalMaterial3ExpressiveApi::class)

package com.ahuamiao.adcleaner.ui

import androidx.compose.animation.AnimatedVisibilityScope
import androidx.compose.animation.BoundsTransform
import androidx.compose.animation.SharedTransitionScope
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.AnimationSpec
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialShapes
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.contentColorFor
import androidx.compose.material3.toPath
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.graphics.shapes.Morph
import androidx.graphics.shapes.RoundedPolygon

/** 一个会变形的形状：换目标时从当前形状弹簧过渡到新形状。 */
@Stable
class MorphState(initial: RoundedPolygon) {
    private var target = initial
    private var morph by mutableStateOf(Morph(initial, initial))
    private val progress = Animatable(1f)

    suspend fun morphTo(polygon: RoundedPolygon, spec: AnimationSpec<Float>) {
        if (polygon === target) return
        morph = Morph(target, polygon)
        target = polygon
        progress.snapTo(0f)
        progress.animateTo(1f, spec)
    }

    /** 只在绘制阶段读进度：动画期间只重画，不重组。 */
    fun fill(path: Path) = morph.toPath(progress.value, path)
}

/** 把形状铺满这个元素。 */
fun Modifier.morphFill(state: MorphState, color: () -> Color, angle: () -> Float = { 0f }) = drawWithCache {
    val path = Path()
    onDrawBehind {
        state.fill(path)
        scale(size.width, size.height, pivot = Offset.Zero) {
            rotate(angle(), pivot = Offset(0.5f, 0.5f)) {
                drawPath(path, color())
            }
        }
    }
}

/** 贯穿首页、准备、执行、完成的那个形状。状态放在根上，换页时接着变形，不从头来。 */
@Stable
class HeroState {
    val morph = MorphState(MaterialShapes.Cookie12Sided)
    var angle by mutableFloatStateOf(0f)
}

val LocalHero = compositionLocalOf { HeroState() }
val LocalSharedScope = compositionLocalOf<SharedTransitionScope?> { null }
val LocalPageScope = compositionLocalOf<AnimatedVisibilityScope?> { null }

private const val DEGREES_PER_SECOND = 9f

@Composable
fun Hero(
    polygon: RoundedPolygon,
    color: Color,
    modifier: Modifier = Modifier,
    pressed: Boolean = false,
    spin: Boolean = true,
    onTap: (() -> Unit)? = null,
    content: @Composable BoxScope.() -> Unit,
) {
    val hero = LocalHero.current
    val motion = MaterialTheme.motionScheme
    val morphSpec = motion.slowSpatialSpec<Float>()
    LaunchedEffect(polygon) { hero.morph.morphTo(polygon, morphSpec) }

    val fill by animateColorAsState(color, motion.slowEffectsSpec())
    val press by animateFloatAsState(if (pressed) 0.92f else 1f, motion.fastSpatialSpec())

    if (spin && !LocalReduceMotion.current) {
        LaunchedEffect(Unit) {
            var last = withFrameMillis { it }
            while (true) {
                val now = withFrameMillis { it }
                hero.angle = (hero.angle + (now - last) * DEGREES_PER_SECOND / 1000f) % 360f
                last = now
            }
        }
    }

    val shared = LocalSharedScope.current
    val page = LocalPageScope.current
    val bounds = motion.defaultSpatialSpec<androidx.compose.ui.geometry.Rect>()
    val travel = if (shared != null && page != null) with(shared) {
        Modifier.sharedElement(
            sharedContentState = rememberSharedContentState("hero"),
            animatedVisibilityScope = page,
            boundsTransform = BoundsTransform { _, _ -> bounds },
        )
    } else Modifier

    Box(
        modifier = modifier
            .then(travel)
            .graphicsLayer {
                scaleX = press
                scaleY = press
            }
            .morphFill(hero.morph, { fill }, { hero.angle })
            .then(
                if (onTap != null) Modifier.pointerInput(onTap) { detectTapGestures { onTap() } } else Modifier,
            ),
        contentAlignment = Alignment.Center,
    ) {
        CompositionLocalProvider(LocalContentColor provides contentColorFor(color)) { content() }
    }
}

/** 列表里的小形状：步骤号、结果状态。 */
@Composable
fun ShapeBadge(
    polygon: RoundedPolygon,
    color: Color,
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    val motion = MaterialTheme.motionScheme
    val state = remember { MorphState(polygon) }
    val spec = motion.defaultSpatialSpec<Float>()
    LaunchedEffect(polygon) { state.morphTo(polygon, spec) }
    val fill by animateColorAsState(color, motion.defaultEffectsSpec())
    Box(modifier.morphFill(state, { fill }), contentAlignment = Alignment.Center, content = content)
}
