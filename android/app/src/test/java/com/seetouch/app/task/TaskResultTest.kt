package com.seetouch.app.task

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class TaskResultTest {
    @Test fun eachRequiredFailureReasonProducesAReadableCauseAndSuggestion() {
        for (reason in FailureReason.entries) {
            val result = TaskResult.fromRunner(JSONObject().put("completed", false)
                .put("reason_code", reason.name.lowercase()).toString(), "task_test", "任务", 2, 4.0)
            assertEquals(reason, result.reason)
            assertTrue(result.reason!!.title.isNotBlank())
            assertTrue(result.reason!!.suggestion.isNotBlank())
            assertNotEquals(TaskStatus.COMPLETED, result.status)
        }
    }
    @Test fun answerUsageAndSourceSurvivePersistenceRoundTrip() {
        val result = TaskResult.fromRunner("""{"task_id":"task_answer","completed":true,
            "total_steps":3,"elapsed_seconds":4.5,"tokens":{"input":100,"output":40},
            "answer":"明天晴","answer_source_step":2,"answer_screenshot":"/private/runs/task/step_002.png",
            "used_memory_ids":["memory_1"],"learned_memory_id":"learned_1","learning_status":"saved",
            "memory_suggestions":[{"category":"preference","name":"天气","content":"显示温度"}]}""",
            "fallback", "查天气", 0, 0.0)
        assertEquals(result, TaskResult.fromJson(result.toJson()))
        assertEquals("明天晴", result.answer)
        assertEquals(2, result.sourceStep)
        assertEquals(100L, result.inputUsage)
        assertTrue(result.speechText.contains("明天晴"))
        assertEquals(listOf("memory_1"), result.usedMemoryIds)
        assertEquals("learned_1", result.learnedMemoryId)
        assertEquals("saved", result.learningStatus)
    }
    @Test fun userStopCannotBeOverwrittenByALateModelSuccess() {
        val result = TaskResult.fromRunner("""{"completed":true}""", "task_stop", "任务", 3, 1.0, true)
        assertEquals(TaskStatus.STOPPED, result.status)
        assertEquals(FailureReason.USER_STOPPED, result.reason)
    }
    @Test fun rawExceptionsAreNotShownAsResultMessages() {
        val result = TaskResult.fromRunner("""{"status":"error","detail":"reasoning_failed quota private-key-secret"}""",
            "task_error", "任务", 0, 1.0)
        assertEquals(FailureReason.QUOTA, result.reason)
        assertFalse(result.toJson().toString().contains("private-key-secret"))
    }
}
