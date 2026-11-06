package com.ahuamiao.adcleaner;

import android.annotation.SuppressLint;
import android.content.AttributionSource;
import android.content.Context;
import android.content.ContextWrapper;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;

/**
 * 后台屏：不在 App 进程里跑，经 Shizuku 以 shell 身份启动
 * （`CLASSPATH=本 APK app_process / com.ahuamiao.adcleaner.Vd 宽 高 密度`），常驻到被杀。
 *
 * 建一块与主屏同尺寸同密度的虚拟屏，打印「DISPLAY 编号 flags=…」后常驻。做法同 scrcpy 的 NewDisplayCapture：
 * 用包名伪装成 com.android.shell 的 Context 建 DisplayManager（DisplayManagerService 核对包名与 uid）。
 * 标记逐级降级：有的系统不给 shell 建可信屏。
 * - OWN_FOCUS + STEAL_TOP_FOCUS_DISABLED：后台屏有自己的焦点，又不抢主屏的（否则主屏输入框弹不出键盘）；
 * - OWN_DISPLAY_GROUP：与主屏分开亮灭，要每 4 秒 userActivity 续亮，否则会睡、画面停住；
 * - ALWAYS_UNLOCKED：主屏锁了，后台屏照样能开页面。
 * 两个坑来自 Mika（github.com/wangzan101/mika，Apache-2.0）的做法。
 */
@SuppressLint({"NewApi", "WrongConstant"})
public final class Vd {
    static final int PUBLIC = 1, OWN_CONTENT_ONLY = 1 << 3, SUPPORTS_TOUCH = 1 << 6, ROTATES = 1 << 7, DESTROY = 1 << 8,
            TRUSTED = 1 << 10, OWN_GROUP = 1 << 11, ALWAYS_UNLOCKED = 1 << 12, NO_TOUCH_FEEDBACK = 1 << 13,
            OWN_FOCUS = 1 << 14, STEAL_TOP_FOCUS_DISABLED = 1 << 16;

    public static void main(String[] a) throws Exception {
        int w = Integer.parseInt(a[0]), h = Integer.parseInt(a[1]), dpi = Integer.parseInt(a[2]);
        Looper.prepareMainLooper();
        Class<?> at = Class.forName("android.app.ActivityThread");
        Object thread = at.getMethod("systemMain").invoke(null);
        Context sys = (Context) at.getMethod("getSystemContext").invoke(thread);
        Context fake = new ContextWrapper(sys) {
            @Override public String getPackageName() { return "com.android.shell"; }
            @Override public String getOpPackageName() { return "com.android.shell"; }
            @Override public AttributionSource getAttributionSource() {
                return new AttributionSource.Builder(2000).setPackageName("com.android.shell").build();
            }
            @Override public Context getApplicationContext() { return this; }
        };
        Constructor<DisplayManager> c = DisplayManager.class.getDeclaredConstructor(Context.class);
        c.setAccessible(true);
        DisplayManager dm = c.newInstance(fake);

        // 画面要有人取走，否则缓冲区占满后屏上的 App 画不出下一帧
        HandlerThread drain = new HandlerThread("drain");
        drain.start();
        ImageReader reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2);
        reader.setOnImageAvailableListener(r -> {
            Image im = r.acquireLatestImage();
            if (im != null) im.close();
        }, new Handler(drain.getLooper()));

        int base = PUBLIC | OWN_CONTENT_ONLY | SUPPORTS_TOUCH | ROTATES | DESTROY;
        int trusted = base | NO_TOUCH_FEEDBACK | TRUSTED | OWN_GROUP | ALWAYS_UNLOCKED | OWN_FOCUS | STEAL_TOP_FOCUS_DISABLED;
        int[] tries = {trusted, trusted & ~STEAL_TOP_FOCUS_DISABLED,
                trusted & ~(STEAL_TOP_FOCUS_DISABLED | OWN_FOCUS | ALWAYS_UNLOCKED | OWN_GROUP), base};
        VirtualDisplay vd = null;
        int used = 0;
        for (int f : tries) {
            try {
                vd = dm.createVirtualDisplay("aac-bg", w, h, dpi, reader.getSurface(), f);
                used = f;
                break;
            } catch (Throwable e) {
                System.out.println("flags 0x" + Integer.toHexString(f) + " 失败: " + e);
            }
        }
        if (vd == null) {
            System.out.println("DISPLAY -1");
            System.exit(1);
        }
        final int id = vd.getDisplay().getDisplayId();
        System.out.println("DISPLAY " + id + " flags=0x" + Integer.toHexString(used));
        System.out.flush();

        IBinder b = (IBinder) Class.forName("android.os.ServiceManager").getMethod("getService", String.class).invoke(null, "power");
        final Object power = Class.forName("android.os.IPowerManager$Stub").getMethod("asInterface", IBinder.class).invoke(null, b);
        Method ua = null;
        for (Method m : power.getClass().getMethods())
            if (m.getName().equals("userActivity") && m.getParameterTypes().length == 4 && m.getParameterTypes()[0] == int.class) ua = m;
        final Method userActivity = ua;
        final Handler main = new Handler(Looper.getMainLooper());
        main.post(new Runnable() {
            public void run() {
                try {
                    if (userActivity != null) userActivity.invoke(power, id, SystemClock.uptimeMillis(), 2, 0);
                } catch (Throwable ignored) {
                }
                main.postDelayed(this, 4000);
            }
        });
        Looper.loop();
    }
}
