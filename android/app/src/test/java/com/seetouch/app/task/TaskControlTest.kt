package com.seetouch.app.task

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class TaskControlTest {
    @Test fun pauseBlocksNewDispatchAndRapidResumeInvalidatesOldRevision() {
        val control = TaskControl().apply { start() }
        val original = control.revision
        var actions = 0
        repeat(10) {
            assertTrue(control.transition(TaskStatus.PAUSED))
            assertBlocked { control.dispatch(original) { actions++ } }
            assertTrue(control.transition(TaskStatus.RUNNING))
        }
        assertBlocked { control.dispatch(original) { actions++ } }
        control.dispatch(control.revision) { actions++ }
        assertEquals(1, actions)
    }

    @Test fun stopCannotBeResumedAndBlocksEveryNewOperation() {
        val control = TaskControl().apply { start() }
        assertTrue(control.transition(TaskStatus.STOPPED))
        assertFalse(control.transition(TaskStatus.RUNNING))
        assertFalse(control.transition(TaskStatus.TAKEOVER))
        assertBlocked { control.dispatch(null) { fail("operation after stop") } }
    }

    @Test fun takeoverAndQuestionWaitingBothBlockNativeOperations() {
        val control = TaskControl().apply { start() }
        for (mode in listOf(TaskStatus.TAKEOVER, TaskStatus.WAITING_USER, TaskStatus.PAUSED)) {
            control.transition(mode)
            assertBlocked { control.dispatch(control.revision) { fail("operation while suspended") } }
        }
    }

    @Test fun inFlightGestureCanFinishWhilePauseReturnsWithinOneSecond() {
        val control = TaskControl().apply { start() }
        val dispatched = CountDownLatch(1)
        val gestureFinished = CountDownLatch(1)
        val worker = thread {
            control.dispatch(control.revision) { dispatched.countDown() }
            gestureFinished.await(2, TimeUnit.SECONDS) // Same placement as AccessibilityService's latch.
        }
        assertTrue(dispatched.await(1, TimeUnit.SECONDS))
        val started = System.nanoTime()
        control.transition(TaskStatus.PAUSED)
        assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 1000)
        assertTrue(worker.isAlive)
        assertBlocked { control.dispatch(null) { fail("new gesture after pause") } }
        gestureFinished.countDown()
        worker.join(1000)
        assertFalse(worker.isAlive)
    }

    @Test fun controlEventsHaveTimesAndOnlyTakeoverBoundaries() {
        val control = TaskControl().apply { start() }
        control.transition(TaskStatus.TAKEOVER, "需要登录")
        control.transition(TaskStatus.RUNNING)
        @Suppress("UNCHECKED_CAST")
        val events = control.snapshot()["events"] as List<Map<String, Any>>
        assertEquals(listOf("takeover_start", "takeover_end", "running"), events.map { it["type"] })
        assertTrue(events.all { it["timestamp"] is Double })
        assertTrue(events.all { it.keys == setOf("type", "reason", "timestamp") })
        assertEquals(emptyList<Any>(), control.snapshot()["events"])
    }

    @Test fun questionTimeoutPausesAndStillWaitsForExplicitAnswer() {
        val future = CompletableFuture<String>()
        val paused = CountDownLatch(1)
        val result = CompletableFuture<String>()
        val worker = thread { result.complete(QuestionWaiter.await(future, { paused.countDown() }, 10)) }
        assertTrue(paused.await(1, TimeUnit.SECONDS))
        assertFalse(result.isDone)
        future.complete("用户回答")
        assertEquals("用户回答", result.get(1, TimeUnit.SECONDS))
        worker.join(1000)
    }

    @Test fun stoppingAnUnansweredQuestionReleasesItsWaiter() {
        val future = CompletableFuture<String>()
        val result = CompletableFuture<String>()
        val worker = thread { result.complete(QuestionWaiter.await(future, { }, 1000)) }
        future.complete("stopped")
        assertEquals("stopped", result.get(1, TimeUnit.SECONDS))
        worker.join(1000)
    }

    private fun assertBlocked(operation: () -> Unit) {
        try { operation(); fail("dispatch should be blocked") } catch (_: IllegalStateException) { }
    }
}
