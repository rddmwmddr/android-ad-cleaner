package com.ahuamiao.adcleaner

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import rikka.shizuku.Shizuku
import rikka.sui.Sui

object ShellAccess {
    const val SHIZUKU = "moe.shizuku.privileged.api"
    const val SHIZUKU_PAGE = "https://shizuku.rikka.app/zh-hans/download/"

    /**
     * Sui（Zygisk 模块，#1451）在本进程里拿到了 binder。`ShizukuProvider` 自 Shizuku API 12.1 起
     * 在 ContentProvider 阶段就自动调过 `Sui.init`，这里只读结果——它的约定是「只调一次」。
     * Sui 实现的是同一套 Shizuku API，但没有 Shizuku 管理器 App：判「装没装」不能只看那个包名。
     */
    val sui: Boolean get() = Sui.isSui()

    /** 有 Shizuku API 的提供方：装了 Shizuku 管理器，或 Sui 在跑。 */
    fun provider(context: Context) = sui || installed(context, SHIZUKU)

    /**
     * 能不能以 shell 身份执行，以及差哪一步。已授权的 Shizuku 永远优先；没有就走内置无线调试（#622，安卓 11 起）：
     * need_dev 没开开发者选项 → need_wifi 没开无线调试 → need_pair 没配对。
     * Shizuku 在跑但没授权不再挡内置的路（决策：未授权时仍要能走内置）；要改走 Shizuku 由配对页的次级入口手动切。
     * 安卓 10 及以下没有无线调试，只有 Shizuku：old（没装）/ stopped（装了没启动）/ ask / denied。
     * Sui 同理排在无线调试之后（#1451）：配对好的无线调试照常走，连不上才问 Sui 授权——
     * 没授权 → sui_ask，拒绝过 → sui_denied。安卓 10 及以下没有无线调试可挡，先问 Sui。
     * 连接要经 mDNS 找端口，最多等几秒，只在后台线程调。
     * 这里会顺手去连（Shell.ensure），不是纯查询：「已就绪」的定义就是连得上，光看开关打没打开说明不了（#662）。
     */
    fun state(context: Context): String {
        val shizukuUp = provider(context) && runCatching { Shizuku.pingBinder() }.getOrDefault(false)
        if (shizukuUp && !Shizuku.isPreV11() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) return "ready"
        if (Build.VERSION.SDK_INT < 30) {
            if (sui && shizukuUp) return suiState()
            return when {
                !provider(context) -> "old"
                !shizukuUp -> "stopped"
                Shizuku.shouldShowRequestPermissionRationale() -> "denied"
                else -> "ask"
            }
        }
        if (Shell.ensure()) return "ready"
        if (sui && shizukuUp) return suiState()
        return when {
            !AdbManager.developerOn(context) -> "need_dev"
            !AdbManager.wirelessOn(context) -> "need_wifi"
            else -> "need_pair"
        }
    }

    /** Sui 在跑但没授权：拒绝过才走拨号盘，没拒绝过就直接请求。 */
    private fun suiState() =
        if (runCatching { Shizuku.shouldShowRequestPermissionRationale() }.getOrDefault(false)) "sui_denied" else "sui_ask"

    fun installed(context: Context, pkg: String) = try {
        context.packageManager.getPackageInfo(pkg, 0); true
    } catch (_: PackageManager.NameNotFoundException) {
        false
    }
}
