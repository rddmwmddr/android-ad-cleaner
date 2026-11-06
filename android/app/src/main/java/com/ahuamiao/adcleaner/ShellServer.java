package com.ahuamiao.adcleaner;

import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * shell 身份的命令服务（#622）：经内置无线调试用一条常驻的 `exec:` 流启动
 * （`CLASSPATH=本 APK app_process / com.ahuamiao.adcleaner.ShellServerMain`），之后 App 的每条命令都走这条流。
 *
 * 不给每条命令单开一条 adb 流：libadb 在对端关流时有竞态，模拟器上 getprop 这类小命令会丢掉全部输出和退出码。
 * 一条流从头用到尾、只开关一次，就碰不到它。Shizuku 也是这个结构（一个 shell 身份的服务进程）。
 *
 * 这个类只用 java.io 与 ProcessBuilder，读屏那部分从 {@link ScreenReader} 注入，
 * 所以整层协议能脱离安卓在 JVM 上单测（ADR-0014）。
 *
 * 协议（大端，经 stdin / stdout，stderr 不用）：
 *   请求  int id, byte 类型, int 长度, 内容
 *         类型 1 执行：内容 = int 命令长度, 命令 UTF-8, int stdin 长度, stdin
 *         类型 2 起常驻进程：内容 = int 名字长度, 名字, 命令 UTF-8（输出读掉丢弃）
 *         类型 3 停常驻进程：内容 = 名字
 *         类型 4 取消执行：内容为空；只对类型 1 有效，杀掉那条命令的进程且不回包
 *         类型 5 读屏：内容 = 屏号（-1 = 所有屏），回与 uiautomator 同格式的 XML（节点带 display-id）
 *         类型 6 屏幕尺寸：内容 = 屏号，回「宽 高」（随旋转）
 *   回应  int id, int 退出码, int stdout 长度, stdout, int stderr 长度, stderr（类型 2 / 3 / 4 回 0 与空）
 */
public final class ShellServer {
    /** 安卓上的 sh；单测在开发机上跑时指到本机 sh（`ShellServerTest` 的 @BeforeClass）。 */
    static String shell = "/system/bin/sh";
    /** 读屏：ShellServerMain 装 Android 实现，单测装假的。null 表示这个进程没有读屏能力。 */
    static volatile ScreenReader reader;
    /** 装读屏时失败的原因：把「读屏起不来」的原话回给客户端，别让它只剩一句「读不到」。 */
    static volatile String readerError;

    private static DataOutputStream out;
    private static final Map<String, Process> daemons = new HashMap<>();
    /** 正在跑的执行：取消要按 id 找到进程。daemons 不在里面（类型 4 对常驻进程无效）。 */
    private static final Map<Integer, Process> running = new HashMap<>();

    /** 协议循环。参数化输入输出只为脱离 adb 做单测。 */
    static void serve(InputStream stdin, OutputStream stdout) throws IOException {
        DataInputStream in = new DataInputStream(stdin);
        out = new DataOutputStream(stdout);
        ExecutorService pool = Executors.newCachedThreadPool(r -> {
            Thread t = new Thread(r);
            t.setDaemon(true);
            return t;
        });
        reply(0, 0, new byte[0], "ready".getBytes("UTF-8"));        // 起来了：App 等到这一条才发命令
        while (true) {
            int id;
            try {
                id = in.readInt();
            } catch (IOException eof) {
                break;                                                // App 那头关了流：退出，常驻进程一并结束
            }
            byte type = in.readByte();
            byte[] body = new byte[in.readInt()];
            in.readFully(body);
            pool.execute(() -> handle(id, type, body));
        }
        shutdown();
    }

    private static void shutdown() {
        synchronized (daemons) {
            for (Process p : daemons.values()) p.destroy();
            daemons.clear();
        }
        synchronized (running) {
            for (Process p : running.values()) p.destroy();
            running.clear();
        }
    }

