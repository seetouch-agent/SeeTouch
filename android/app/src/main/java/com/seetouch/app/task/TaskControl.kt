package com.seetouch.app.task

/** A single monitor protects transitions and native dispatch; never hold it while awaiting gestures. */
class TaskControl {
    var active = false; private set
    var mode = TaskStatus.IDLE; private set
    var revision = 0L; private set
    private val events = mutableListOf<Map<String, Any>>()

    @Synchronized fun start() {
        check(!active)
        active = true
        mode = TaskStatus.RUNNING
        revision++
        events.clear()
    }

    @Synchronized fun transition(next: TaskStatus, reason: String = ""): Boolean {
        if (!active || mode == TaskStatus.STOPPED || next == mode) return false
        if (mode == TaskStatus.TAKEOVER) event("takeover_end", "")
        mode = next
        revision++
        event(if (next == TaskStatus.TAKEOVER) "takeover_start" else next.name.lowercase(), reason)
        return true
    }

    @Synchronized fun finish() { active = false }

    @Synchronized fun <T> dispatch(expectedRevision: Long?, operation: () -> T): T {
        check(!active || (mode == TaskStatus.RUNNING &&
            (expectedRevision == null || expectedRevision == revision))) { "Task control blocked device operation" }
        return operation()
    }

    @Synchronized fun snapshot(): Map<String, Any> = mapOf(
        "mode" to when (mode) {
            TaskStatus.RUNNING -> "running"
            TaskStatus.WAITING_USER -> "waiting_user"
            TaskStatus.TAKEOVER -> "takeover"
            TaskStatus.STOPPED -> "stopped"
            else -> "paused"
        },
        "revision" to revision, "events" to events.toList().also { events.clear() },
    )

    private fun event(type: String, reason: String) {
        events.add(mapOf("type" to type, "reason" to reason,
            "timestamp" to System.currentTimeMillis() / 1000.0))
    }
}
