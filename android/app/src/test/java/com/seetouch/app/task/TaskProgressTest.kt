package com.seetouch.app.task

import org.junit.Assert.*
import org.junit.Test

class TaskProgressTest {
    @Test fun confirmationRemovesTerminalInstructionsButKeepsActionDetails() {
        val pending = PendingConfirmation.fromRunnerMessage("""
            ============== 敏感动作待确认 ==============
            动作类型:CLICK
            参数:    point=[500, 300]
            操作描述:确认发送
            界面状态:发送给小明
            截图路径:/internal/runs/step.png
            继续执行?[y/N]:
        """.trimIndent())
        assertTrue(pending.message.contains("确认发送"))
        assertTrue(pending.message.contains("发送给小明"))
        assertTrue(pending.message.contains("point=[500, 300]"))
        assertFalse(pending.message.contains("/internal/"))
        assertFalse(pending.message.contains("[y/N]"))
    }

    @Test fun progressCallbackPreservesStepPhaseAndSummary() {
        val progress = TaskProgress.fromJson("""{"step":2,"phase":"checking",
            "action":"CLICK","action_summary":"打开搜索框"}""")
        assertEquals(2, progress.step)
        assertEquals(TaskPhase.CHECKING, progress.phase)
        assertEquals("CLICK", progress.action)
        assertEquals("打开搜索框", progress.actionSummary)
    }

    @Test fun futurePhaseDoesNotCrashOrInventProgress() {
        val progress = TaskProgress.fromJson("""{"step":-1,"phase":"new_phase"}""")
        assertEquals(0, progress.step)
        assertEquals(TaskPhase.STARTING, progress.phase)
    }

    @Test fun reasoningShowsCurrentStepAndBudgetWithoutFakePercentage() {
        val display = TaskProgressDisplay.from(TaskUiState(
            status = TaskStatus.RUNNING, instruction = "打开时钟", maxSteps = 20,
            progress = TaskProgress(2, TaskPhase.THINKING),
        ))
        assertEquals("第 2 步 · 思考中", display.title)
        assertEquals("打开时钟", display.detail)
        assertEquals("已记录 0 步 · 最多 20 步", display.stepCount)
        assertTrue(display.running)
        assertNull(display.confirmation)
    }

    @Test fun confirmationOverridesExecutionPhaseAndKeepsEntirePrompt() {
        val message = "确认发送消息？".repeat(100)
        val display = TaskProgressDisplay.from(TaskUiState(status = TaskStatus.RUNNING,
            pendingConfirmation = PendingConfirmation(message),
            progress = TaskProgress(3, TaskPhase.CHECKING, "CLICK", "点击发送")))
        assertEquals("第 3 步 · 等待确认", display.title)
        assertEquals(message, display.detail)
        assertNotNull(display.confirmation)
    }

    @Test fun terminalStateDoesNotOfferStaleConfirmationOrExposeTraceback() {
        val display = TaskProgressDisplay.from(TaskUiState(status = TaskStatus.ERROR,
            pendingConfirmation = PendingConfirmation("old"), errorDetail = "private traceback"))
        assertEquals("任务出错", display.title)
        assertFalse(display.detail.contains("private traceback"))
        assertNull(display.confirmation)
        assertFalse(display.running)
        val complete = TaskProgressDisplay.from(TaskUiState(status = TaskStatus.COMPLETED,
            resultSummary = "任务完成，共 3 步"))
        assertEquals("任务完成，共 3 步", complete.detail)
    }
}
