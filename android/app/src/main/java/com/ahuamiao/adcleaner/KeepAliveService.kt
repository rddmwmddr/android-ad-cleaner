package com.ahuamiao.adcleaner

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/** 执行期间的前台服务：引擎在别的 App 的设置页里点开关，本 App 在后台，靠它不被系统回收。 */
class KeepAliveService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_PAUSE) {
            // 通知栏上点「暂停」：不用切回本 App（切过来会挡住引擎正在点的页面），在下一个安全位置停下
            (application as AacApp).worker.execute {
                com.chaquo.python.Python.getInstance().getModule("aac_android.main").callAttr("call", "pause", "[]")
            }
            return START_NOT_STICKY
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "执行状态", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_popup_sync)
            .setContentTitle("安卓去广告正在执行")
            .setContentText("正在逐项关闭，请不要碰手机。要用手机先点「暂停」，等提示音响了再操作")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "暂停",
                PendingIntent.getService(this, 1, Intent(this, KeepAliveService::class.java).setAction(ACTION_PAUSE),
                    PendingIntent.FLAG_IMMUTABLE)).build())
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, notification)
        }
        return START_NOT_STICKY
    }

    companion object {
        const val CHANNEL = "running"
        const val ACTION_PAUSE = "com.ahuamiao.adcleaner.PAUSE"
    }
}
