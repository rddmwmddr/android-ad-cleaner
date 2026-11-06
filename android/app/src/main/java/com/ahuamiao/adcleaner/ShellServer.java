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
 * （`CLASSPATH=本 APK app_process / com.ahuamiao.adcleaner.ShellServer`），之后 App 的每条命令都走这条流。
 *
 * 不给每条命令单开一条 adb 流：libadb 在对端关流时有竞态，模拟器上 getprop 这类小命令会丢掉全部输出和退出码。
 * 一条流从头用到尾、只开关一次，就碰不到它。Shizuku 也是这个结构（一个 shell 身份的服务进程）。
 *
 * 协议（大端，经 stdin / stdout，stderr 不用）：
 *   请求  int id, byte 类型, int 长度, 内容
 *         类型 1 执行：内容 = int 命令长度, 命令 UTF-8, int stdin 长度, stdin
 *         类型 2 起常驻进程：内容 = int 名字长度, 名字, 命令 UTF-8（输出读掉丢弃）
 *         类型 3 停常驻进程：内容 = 名字
 *   回应  int id, int 退出码, int stdout 长度, stdout, int stderr 长度, stderr（类型 2 / 3 回 0 与空）
 */
public final class ShellServer {
    private static DataOutputStream out;
    private static final Map<String, Process> daemons = new HashMap<>();

    public static void main(String[] args) throws IOException {
        DataInputStream in = new DataInputStream(System.in);
        out = new DataOutputStream(System.out);
        ExecutorService pool = Executors.newCachedThreadPool();
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
        synchronized (daemons) {
            for (Process p : daemons.values()) p.destroy();
        }
        System.exit(0);
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
            }
        } catch (Throwable t) {
            try {
                reply(id, 255, new byte[0], String.valueOf(t).getBytes("UTF-8"));
            } catch (IOException ignored) {
            }
        }
    }

    private static byte[] read(DataInputStream b) throws IOException {
        byte[] data = new byte[b.readInt()];
        b.readFully(data);
        return data;
    }

    private static void run(int id, String cmd, byte[] stdin) throws Exception {
        Process p = new ProcessBuilder("/system/bin/sh", "-c", cmd).start();
        ByteArrayOutputStream o = new ByteArrayOutputStream(), e = new ByteArrayOutputStream();
        Thread to = drain(p.getInputStream(), o), te = drain(p.getErrorStream(), e);
        try (OutputStream os = p.getOutputStream()) {
            if (stdin.length > 0) os.write(stdin);
        } catch (IOException ignored) {
        }
        int code = p.waitFor();
        to.join(5000);
        te.join(5000);
        reply(id, code, o.toByteArray(), e.toByteArray());
    }

    private static void daemon(String name, String cmd) throws IOException {
        synchronized (daemons) {
            Process old = daemons.get(name);
            if (old != null && old.isAlive()) return;
            Process p = new ProcessBuilder("/system/bin/sh", "-c", cmd).start();
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
