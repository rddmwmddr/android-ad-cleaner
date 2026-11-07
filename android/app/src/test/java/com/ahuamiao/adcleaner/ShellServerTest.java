package com.ahuamiao.adcleaner;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.PipedInputStream;
import java.io.PipedOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * 协议层（ShellServer 只用 java.io 与 ProcessBuilder，不碰 Android）：帧、stdout / stderr 分开、
 * 退出码、并发编号、取消。连不上 adbd 的连接 / 重连留给真机（#622）。
 */
public class ShellServerTest {
    private static final int RUN = 1, DAEMON = 2, STOP = 3, CANCEL = 4, DUMP = 5, SIZE = 6;

    @org.junit.BeforeClass
    public static void useTheHostShell() {
        ShellServer.shell = "/bin/sh";              // 安卓上是 /system/bin/sh，开发机上换成同一个语义的本机 sh
    }

    private PipedOutputStream toServer;
    private DataInputStream fromServer;
    private Thread serving;
    private final BlockingQueue<Frame> frames = new LinkedBlockingQueue<>();

    private static final class Frame {
        final int id, code;
        final byte[] out, err;

        Frame(int id, int code, byte[] out, byte[] err) {
            this.id = id;
            this.code = code;
            this.out = out;
            this.err = err;
        }

        String outText() {
            return new String(out, StandardCharsets.UTF_8);
        }

        String errText() {
            return new String(err, StandardCharsets.UTF_8);
        }
    }

    @Before
    public void start() throws Exception {
        ShellServer.reader = null;              // 静态字段：每例从「没有读屏能力」开始，自己按需装
        toServer = new PipedOutputStream();
        PipedInputStream serverIn = new PipedInputStream(toServer, 1 << 16);
        PipedOutputStream serverOut = new PipedOutputStream();
        fromServer = new DataInputStream(new PipedInputStream(serverOut, 1 << 16));

        serving = new Thread(() -> {
            try {
                ShellServer.serve(serverIn, serverOut);
            } catch (IOException ignored) {
            }
        });
        serving.setDaemon(true);
        serving.start();

        Thread reading = new Thread(() -> {
            try {
                while (true) frames.put(read());
            } catch (Exception ignored) {
            }
        });
        reading.setDaemon(true);
        reading.start();

        Frame ready = next(5000);
        assertNotNull("起来后先报一条 ready", ready);
        assertEquals(0, ready.id);
        assertEquals("ready", ready.errText());
    }

    @After
    public void stop() throws Exception {
        toServer.close();       // 服务端读到 EOF：退出并清掉常驻进程
        // 等它真的退出再跑下一例：running / daemons 是静态的，旧 serve 的 shutdown() 会误伤新用例
        serving.join(5000);
    }

    // ----- 协议工具 -----

    private Frame read() throws IOException {
        int id = fromServer.readInt();
        int code = fromServer.readInt();
        byte[] o = new byte[fromServer.readInt()];
        fromServer.readFully(o);
        byte[] e = new byte[fromServer.readInt()];
        fromServer.readFully(e);
        return new Frame(id, code, o, e);
    }

    private Frame next(long ms) throws InterruptedException {
        return frames.poll(ms, TimeUnit.MILLISECONDS);
    }

