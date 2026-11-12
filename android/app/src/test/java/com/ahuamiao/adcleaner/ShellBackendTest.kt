package com.ahuamiao.adcleaner

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ShellBackendTest {
    @Test fun prefersShizukuWheneverItIsReady() {
        assertEquals(ShellBackend.Shizuku, ShellBackend.pick(shizukuReady = true, wirelessConnected = true))
        assertEquals(ShellBackend.Shizuku, ShellBackend.pick(shizukuReady = true, wirelessConnected = false))
    }

    @Test fun fallsBackToConnectedWireless() {
        assertEquals(ShellBackend.Wireless, ShellBackend.pick(shizukuReady = false, wirelessConnected = true))
    }

    @Test fun bothMissingExplainsWithoutALibraryException() {
        val reason = (ShellBackend.pick(shizukuReady = false, wirelessConnected = false) as? ShellBackend.Missing)?.reason
        assertNotNull(reason)
        assertEquals(ShellBackend.NO_BACKEND, reason)
        assertTrue(reason!!.startsWith("命令服务不可用："))
        assertTrue(reason.contains("Shizuku"))
        assertTrue(reason.contains("授权"))          // ready() 同时含授权检查，不能只说「没在运行」
        assertTrue(reason.contains("无线调试"))
        assertFalse(reason.contains("IllegalStateException"))
    }

    /** 守卫：只走无线调试的路径不该把问题推到用户没装的 Shizuku 上。 */
    @Test fun wirelessOnlyPathNamesOnlyWireless() {
        assertTrue(ShellBackend.NO_WIRELESS.startsWith("命令服务不可用："))
        assertTrue(ShellBackend.NO_WIRELESS.contains("无线调试"))
        assertFalse(ShellBackend.NO_WIRELESS.contains("Shizuku"))
    }

    @Test fun aMissingBackendRefusesToOpenTheStream() {
        var opened = false
        val e = assertThrows(ShellUnavailable::class.java) {
            openWhenReady<Unit>(ready = false, connect = { false }, open = { opened = true })
        }
        assertEquals(ShellBackend.NO_WIRELESS, e.text)
        assertFalse(opened)
    }

    @Test fun theStreamOpensOnceAConnectionSucceeds() {
        assertEquals("stream", openWhenReady(ready = false, connect = { true }, open = { "stream" }))
    }

    @Test fun anAlreadyConnectedBackendIsNotProbedAgain() {
        assertEquals("stream", openWhenReady(ready = true, connect = { error("不该再试连") }, open = { "stream" }))
    }

    @Test fun theMissingBackendSentenceReachesTheUserVerbatim() {
        assertEquals(ShellBackend.NO_BACKEND, failureText(ShellUnavailable(ShellBackend.NO_BACKEND)))
    }

    /** 别的失败照旧带前缀：库异常名留在后面，但用户能认出这是命令服务的问题。 */
    @Test fun anyOtherFailureKeepsThePrefix() {
        assertEquals(
            "命令服务不可用：java.lang.IllegalStateException: connect() must be called first",
            failureText(IllegalStateException("connect() must be called first")),
        )
    }
}
