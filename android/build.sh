#!/bin/zsh
# 构建手机版：./build.sh [assembleDebug|assembleRelease]
# 先把 ../tool 与 ../recipes 同步进 assets，再交给 Gradle。
set -e
export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$HOME/Library/gradle/gradle-8.10.2/bin:$PATH"
cd "$(dirname "$0")"
gradle --console=plain "${@:-assembleDebug}"
