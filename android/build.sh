#!/bin/zsh
# 构建手机版：./build.sh [assembleDebug|assembleRelease]
# 先把 ../tool 与 ../recipes 同步进 assets，再交给 Gradle。
# JAVA_HOME / ANDROID_HOME / GRADLE_HOME 可覆盖，不设时用维护者机器上的默认值。
set -e
if [ -z "${JAVA_HOME:-}" ]; then
  JAVA_HOME="$(/usr/libexec/java_home -v 17)" || { echo "找不到 JDK 17：装 JDK 17 或先设 JAVA_HOME" >&2; exit 1; }
fi
: "${ANDROID_HOME:=$HOME/Library/Android/sdk}"
: "${GRADLE_HOME:=$HOME/Library/gradle/gradle-9.8.2}"
export JAVA_HOME ANDROID_HOME
export PATH="$GRADLE_HOME/bin:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"
cd "$(dirname "$0")"
gradle --console=plain "${@:-assembleDebug}"
