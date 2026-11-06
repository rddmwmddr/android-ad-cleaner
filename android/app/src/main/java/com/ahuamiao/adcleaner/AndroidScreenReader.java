package com.ahuamiao.adcleaner;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.annotation.SuppressLint;
import android.app.UiAutomation;
import android.content.Context;
import android.graphics.Rect;
import android.os.HandlerThread;
import android.os.Looper;
import android.util.SparseArray;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.List;

/**
 * 以 shell 身份读屏（#623）：自己连 UiAutomation，读所有屏的窗口。
 *
 * 取代原来 uiautomator2 的 u2.jar 读屏服务——那个服务在 9008 端口对局域网开放、无鉴权，
 * 同一个 Wi-Fi 下的设备能读屏、代点按。这里只走命令服务的 stdin/stdout，不开任何端口。
 */
@SuppressLint({"NewApi", "PrivateApi", "BlockedPrivateApi", "SoonBlockedPrivateApi", "DiscouragedPrivateApi"})
public final class AndroidScreenReader implements ScreenReader {
    private static Context system;
    private UiAutomation uia;

    /** 在有 Looper 的主线程上取系统 Context：`ActivityThread.systemMain` 要求调用线程有 Looper。 */
    public static void prepare() throws Exception {
        Class<?> at = Class.forName("android.app.ActivityThread");
        Object thread = at.getMethod("systemMain").invoke(null);
        system = (Context) at.getMethod("getSystemContext").invoke(thread);
    }

    /** 只有一块 UiAutomation 连接：并发的读屏请求在这里排队。 */
    @Override
    public synchronized String dump(int display) throws Exception {
        try {
            return dumpAll(display);
        } catch (Throwable t) {
            uia = null;                 // 连接可能已经失效（被别的 UiAutomation 抢走、无障碍重挂）：下次重连
            throw t;
        }
    }

    @Override
    public String size(int display) throws Exception {
        Object global = Class.forName("android.hardware.display.DisplayManagerGlobal")
                .getMethod("getInstance").invoke(null);
        Object info = global.getClass().getMethod("getDisplayInfo", int.class).invoke(global, display);
        int w = info.getClass().getField("logicalWidth").getInt(info);
        int h = info.getClass().getField("logicalHeight").getInt(info);
        return w + " " + h;
    }

    private String dumpAll(int display) throws Exception {
        UiAutomation u = uia();
        StringBuilder sb = new StringBuilder(
                "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation=\"0\">");
        SparseArray<List<AccessibilityWindowInfo>> all = u.getWindowsOnAllDisplays();
        for (int i = 0; i < all.size(); i++) {
            int id = all.keyAt(i);
            if (display >= 0 && id != display) continue;
            for (AccessibilityWindowInfo w : all.valueAt(i)) {
                AccessibilityNodeInfo root = w.getRoot();
                if (root != null) node(sb, root, 0, id, 0);
            }
        }
        return sb.append("</hierarchy>").toString();
    }

    private UiAutomation uia() throws Exception {
        if (uia != null) return uia;
        if (system == null) throw new IllegalStateException("拿不到系统 Context");
        HandlerThread handler = new HandlerThread("uia");
        handler.start();
        Object connection = Class.forName("android.app.UiAutomationConnection")
                .getDeclaredConstructor().newInstance();
        Class<?> iface = Class.forName("android.app.IUiAutomationConnection");
        UiAutomation u = null;
        // 构造函数各版本不同：安卓 14 起是 (Context, 连接)，之前是 (Looper, 连接)
        for (Constructor<?> c : UiAutomation.class.getDeclaredConstructors()) {
            Class<?>[] p = c.getParameterTypes();
            if (p.length == 2 && p[1] == iface) {
                c.setAccessible(true);
                u = (UiAutomation) c.newInstance(p[0] == Looper.class ? handler.getLooper() : system, connection);
                break;
            }
        }
        if (u == null) throw new IllegalStateException("找不到 UiAutomation 构造函数");
        Method connect;
        try {
            connect = UiAutomation.class.getDeclaredMethod("connect", int.class);
            connect.setAccessible(true);
            connect.invoke(u, 1);          // FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES：不踢掉用户开着的无障碍服务
        } catch (NoSuchMethodException e) {
            connect = UiAutomation.class.getDeclaredMethod("connect");
            connect.setAccessible(true);
            connect.invoke(u);
        }
        AccessibilityServiceInfo info = u.getServiceInfo();
        info.flags |= AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
                | AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
                | AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;
        u.setServiceInfo(info);
        // 刚连上时窗口列表还是空的（模拟器实测第一次读 0 个节点）：等它看见窗口，最多 3 秒
        for (int i = 0; i < 30 && !seesWindow(u); i++) Thread.sleep(100);
        uia = u;
        return u;
    }

    private static boolean seesWindow(UiAutomation u) {
        SparseArray<List<AccessibilityWindowInfo>> all = u.getWindowsOnAllDisplays();
        for (int k = 0; k < all.size(); k++)
            for (AccessibilityWindowInfo w : all.valueAt(k))
                if (w.getRoot() != null) return true;
        return false;
    }

    /** 与 uiautomator 的 dump 同格式（引擎按这些属性读）；每个节点带 display-id，后台屏按它过滤。 */
    private static void node(StringBuilder sb, AccessibilityNodeInfo n, int index, int display, int depth) {
        Rect r = new Rect();
        n.getBoundsInScreen(r);
        sb.append("<node index=\"").append(index).append('"');
        attr(sb, "text", n.getText());
        attr(sb, "resource-id", n.getViewIdResourceName());
        attr(sb, "class", n.getClassName());
        attr(sb, "package", n.getPackageName());
        attr(sb, "content-desc", n.getContentDescription());
        flag(sb, "checkable", n.isCheckable());
        flag(sb, "checked", n.isChecked());
        flag(sb, "clickable", n.isClickable());
        flag(sb, "enabled", n.isEnabled());
        flag(sb, "focusable", n.isFocusable());
        flag(sb, "focused", n.isFocused());
        flag(sb, "scrollable", n.isScrollable());
        flag(sb, "long-clickable", n.isLongClickable());
        flag(sb, "password", n.isPassword());
        flag(sb, "selected", n.isSelected());
        flag(sb, "visible-to-user", n.isVisibleToUser());
        sb.append(" bounds=\"[").append(r.left).append(',').append(r.top).append("][")
                .append(r.right).append(',').append(r.bottom).append("]\" display-id=\"").append(display).append('"');
        int count = depth < 50 ? n.getChildCount() : 0;
        if (count == 0) {
            sb.append(" />");
            return;
        }
        sb.append('>');
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo c = n.getChild(i);
            if (c != null) node(sb, c, i, display, depth + 1);
        }
        sb.append("</node>");
    }

    private static void attr(StringBuilder sb, String name, CharSequence value) {
        sb.append(' ').append(name).append("=\"");
        if (value != null) {
            for (int i = 0; i < value.length(); i++) {
                char ch = value.charAt(i);
                switch (ch) {
                    case '&': sb.append("&amp;"); break;
                    case '<': sb.append("&lt;"); break;
                    case '>': sb.append("&gt;"); break;
                    case '"': sb.append("&quot;"); break;
                    case '\n': sb.append("&#10;"); break;
                    case '\r': sb.append("&#13;"); break;
                    default:
                        if (ch >= 0x20 || ch == '\t') sb.append(ch);   // XML 1.0 不允许的控制字符丢掉
                }
            }
        }
        sb.append('"');
    }

    private static void flag(StringBuilder sb, String name, boolean value) {
        sb.append(' ').append(name).append("=\"").append(value).append('"');
    }
}
