package com.seetouch.app.overlay

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutionException
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

class OverlayOperationGateTest {
    @Test fun backgroundOperationDoesNotNeedFramesAndRestoresBothWindowsOnFailure() {
        val ui = LinkedBlockingQueue<() -> Unit>()
        val events = mutableListOf<String>()
        val progress = OverlayVisibility().apply { requested = true }
        val entry = OverlayVisibility().apply { requested = true }
        val gate = OverlayOperationGate({ ui.add(it) }, { ui.add(it) }, { false })
        val result = CompletableFuture.supplyAsync {
            gate.run(hide = {
                progress.beginOperation(); entry.beginOperation(); events.add("removed both windows")
            }, restore = {
                progress.endOperation(); entry.endOperation(); events.add("restored both windows")
            }) {
                assertFalse(progress.visible); assertFalse(entry.visible)
                events.add("screenshot")
                throw IllegalStateException("capture failed")
            }
        }
        ui.poll(1, TimeUnit.SECONDS)!!.invoke() // UI removal; no vsync or render loop.
        assertEquals(listOf("removed both windows"), events)
        assertFalse(result.isDone)
        ui.poll(1, TimeUnit.SECONDS)!!.invoke() // Delayed acknowledgement after removal.
        try { result.get(1, TimeUnit.SECONDS); fail("capture should fail") }
        catch (error: ExecutionException) { assertEquals("capture failed", error.cause!!.message) }
        ui.poll(1, TimeUnit.SECONDS)!!.invoke()
        assertTrue(progress.visible); assertTrue(entry.visible)
        assertEquals(listOf("removed both windows", "screenshot", "restored both windows"), events)
    }

    @Test fun lateUiCallbacksAfterTimeoutCannotHideWindowsOrDispatchAnOperation() {
        val ui = LinkedBlockingQueue<() -> Unit>()
        val state = OverlayVisibility().apply { requested = true }
        val gate = OverlayOperationGate({ ui.add(it) }, { ui.add(it) }, { false }, timeoutMillis = 10)
        val result = CompletableFuture.supplyAsync {
            gate.run(hide = { state.beginOperation() }, restore = { state.endOperation() }) {
                fail("operation after overlay timeout")
            }
        }
        try { result.get(1, TimeUnit.SECONDS); fail("UI queue has not run") }
        catch (error: ExecutionException) { assertTrue(error.cause!!.message!!.contains("Timed out removing")) }
        while (ui.isNotEmpty()) ui.poll()!!.invoke()
        assertTrue(state.visible)
    }
}
