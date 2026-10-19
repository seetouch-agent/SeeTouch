package com.seetouch.app.task

import org.json.JSONObject

enum class TaskPhase(val label: String) {
    STARTING("准备中"), CAPTURING("观察屏幕"), THINKING("思考中"),
    CHECKING("检查操作"), EXECUTING("执行中"), BETWEEN_STEPS("步骤结束"),
}

data class TaskProgress(
    val step: Int = 0,
    val phase: TaskPhase = TaskPhase.STARTING,
    val action: String = "",
    val actionSummary: String = "",
) {
    companion object {
        fun fromJson(json: String): TaskProgress {
            val o = JSONObject(json)
            val phase = TaskPhase.entries.firstOrNull {
                it.name.equals(o.optString("phase"), ignoreCase = true)
            } ?: TaskPhase.STARTING
            return TaskProgress(o.optInt("step").coerceAtLeast(0), phase,
                o.optString("action"), o.optString("action_summary"))
        }
    }
}

/** Step limits are a budget, so the overlay deliberately does not invent a completion percentage. */
data class TaskProgressDisplay(
    val title: String,
    val detail: String,
    val stepCount: String,
    val running: Boolean,
    val confirmation: PendingConfirmation?,
    val active: Boolean = running,
) {
    companion object {
        fun from(state: TaskUiState): TaskProgressDisplay {
            val running = state.status == TaskStatus.RUNNING
            val confirmation = state.pendingConfirmation.takeIf { running }
            val phase = if (confirmation != null) "等待确认" else state.progress.phase.label
            val title = when (state.status) {
                TaskStatus.IDLE -> "就绪"
                TaskStatus.RUNNING -> if (state.progress.step > 0)
                    "第 ${state.progress.step} 步 · $phase" else phase
                TaskStatus.PAUSED -> "已暂停"
                TaskStatus.WAITING_USER -> "等待你的回答"
                TaskStatus.TAKEOVER -> "人工接管中"
                TaskStatus.STOPPED -> "已终止"
                TaskStatus.COMPLETED -> "任务完成"
                TaskStatus.ABORTED -> "任务中止"
                TaskStatus.ERROR -> "任务出错"
            }
            val detail = when {
                confirmation != null -> confirmation.message
                state.pendingQuestion != null -> state.pendingQuestion.question
                state.status == TaskStatus.TAKEOVER -> state.controlReason + "；完成后点继续。接管期间不截图、不上传、不操作。"
                state.status == TaskStatus.PAUSED -> state.controlReason
                state.status == TaskStatus.ERROR -> "请回到 SeeTouch 查看错误详情"
                !running -> state.resultSummary.orEmpty()
                state.progress.actionSummary.isNotBlank() -> state.progress.actionSummary
                else -> state.instruction
            }
            return TaskProgressDisplay(title, detail,
                "已记录 ${state.steps.size} 步 · 最多 ${state.maxSteps} 步",
                running, confirmation, state.workerActive || state.status in setOf(
                    TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.WAITING_USER, TaskStatus.TAKEOVER))
        }
    }
}
