package com.seetouch.app.task

import org.json.JSONObject

/** 任务生命周期状态。 */
enum class TaskStatus { IDLE, RUNNING, PAUSED, WAITING_USER, TAKEOVER, STOPPED, COMPLETED, ABORTED, ERROR }

data class PendingQuestion(val id: Long, val question: String, val options: List<String>)

/** 单步执行摘要(task_entry.py _step_summary 的 Kotlin 映射)。 */
data class StepInfo(
    val step: Int,
    val action: String,
    val parameters: String,
    val actionSummary: String,
    val screenSummary: String,
    val success: Boolean?,
    val notes: List<String>,
    val reasoningTime: Double,
) {
    companion object {
        fun fromJson(json: String): StepInfo {
            val o = JSONObject(json)
            val notes = mutableListOf<String>()
            o.optJSONArray("notes")?.let { arr ->
                for (i in 0 until arr.length()) notes.add(arr.getString(i))
            }
            return StepInfo(
                step = o.optInt("step"),
                action = o.optString("action"),
                parameters = o.optJSONObject("parameters")?.toString() ?: "{}",
                actionSummary = o.optString("action_summary"),
                screenSummary = o.optString("screen_summary"),
                success = if (o.isNull("success")) null else o.optBoolean("success"),
                notes = notes,
                reasoningTime = o.optDouble("reasoning_time", 0.0),
            )
        }
    }
}

/** 敏感动作待确认信息。 */
data class PendingConfirmation(val message: String, val id: Long = 0) {
    companion object {
        fun fromRunnerMessage(message: String): PendingConfirmation = PendingConfirmation(
            message.lineSequence().filterNot {
                val line = it.trim()
                line.startsWith("====") || line.startsWith("截图路径:") ||
                    line == "继续执行?[y/N]:"
            }.joinToString("\n").trim(),
        )
    }
}

/** UI 可观察的整体任务状态。 */
data class TaskUiState(
    val status: TaskStatus = TaskStatus.IDLE,
    val instruction: String = "",
    val steps: List<StepInfo> = emptyList(),
    val pendingConfirmation: PendingConfirmation? = null,
    val resultSummary: String? = null,
    val errorDetail: String? = null,
    val maxSteps: Int = 45,
    val progress: TaskProgress = TaskProgress(),
    val workerActive: Boolean = false,
    val pendingQuestion: PendingQuestion? = null,
    val controlReason: String = "",
    val taskGeneration: Long = 0,
)
