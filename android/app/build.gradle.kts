import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

layout.buildDirectory.set(file(System.getProperty("user.home") + "/Library/Caches/aac-android/app"))

// 版本号跟桌面版同一处：gui/app.py 的 VERSION
val repo = rootProject.file("..")
val appVersion = Regex("""VERSION = "([^"]+)"""").find(repo.resolve("gui/app.py").readText())!!.groupValues[1]
val parts = appVersion.split(".").map { it.toInt() }

android {
    namespace = "com.ahuamiao.adcleaner"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.ahuamiao.adcleaner"
        minSdk = 26
        targetSdk = 35
        versionCode = parts[0] * 10000 + parts[1] * 100 + parts[2]
        versionName = appVersion
        ndk { abiFilters += listOf("arm64-v8a") }
    }
    // 正式签名：证书与密码在仓库被忽略的 .private/android-signing/（不进 GitHub）。丢了就没法覆盖安装更新，只能卸载重装
    val ks = repo.resolve(".private/android-signing/keystore.properties")
    signingConfigs {
        if (ks.exists()) create("release") {
            val p = Properties().apply { ks.reader(Charsets.UTF_8).use { load(it) } }
            storeFile = file(p.getProperty("storeFile"))
            storePassword = p.getProperty("storePassword")
            keyAlias = p.getProperty("keyAlias")
            keyPassword = p.getProperty("keyPassword")
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false     // 引擎经 Chaquopy 反射调 Kotlin（ShizukuShell、Native），不混淆
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/aac-assets"))
}

kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_17) } }

chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython(System.getProperty("user.home") + "/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12")
        pip { install("pillow") }
    }
}

// 引擎、机型脚本、客户端后台与网页原样打进 assets/aac，App 首次启动解到私有目录再跑（路径与桌面版一致）
val syncEngine by tasks.registering(Sync::class) {
    into(layout.buildDirectory.dir("generated/aac-assets/aac"))
    from(repo.resolve("tool")) { into("tool"); include("*.py", "*.dex") }
    from(repo.resolve("recipes")) { into("recipes"); include("*/recipe*.py"); exclude("zztest-*/**") }
    from(repo.resolve("gui")) { into("gui"); include("app.py", "winpreflight.py", "version.py", "web/**") }
    from(repo.resolve("images")) { into("images"); include("dev-*.png") }   // env() 只列 dev-*：界面的教程图
    from(repo.resolve("gui/.venv/lib/python3.12/site-packages/uiautomator2/assets/u2.jar"))
}
tasks.named("preBuild") { dependsOn(syncEngine) }

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("dev.rikka.shizuku:api:13.1.5")
    implementation("dev.rikka.shizuku:provider:13.1.5")
}
