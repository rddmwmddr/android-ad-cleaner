import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.io.File
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

layout.buildDirectory.set(file(System.getProperty("user.home") + "/Library/Caches/aac-android/app"))

// 版本号跟桌面版同一处：gui/app.py 的 VERSION
val repo = rootProject.file("..")
val appVersion = Regex("""VERSION = "([^"]+)"""").find(repo.resolve("gui/app.py").readText())!!.groupValues[1]
val parts = appVersion.split(".").map { it.toInt() }

android {
    namespace = "com.ahuamiao.adcleaner"
    compileSdk = 37
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
    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/aac-assets").get().asFile)
}

kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_17) } }

chaquopy {
    defaultConfig {
        version = "3.12"
        // 构建机上的 Python 3.12：本机默认走 uv 装的那份，别的机器与 CI 用 CHAQUOPY_PYTHON 指定（#678）。
        // 以前这里写死 macOS 的 uv 路径，别的系统一构建就报「is not a valid Python 3.12 command」。
        val buildPythonPath = System.getenv("CHAQUOPY_PYTHON")
            ?: File(System.getProperty("user.home"), ".local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12").path
        require(File(buildPythonPath).canExecute()) {
            "找不到构建用的 Python 3.12：把 CHAQUOPY_PYTHON 指向它（现在是 $buildPythonPath）"
        }
        buildPython(buildPythonPath)
        pip { install("pillow") }
    }
}

// 引擎、机型脚本、客户端后台原样打进 assets/aac，App 首次启动解到私有目录再跑（路径与桌面版一致）；界面是 Compose，不带网页
// 读屏是 App 自己的 ShellServer（#623），不再带 u2.jar
val syncEngine by tasks.registering(Sync::class) {
    into(layout.buildDirectory.dir("generated/aac-assets/aac"))
    from(repo.resolve("tool")) { into("tool"); include("*.py", "*.dex") }
    from(repo.resolve("recipes")) { into("recipes"); include("*/recipe*.py"); exclude("zztest-*/**") }
    from(repo.resolve("gui")) { into("gui"); include("app.py", "winpreflight.py", "version.py", "web/chime.wav") }
    from(repo.resolve("docs/手机版教程")) { into("docs"); include("brand-taps.json") }   // 首次设置按品牌说路径
}
tasks.named("preBuild") { dependsOn(syncEngine) }

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.13.0")
    // 官方 Material 3 Expressive（ADR-0018）。1.5 要求 compileSdk 37、AGP 9.1；Chaquopy 17.2 支持到 AGP 9.5
    implementation("androidx.compose.material3:material3:1.5.0-rc01")
    implementation("androidx.graphics:graphics-shapes:1.1.0")
    implementation("dev.rikka.shizuku:api:13.1.5")
    implementation("dev.rikka.shizuku:provider:13.1.5")
    // 内置无线调试配对与连接（#622）。libadb-android 双许可 GPL-3.0-or-later / Apache-2.0，按 Apache-2.0 使用
    implementation("com.github.MuntashirAkon:libadb-android:3.1.1")
    // 授权时在本机识别配对码（#634）：模型打包进 APK，离线可用，不依赖 Google 服务
    implementation("com.google.mlkit:text-recognition:16.0.1")
    implementation("com.github.MuntashirAkon:sun-security-android:1.1")
    implementation("org.conscrypt:conscrypt-android:2.5.3")
    // ShellServer 只用 java.io 与 ProcessBuilder，能在 JVM 上单测协议层（android/README.md）
    testImplementation("junit:junit:4.13.2")
}
