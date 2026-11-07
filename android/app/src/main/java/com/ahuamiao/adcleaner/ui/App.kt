package com.ahuamiao.adcleaner.ui

import androidx.activity.compose.PredictiveBackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.SharedTransitionLayout
import androidx.compose.animation.SizeTransform
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** 前进方向：决定换页时从哪边进。 */
private fun rank(screen: Screen) = when (screen) {
    is Screen.Boot, is Screen.Failed -> 0
    is Screen.Setup, is Screen.Home -> 1
    is Screen.Choose, is Screen.Prepare -> 2
    is Screen.Run -> 3
    is Screen.Done -> 4
}

@Composable
fun App(model: AppModel, host: HostActions) {
    AacTheme {
        val colors = MaterialTheme.colorScheme
        val motion = MaterialTheme.motionScheme
        val hero = remember { HeroState() }
        val slide = motion.defaultSpatialSpec<IntOffset>()
        val fade = motion.defaultEffectsSpec<Float>()

        // 预测性返回：手指拖着，当前页跟着缩小、露出圆角；松手才真的返回，撤回就弹回去
        val back = remember { Animatable(0f) }
        val backSpec = motion.fastSpatialSpec<Float>()
        val scope = rememberCoroutineScope()
        PredictiveBackHandler(enabled = model.canGoBack()) { events ->
            try {
                events.collect { back.snapTo(it.progress) }
                model.back()
                scope.launch { back.animateTo(0f, backSpec) }
            } catch (e: CancellationException) {
                scope.launch { back.animateTo(0f, backSpec) }
                throw e
            }
        }
        val density = LocalDensity.current

        Surface(modifier = Modifier.fillMaxSize(), color = colors.surfaceDim) {
            SharedTransitionLayout(
                Modifier
                    .fillMaxSize()
                    .graphicsLayer {
                        val scale = 1f - back.value * 0.1f
                        scaleX = scale
                        scaleY = scale
                    }
                    .clip(RoundedCornerShape(with(density) { (back.value * 28.dp.toPx()).toDp() })),
            ) {
                // 页面底色比列表卡片深一档：分段列表靠这一点层次分出卡片
                Surface(modifier = Modifier.fillMaxSize(), color = colors.surfaceContainer) {
                    AnimatedContent(
                        targetState = model.screen,
                        contentKey = { it::class },
                        transitionSpec = {
                            val dir = if (rank(targetState) >= rank(initialState)) 1 else -1
                            (slideInHorizontally(slide) { dir * it / 8 } + fadeIn(fade)) togetherWith
                                (slideOutHorizontally(slide) { -dir * it / 8 } + fadeOut(fade)) using
                                SizeTransform(clip = false)
                        },
                        label = "screen",
                    ) { screen ->
                        CompositionLocalProvider(
                            LocalHero provides hero,
                            LocalSharedScope provides this@SharedTransitionLayout,
                            LocalPageScope provides this,
                        ) {
                            when (screen) {
                                is Screen.Boot -> BootScreen()
                                is Screen.Failed -> FailedScreen(screen.reason)
                                is Screen.Setup -> SetupScreen(model, screen.state, host)
                                is Screen.Home -> HomeScreen(model)
                                is Screen.Prepare -> PrepareScreen(model, screen.at)
                                is Screen.Choose -> ChooseScreen(model)
                                is Screen.Run -> RunScreen(model)
                                is Screen.Done -> DoneScreen(model, screen.run)
                            }
                        }
                    }
                }
            }
        }
        SheetHost(model)
        NoticeHost(model)
    }
}
