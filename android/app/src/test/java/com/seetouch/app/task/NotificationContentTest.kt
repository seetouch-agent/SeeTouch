package com.seetouch.app.task

import org.junit.Assert.*
import org.junit.Test

class NotificationContentTest {
    @Test fun modelTextQuestionsScreenshotsAndAnswersNeverAppearInNotificationText() {
        val privateText = "private-screen-secret"
        val base = TaskUiState(status = TaskStatus.RUNNING, instruction = "查询天气",
            progress = TaskProgress(3, TaskPhase.CHECKING, "CLICK", privateText))
        val states = listOf(base,
            base.copy(pendingConfirmation = PendingConfirmation(privateText, screenshotPath = privateText)),
            base.copy(status = TaskStatus.WAITING_USER, pendingQuestion = PendingQuestion(2, privateText, listOf(privateText))),
            base.copy(status = TaskStatus.TAKEOVER, controlReason = privateText),
            base.copy(status = TaskStatus.PAUSED, controlReason = privateText),
            base.copy(status = TaskStatus.ERROR, errorDetail = privateText),
            base.copy(result = TaskResult("task", "查询天气", TaskStatus.COMPLETED, null, 3, 4.0, 1, 1, privateText)))
        for (state in states) {
            val text = NotificationContent.from(state)
            assertFalse(text.title.contains(privateText))
            assertFalse(text.text.contains(privateText))
            assertEquals("查询天气", text.text)
        }
    }
    @Test fun progressShowsTheCurrentStepAndEventsAreImportant() {
        val running = NotificationContent.from(TaskUiState(status = TaskStatus.RUNNING,
            progress = TaskProgress(4, TaskPhase.THINKING)))
        assertTrue(running.title.contains("第 4 步"))
        assertFalse(running.important)
        for (status in listOf(TaskStatus.PAUSED, TaskStatus.TAKEOVER, TaskStatus.WAITING_USER, TaskStatus.STOPPED))
            assertTrue(NotificationContent.from(TaskUiState(status = status)).important)
    }
}
