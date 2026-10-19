package com.seetouch.app.task

import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class TaskResultStoreTest {
    @get:Rule val temporary = TemporaryFolder()
    private fun result() = TaskResult("task_local", "查询当前页面", TaskStatus.COMPLETED,
        null, 2, 3.0, 100, 30, "查询答案", 2, "/private/runs/task_local/step_002.png")
    @Test fun resultCanBeReopenedAfterTheControllerHasBeenRecreated() {
        val directory = temporary.newFolder("results")
        val original = result()
        TaskResultStore(directory).save(original)
        val reopened = TaskResultStore(directory)
        assertEquals(original, reopened.latest())
        assertEquals("查询答案", reopened.load("task_local")!!.answer)
    }
    @Test fun feedbackIsEditableAndDoesNotChangeTheOriginalResult() {
        val store = TaskResultStore(temporary.newFolder("feedback"))
        val original = result()
        store.save(original)
        store.saveFeedback(original.taskId, true, "第一次评价")
        store.saveFeedback(original.taskId, false, "修改后的评价")
        assertFalse(store.feedback(original.taskId)!!.getBoolean("positive"))
        assertEquals("修改后的评价", store.feedback(original.taskId)!!.getString("comment"))
        assertEquals(original, store.load(original.taskId))
    }
    @Test fun untrustedResultIdentifierCannotEscapePrivateStorage() {
        val store = TaskResultStore(temporary.newFolder("safe"))
        assertNull(store.load("../elsewhere"))
        try { store.saveFeedback("../elsewhere", true, "text"); fail("invalid id") }
        catch (_: IllegalArgumentException) { }
    }
}
