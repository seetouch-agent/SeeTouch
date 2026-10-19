package com.seetouch.app.task

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.TimeUnit

class ConfirmationGateTest {
    @Test fun lateApprovalIsAlwaysRejectedAndRecordedAsTimeout() {
        var now = 0L
        val gate = ConfirmationGate(60) { now }
        now = TimeUnit.SECONDS.toNanos(60)
        gate.respond(true)
        val result = JSONObject(gate.await())
        assertFalse(result.getBoolean("approved"))
        assertEquals("timeout", result.getString("choice"))
    }
    @Test fun aDeniedOrInterruptedConfirmationCannotBeApprovedAgain() {
        val gate = ConfirmationGate(60) { 0L }
        assertTrue(gate.respond(false))
        assertFalse(gate.respond(true))
        assertEquals("deny", JSONObject(gate.await()).getString("choice"))
        val interrupted = ConfirmationGate(60) { 0L }
        interrupted.cancel("interrupted")
        assertFalse(interrupted.respond(true))
        assertFalse(JSONObject(interrupted.await()).getBoolean("approved"))
    }
}