    private static void handle(int id, byte type, byte[] body) {
        try {
            DataInputStream b = new DataInputStream(new java.io.ByteArrayInputStream(body));
            if (type == 1) {
                String cmd = new String(read(b), "UTF-8");
                byte[] stdin = read(b);
                run(id, cmd, stdin);
            } else if (type == 2) {
                String name = new String(read(b), "UTF-8");
                byte[] rest = new byte[b.available()];
                b.readFully(rest);
                daemon(name, new String(rest, "UTF-8"));
                reply(id, 0, new byte[0], new byte[0]);
            } else if (type == 3) {
                Process p;
                synchronized (daemons) {
                    p = daemons.remove(new String(body, "UTF-8"));
                }
                if (p != null) p.destroy();
                reply(id, 0, new byte[0], new byte[0]);
            } else if (type == 4) {
                cancel(id);
            } else if (type == 5) {
                dumpScreen(id, displayArg(body));
            } else if (type == 6) {
                replySize(id, displayArg(body));
            }
        } catch (Throwable t) {
            try {
                reply(id, 255, new byte[0], String.valueOf(t).getBytes("UTF-8"));
            } catch (IOException ignored) {
            }
        }
    }

    private static int displayArg(byte[] body) {
        return Integer.parseInt(new String(body, java.nio.charset.StandardCharsets.UTF_8).trim());
    }

    private static ScreenReader screen() {
        ScreenReader r = reader;
        if (r == null) throw new IllegalStateException(readerError == null ? "这个进程没有读屏能力" : readerError);
        return r;
    }

    private static void dumpScreen(int id, int display) throws Exception {
        reply(id, 0, screen().dump(display).getBytes("UTF-8"), new byte[0]);
    }

    private static void replySize(int id, int display) throws Exception {
        reply(id, 0, screen().size(display).getBytes("UTF-8"), new byte[0]);
    }

    private static byte[] read(DataInputStream b) throws IOException {
        byte[] data = new byte[b.readInt()];
        b.readFully(data);
        return data;
    }

    private static void run(int id, String cmd, byte[] stdin) throws Exception {
        Process p = new ProcessBuilder(shell, "-c", cmd).start();
        synchronized (running) {
            running.put(id, p);
        }
        ByteArrayOutputStream o = new ByteArrayOutputStream(), e = new ByteArrayOutputStream();
        Thread to = drain(p.getInputStream(), o), te = drain(p.getErrorStream(), e);
        try (OutputStream os = p.getOutputStream()) {
            if (stdin.length > 0) os.write(stdin);
        } catch (IOException ignored) {
        }
        int code = p.waitFor();
        if (release(id)) return;                                     // 取消过：不回包，也不必再等残留输出
        to.join(5000);
        te.join(5000);
        reply(id, code, o.toByteArray(), e.toByteArray());
    }

    /**
     * 命令结束：把它摘下。返回 true 表示取消者已经先摘走了，这条不该再回包
     * （回包会和取消撞同一个 id，而 App 侧早已把这条 id 从待回队列里删掉）。
     */
    private static boolean release(int id) {
        synchronized (running) {
            return running.remove(id) == null;
        }
    }

    /**
     * 取消一条执行。只认「执行」：常驻进程由类型 3 停。
     * `destroy()` 只发给直属的 sh；`sh -c "a | b"` 的子进程靠管道关闭自行退出，
     * 安卓没有 Java 9 的 ProcessHandle，剩下的短命子进程不追。
     */
    private static void cancel(int id) {
        Process p;
        synchronized (running) {
            p = running.remove(id);
        }
        if (p != null) p.destroy();
    }

    private static void daemon(String name, String cmd) throws IOException {
        synchronized (daemons) {
            Process old = daemons.get(name);
            if (old != null && old.isAlive()) return;
            Process p = new ProcessBuilder(shell, "-c", cmd).start();
            drain(p.getInputStream(), null);
            drain(p.getErrorStream(), null);
            p.getOutputStream().close();
            daemons.put(name, p);
        }
    }

    private static Thread drain(InputStream s, ByteArrayOutputStream into) {
        Thread t = new Thread(() -> {
            byte[] buf = new byte[8192];
            try {
                int n;
                while ((n = s.read(buf)) > 0) {
                    if (into != null) into.write(buf, 0, n);
                }
            } catch (IOException ignored) {
            }
        });
        t.setDaemon(true);
        t.start();
        return t;
    }

    private static void reply(int id, int code, byte[] o, byte[] e) throws IOException {
        synchronized (ShellServer.class) {
            out.writeInt(id);
            out.writeInt(code);
            out.writeInt(o.length);
            out.write(o);
            out.writeInt(e.length);
            out.write(e);
            out.flush();
        }
    }
}
