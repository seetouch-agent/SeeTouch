package com.seetouch.app.task

/** Never derive notification text from screenshots, model summaries, answers or questions. */
data class NotificationContent(val title: String, val text: String, val important: Boolean) {
    companion object {
        fun from(state: TaskUiState): NotificationContent {
            val title = when {
                state.result != null -> "SeeTouch · ${state.result.statusLabel}"
                state.pendingConfirmation != null -> "SeeTouch · 待确认敏感操作"
                state.status == TaskStatus.WAITING_USER -> "SeeTouch · 需要你的回答"
                state.status == TaskStatus.TAKEOVER -> "SeeTouch · 请手动操作，完成后继续"
                state.status == TaskStatus.PAUSED -> "SeeTouch · 已暂停"
                state.status == TaskStatus.STOPPED -> "SeeTouch · 已终止"
                else -> "SeeTouch · 第 ${state.progress.step.coerceAtLeast(1)} 步 · ${state.progress.phase.label}"
            }
            return NotificationContent(title, state.instruction.replace(Regex("\\s+"), " ").take(60),
                state.pendingConfirmation != null || state.status != TaskStatus.RUNNING)
        }
    }
}
