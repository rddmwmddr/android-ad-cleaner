package com.ahuamiao.adcleaner

/** 系统读出的 APK 身份。只接受同包名、同签名、版本更高的本产品更新。 */
internal data class UpdateIdentity(
    val packageName: String,
    val version: String,
    val code: Long,
    val signers: Set<String>,
) {
    fun rejection(candidate: UpdateIdentity, expected: String): String? = when {
        candidate.packageName != packageName -> "安装包不属于本 App"
        candidate.version != expected -> "安装包版本与更新清单不一致"
        candidate.code <= code -> "安装包不是更新版本"
        signers.isEmpty() || candidate.signers != signers -> "安装包签名与当前 App 不一致"
        else -> null
    }
}
