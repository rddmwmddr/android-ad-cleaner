package com.ahuamiao.adcleaner

import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class UpdateIdentityTest {
    private val installed = UpdateIdentity("com.ahuamiao.adcleaner", "0.4.1", 41, setOf("release-key"))
    private val candidate = installed.copy(version = "0.4.2", code = 42)

    @Test fun acceptsSameSignerUpgrade() {
        assertNull(installed.rejection(candidate, "0.4.2"))
    }

    @Test fun refusesDifferentAppSignerAndDowngrade() {
        listOf(
            candidate.copy(packageName = "another.app"),
            candidate.copy(signers = setOf("debug-key")),
            candidate.copy(signers = emptySet()),
            candidate.copy(code = 41),
            candidate.copy(version = "0.4.3"),
        ).forEach { assertNotNull(installed.rejection(it, "0.4.2")) }
    }
}
