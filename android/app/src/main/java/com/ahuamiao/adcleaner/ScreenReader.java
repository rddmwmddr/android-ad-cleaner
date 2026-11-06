package com.ahuamiao.adcleaner;

/**
 * 读屏与屏幕尺寸（#623）：由 AndroidScreenReader 实现，ShellServer 只认这个接口。
 * 协议层因此仍然只依赖 java.io，能在 JVM 上单测（ADR-0014）；读屏本身在真机 / 模拟器上验。
 */
public interface ScreenReader {
    /** 第 display 块屏的窗口，与 uiautomator 同格式的 XML；-1 表示所有屏。 */
    String dump(int display) throws Exception;

    /** 第 display 块屏的逻辑尺寸「宽 高」，随旋转。 */
    String size(int display) throws Exception;
}
