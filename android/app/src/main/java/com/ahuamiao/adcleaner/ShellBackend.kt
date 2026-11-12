package com.ahuamiao.adcleaner

/**
 * 起命令服务前的后端判定：走哪条通道、没就绪报哪句话、能不能开流。
 *
 * 已授权的 Shizuku 永远优先，它不可用时才用内置无线调试（沿用 #622 的做法）。判定只在这里定义，
 * `Shell` 的 `connected()` / `ensure()` / `client()` 共用这一份。纯判断、不碰 Android 运行时，
 * 规则与文案由 JVM 单测直接覆盖（#1034）。
 */
internal sealed interface ShellBackend {
    object Shizuku : ShellBackend
    object Wireless : ShellBackend

    /** 两条通道都没就绪。`reason` 是给用户看的整句，已带「命令服务不可用：」前缀。 */
    data class Missing(val reason: String) : ShellBackend

    companion object {
        /** 只走无线调试的路径（`AdbShell.client()`）用这句：别把问题推到用户没装的 Shizuku 上。 */
        const val NO_WIRELESS = "命令服务不可用：内置无线调试没有连上，到「开发者选项」把「无线调试」关掉再打开"

        /** `ShizukuShell.ready()` 同时含授权检查，所以「没在运行」与「没授权」得一起说。 */
        const val NO_BACKEND = "命令服务不可用：Shizuku 没在运行或没有授权，内置无线调试也没有连上。启动 Shizuku，或到「开发者选项」把「无线调试」关掉再打开"

        /**
         * 已授权的 Shizuku 优先；没有就用已连上的内置无线调试。两条都没有时给一句可行动的说明——
         * 对没连上的后端开流只会拿到 libadb 的 `IllegalStateException: connect() must be called first`。
         */
        fun pick(shizukuReady: Boolean, wirelessConnected: Boolean): ShellBackend = when {
            shizukuReady -> Shizuku
            wirelessConnected -> Wireless
            else -> Missing(NO_BACKEND)
        }
    }
}

/**
 * 开流前的闸：没连上就先按 `ensure()` 的口径试一次连接，还不通就抛那句整话（#1034）。
 *
 * 依赖全由调用方给：`AdbShell` 摸的是 Android 运行时，独立成函数才能被 JVM 单测守住。
 */
internal fun <T> openWhenReady(ready: Boolean, connect: () -> Boolean, open: () -> T): T {
    if (!ready && !connect()) throw ShellUnavailable(ShellBackend.NO_WIRELESS)
    return open()
}
