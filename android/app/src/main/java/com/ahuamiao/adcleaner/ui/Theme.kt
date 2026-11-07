package com.ahuamiao.adcleaner.ui

import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialExpressiveTheme
import androidx.compose.material3.MotionScheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.expressiveLightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight

/** 用户在系统里关了动画：形状不再持续旋转，其余动效由 Compose 按系统比例缩短。 */
val LocalReduceMotion = staticCompositionLocalOf { false }

/** 数字等宽：进度、用时跳动时不晃。 */
const val TABULAR = "tnum"

/**
 * 强调字重。官方令牌是 500，可很多中文字体只有常规和粗体两档，500 落回常规，强调就没了。
 * 标题和大字用粗体，小一号的用 600（只有两档的字体也会落到粗体）。
 */
private val AacTypography = Typography().run {
    copy(
        displayLargeEmphasized = displayLargeEmphasized.copy(fontWeight = FontWeight.Bold),
        displayMediumEmphasized = displayMediumEmphasized.copy(fontWeight = FontWeight.Bold),
        displaySmallEmphasized = displaySmallEmphasized.copy(fontWeight = FontWeight.Bold),
        headlineLargeEmphasized = headlineLargeEmphasized.copy(fontWeight = FontWeight.Bold),
        headlineMediumEmphasized = headlineMediumEmphasized.copy(fontWeight = FontWeight.Bold),
        headlineSmallEmphasized = headlineSmallEmphasized.copy(fontWeight = FontWeight.Bold),
        titleLargeEmphasized = titleLargeEmphasized.copy(fontWeight = FontWeight.SemiBold),
        titleMediumEmphasized = titleMediumEmphasized.copy(fontWeight = FontWeight.SemiBold),
        titleSmallEmphasized = titleSmallEmphasized.copy(fontWeight = FontWeight.SemiBold),
        labelLargeEmphasized = labelLargeEmphasized.copy(fontWeight = FontWeight.SemiBold),
    )
}

@Composable
fun AacTheme(content: @Composable () -> Unit) {
    val context = LocalContext.current
    val dark = isSystemInDarkTheme()
    val colors = when {
        Build.VERSION.SDK_INT >= 31 -> if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        dark -> darkColorScheme()
        else -> expressiveLightColorScheme()
    }
    val reduce = remember {
        Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
    CompositionLocalProvider(LocalReduceMotion provides reduce) {
        MaterialExpressiveTheme(
            colorScheme = colors,
            motionScheme = MotionScheme.expressive(),
            typography = AacTypography,
            content = content,
        )
    }
}
