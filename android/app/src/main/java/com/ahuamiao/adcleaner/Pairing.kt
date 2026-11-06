package com.ahuamiao.adcleaner

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlin.concurrent.thread

/**
 * 无线调试配对（#622）。配对码只在系统「使用配对码配对设备」对话框开着时有效，切回本 App 对话框就关了，
 * 所以码填在通知栏里（带输入框的通知，Shizuku / Mika 同样做法）。
 *
 * 不在后台一直找配对端口：用户在对话框里时本 App 在后台，小米 HyperOS 会把它冻住。填码提交的那一刻
 * 系统把回复送进来、App 醒着，当场找端口（对话框此时还开着）再配对。
 */
object Pairing {
    const val ACTION = "com.ahuamiao.adcleaner.PAIR"
    const val KEY = "code"
    private const val CHANNEL = "pair"
    private const val ID = 3

    /** 手动填写：发出带输入框的通知，并打开开发者选项（「无线调试」在里面）。自动识别不可用时走这条。 */
    @JvmStatic
    fun start(context: Context) {
        notify(context, "填写屏幕上的 6 位数字", "在「无线调试 → 使用配对码配对设备」里看到 6 位数字后，点下面的「填写」把它填进来", input = true)
        openWireless(context)
    }

    /** 打开开发者选项并高亮「无线调试」那一行（AOSP 的 fragment 参数；不认的系统只是打开开发者选项）。 */
    @JvmStatic
    fun openWireless(context: Context) {
        val key = ":settings:fragment_args_key"
        context.startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS)
            .putExtra(key, "toggle_adb_wireless")
            .putExtra(":settings:show_fragment_args", android.os.Bundle().apply { putString(key, "toggle_adb_wireless") })
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun notify(context: Context, title: String, text: String, input: Boolean = false) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "无线调试配对", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(context, 3, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val builder = Notification.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_edit)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(!input)
        if (input) {
            val reply = PendingIntent.getBroadcast(context, 4,
                Intent(context, PairingReceiver::class.java).setAction(ACTION),
                PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val remote = RemoteInput.Builder(KEY).setLabel("屏幕上的 6 位数字").build()
            builder.addAction(Notification.Action.Builder(null, "填写", reply).addRemoteInput(remote).build())
        }
        nm.notify(ID, builder.build())
    }
}

class PairingReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val code = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(Pairing.KEY)?.toString()
            ?.filter { it.isDigit() }.orEmpty()
        if (code.length != 6) {
            Pairing.notify(context, "要填 6 位数字", "请对照「使用配对码配对设备」里显示的数字重新填写", input = true)
            return
        }
        val pending = goAsync()
        AdbShell.app = context.applicationContext
        Pairing.notify(context, "正在授权…", "请先不要关掉「使用配对码配对设备」那个页面")
        thread {
            try {
                val paired = AdbShell.pair(code, 8000)
                val connected = paired && AdbShell.connect(8000)
                when {
                    connected -> Pairing.notify(context, "授权完成，以后不用再做", "回到「安卓去广告」就能开始")
                    paired -> Pairing.notify(context, "授权完成", "回到「安卓去广告」，它会自动连上")
                    else -> Pairing.notify(context, "授权没成功",
                        "数字可能已经变了（每次打开那个页面都会换）。再点一次「使用配对码配对设备」，填新的 6 位数字", input = true)
                }
                MainActivity.refreshState()
            } finally {
                pending.finish()
            }
        }
    }
}
