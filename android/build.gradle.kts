plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("com.chaquo.python") version "17.2.0" apply false
}
// 构建目录放在 ~/Library/Caches：仓库可能在同步盘里，避免产生冲突副本
layout.buildDirectory.set(file(System.getProperty("user.home") + "/Library/Caches/aac-android/root"))