    private void send(int id, int type, byte[] body) throws IOException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        DataOutputStream d = new DataOutputStream(buffer);
        d.writeInt(id);
        d.writeByte(type);
        d.writeInt(body.length);
        d.write(body);
        d.flush();
        toServer.write(buffer.toByteArray());
        toServer.flush();
    }

    private static byte[] execBody(String cmd, String stdin) throws IOException {
        byte[] c = cmd.getBytes(StandardCharsets.UTF_8);
        byte[] s = stdin.getBytes(StandardCharsets.UTF_8);
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        DataOutputStream d = new DataOutputStream(buffer);
        d.writeInt(c.length);
        d.write(c);
        d.writeInt(s.length);
        d.write(s);
        d.flush();
        return buffer.toByteArray();
    }

    private static byte[] daemonBody(String name, String cmd) throws IOException {
        byte[] n = name.getBytes(StandardCharsets.UTF_8);
        byte[] c = cmd.getBytes(StandardCharsets.UTF_8);
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        DataOutputStream d = new DataOutputStream(buffer);
        d.writeInt(n.length);
        d.write(n);
        d.write(c);
        d.flush();
        return buffer.toByteArray();
    }

    // ----- 用例 -----

    @Test
    public void stdout_and_stderr_stay_apart_and_the_exit_code_comes_back() throws Exception {
        send(1, RUN, execBody("echo out; echo err >&2; exit 3", ""));
        Frame f = next(5000);
        assertNotNull(f);
        assertEquals(1, f.id);
        assertEquals(3, f.code);
        assertEquals("out\n", f.outText());
        assertEquals("err\n", f.errText());
    }

    @Test
    public void stdin_reaches_the_command() throws Exception {
        send(2, RUN, execBody("cat", "hello"));
        Frame f = next(5000);
        assertNotNull(f);
        assertEquals("hello", f.outText());
    }

    @Test
    public void concurrent_commands_reply_under_their_own_id() throws Exception {
        send(10, RUN, execBody("sleep 0.1; echo ten", ""));
        send(11, RUN, execBody("echo eleven", ""));
        Map<Integer, Frame> got = new HashMap<>();
        for (int i = 0; i < 2; i++) {
            Frame f = next(5000);
            assertNotNull(f);
            got.put(f.id, f);
        }
        assertEquals("ten\n", got.get(10).outText());
        assertEquals("eleven\n", got.get(11).outText());
    }

    @Test
    public void cancel_kills_the_command_and_sends_no_reply() throws Exception {
        // 命令 2 秒后写标记：只看「不回包」证不到真被杀（回包本来就要等到命令结束），
        // 标记出不出来才是可证伪的那一半。
        Path marker = Files.createTempFile("aac-cancel", ".txt");
        Files.delete(marker);
        marker.toFile().deleteOnExit();

        send(20, RUN, execBody("sleep 2; echo done > " + marker, ""));
        Thread.sleep(300);                          // 让它进到「正在跑」
        send(20, CANCEL, new byte[0]);
        assertNull("取消不回包", next(1000));
        Thread.sleep(2500);
        assertFalse("命令应当真的被杀掉，标记不该出现", Files.exists(marker));

        send(21, RUN, execBody("echo alive", ""));  // 取消之后服务照常可用
        Frame f = next(5000);
        assertNotNull(f);
        assertEquals(21, f.id);
        assertEquals("alive\n", f.outText());
    }

    @Test
    public void cancel_does_not_touch_a_daemon() throws Exception {
        Path pidFile = Files.createTempFile("aac-daemon", ".pid");
        pidFile.toFile().deleteOnExit();
        send(30, DAEMON, daemonBody("t", "echo $$ > " + pidFile + "; sleep 30"));
        Frame started = next(5000);
        assertNotNull(started);
        assertEquals(30, started.id);

        String pid = "";
        long deadline = System.currentTimeMillis() + 5000;
        while (pid.isEmpty() && System.currentTimeMillis() < deadline) {
            pid = new String(Files.readAllBytes(pidFile), StandardCharsets.UTF_8).trim();
            Thread.sleep(50);
        }
        assertFalse("常驻进程应当已经起来", pid.isEmpty());

        send(30, CANCEL, new byte[0]);              // 类型 4 只对「执行」有效
        Thread.sleep(300);
        // 单测对着 android.jar 编译，没有 ProcessHandle
        assertEquals("常驻进程不该被取消掉", 0, new ProcessBuilder("kill", "-0", pid).start().waitFor());

        send(31, STOP, "t".getBytes(StandardCharsets.UTF_8));
        Frame stopped = next(5000);
        assertNotNull(stopped);
        assertEquals(31, stopped.id);
    }

    // ----- 读屏（#623）-----

    /** 读屏不在协议层实现：换一个假的，协议照样按类型 5 / 6 收发。 */
    private static ScreenReader reader(String dump, String size) {
        return new ScreenReader() {
            @Override
            public String dump(int display) {
                return dump + display;
            }

            @Override
            public String size(int display) {
                return size;
            }
        };
    }

    @Test
    public void dump_and_size_are_served_by_the_reader() throws Exception {
        ShellServer.reader = reader("", "1080 2400");
        send(40, DUMP, "3".getBytes(StandardCharsets.UTF_8));
        Frame f = next(5000);
        assertNotNull(f);
        assertEquals(40, f.id);
        assertEquals(0, f.code);
        assertEquals("3", f.outText());         // 假读屏把屏号回显出来：屏号确实传到了实现里
        assertEquals("", f.errText());

        send(41, SIZE, "3".getBytes(StandardCharsets.UTF_8));
        Frame g = next(5000);
        assertNotNull(g);
        assertEquals(41, g.id);
        assertEquals("1080 2400", g.outText());
    }

    @Test
    public void a_reader_failure_comes_back_with_the_servers_own_words() throws Exception {
        ShellServer.reader = new ScreenReader() {
            @Override
            public String dump(int display) {
                throw new IllegalStateException("读屏连接被别的无障碍服务占用");
            }

            @Override
            public String size(int display) {
                return "";
            }
        };
        send(42, DUMP, "0".getBytes(StandardCharsets.UTF_8));
        Frame f = next(5000);
        assertNotNull(f);
        assertEquals(255, f.code);
        assertTrue("根因要回给客户端，不能只剩一句「读不到」", f.errText().contains("读屏连接被别的无障碍服务占用"));
    }

    @Test
    public void without_a_reader_the_command_channel_still_works() throws Exception {
        send(43, DUMP, "0".getBytes(StandardCharsets.UTF_8));
        Frame f = next(5000);
        assertNotNull(f);
        assertEquals(43, f.id);
        assertEquals(255, f.code);
        assertTrue(f.errText().contains("没有读屏"));

        send(44, RUN, execBody("echo alive", ""));
        Frame g = next(5000);
        assertNotNull(g);
        assertEquals("alive\n", g.outText());   // 读屏缺失不该拖垮命令通道
    }

    @Test
    public void cancelling_one_id_does_not_eat_another_reply() throws Exception {
        // 类型 4 与 5 / 6 是两张码：取消回的是「不回包」，读屏回的是正文。
        // 这条守住编号不撞车——撞了的话，取消会把后一条读屏的应答吃掉。
        ShellServer.reader = reader("screen-", "1 1");
        send(50, CANCEL, new byte[0]);          // 服务端没有这个 id：什么都不做，也不回包
        send(51, DUMP, "0".getBytes(StandardCharsets.UTF_8));
        Frame f = next(5000);
        assertNotNull(f);
        assertEquals(51, f.id);
        assertEquals("screen-0", f.outText());
    }
}
