package com.ahuamiao.adcleaner;

import android.os.Looper;

/**
 * 命令服务的进程入口（`app_process` 起的那个类）。
 *
 * 与 ShellServer 分开：这一层要碰 Android（主线程 Looper、系统 Context、读屏），
 * ShellServer 自己保持纯 java.io，好让协议在 JVM 上单测（ADR-0014）。
 *
 * 读屏的回调走主线程 Looper，所以主线程只转 Looper，协议循环另起一条线程。
 */
public final class ShellServerMain {
    public static void main(String[] args) throws Exception {
        Looper.prepareMainLooper();
        try {
            AndroidScreenReader.prepare();      // systemMain 要求调用线程有 Looper
            ShellServer.reader = new AndroidScreenReader();
        } catch (Throwable t) {
            // 读屏起不来不该拖垮命令通道：类型 5 / 6 回 255 与这句话，其余照常
            ShellServer.readerError = String.valueOf(t);
        }
        Thread worker = new Thread(() -> {
            try {
                ShellServer.serve(System.in, System.out);
            } catch (Exception ignored) {
            }
            System.exit(0);
        }, "serve");
        worker.start();
        Looper.loop();
    }
}
