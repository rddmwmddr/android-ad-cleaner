package com.ahuamiao.adcleaner.ui

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** #889：更新面板读的字段怎么从快照里取。纯派生，不需要 Android 运行时。 */
class UpdateViewTest {
    @Test fun versionAndNotesComeFromTheSnapshot() {
        val view = UpdateView.of(
            JSONObject().put("state", "available").put("version", "0.4.2")
                .put("notes_url", "https://example.test/releases/tag/v0.4.2").put("source", "github")
        )
        assertEquals(NewVersion("0.4.2", "https://example.test/releases/tag/v0.4.2"), view.version)
        assertEquals("github", view.source)
        assertEquals("available", view.state.optString("state"))
    }

    @Test fun snapshotWithoutVersionShowsNoNewVersionAndLeavesTheChosenSourceAlone() {
        val view = UpdateView.of(JSONObject().put("state", "current"))
        assertNull(view.version)
        // 消息在前：JUnit 4.13 另有 assertNull(String, Object)，写成 (值, 说明) 会被解析反。
        assertNull("没有 source 时调用方要保持用户选的渠道，不能重置成默认值", view.source)
    }
}
