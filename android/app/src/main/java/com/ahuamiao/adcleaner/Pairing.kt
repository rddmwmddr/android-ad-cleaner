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

    /** 发出带输入框的通知，并打开开发者选项（「无线调试」在里面）。 */
    @JvmStatic
    fun start(context: Context) {
        notify(context, "填写配对码", "在「无线调试 → 使用配对码配对设备」里看到 6 位配对码后，下拉通知栏在这里填写", input = true)
        context.startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS)
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
            val remote = RemoteInput.Builder(KEY).setLabel("6 位配对码").build()
            builder.addAction(Notification.Action.Builder(null, "填写配对码", reply).addRemoteInput(remote).build())
        }
        nm.notify(ID, builder.build())
    }
}

class PairingReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val code = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(Pairing.KEY)?.toString()
            ?.filter { it.isDigit() }.orEmpty()
        if (code.length != 6) {
            Pairing.notify(context, "配对码是 6 位数字", "请对照「使用配对码配对设备」里的数字重新填写", input = true)
            return
        }
        val pending = goAsync()
        AdbShell.app = context.applicationContext
        Pairing.notify(context, "正在配对…", "请先不要关掉「使用配对码配对设备」对话框")
        thread {
            try {
                val paired = AdbShell.pair(code, 8000)
                val connected = paired && AdbShell.connect(8000)
                when {
                    connected -> Pairing.notify(context, "配对成功", "回到「安卓去广告」就能开始。以后不用再配对")
                    paired -> Pairing.notify(context, "配对成功，但还没连上", "回到「安卓去广告」，它会自动再连一次")
                    else -> Pairing.notify(context, "配对没成功",
                        "配对码可能已经变了。重新点「使用配对码配对设备」，用新的配对码再填一次", input = true)
                }
                MainActivity.refreshState()
            } finally {
                pending.finish()
            }
        }
    }
}
