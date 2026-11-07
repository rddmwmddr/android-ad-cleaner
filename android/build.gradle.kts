plugins {
    id("com.android.application") version "9.5.1" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.3.21" apply false
    id("com.chaquo.python") version "17.2.0" apply false
}
// 构建目录放在 ~/Library/Caches：仓库可能在同步盘里，避免产生冲突副本
layout.buildDirectory.set(file(System.getProperty("user.home") + "/Library/Caches/aac-android/root"))
