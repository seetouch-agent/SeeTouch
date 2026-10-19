package com.seetouch.app.task

import org.json.JSONObject

enum class FailureReason(val title: String, val suggestion: String) {
    MAX_STEPS("已达到最大步数", "可增加步数上限，或把任务拆成更小的步骤"),
    TIMEOUT("等待响应超时", "请检查网络；模型较慢时可增加请求超时"),
    STUCK_LOOP("连续重复操作，已停止", "请调整当前页面或补充更明确的任务说明"),
    MODEL_ERROR("模型调用失败", "请在设置中测试连接，检查模型和接口配置"),
    QUOTA("模型服务额度不足", "请检查服务商余额、配额或计费状态"),
    PERMISSION_MISSING("权限或模型访问权限缺失", "请检查无障碍服务、API Key 和模型访问权限"),
    APP_NOT_INSTALLED("未找到目标应用", "请先安装应用，并使用桌面显示的应用名称"),
    BLACKLISTED_APP("目标应用在禁止访问名单中", "请在设置中检查应用访问范围"),
    MODEL_UNABLE("模型判断当前任务无法完成", "可换一种描述，或手动调整页面后重试"),
    USER_DENIED("未允许敏感操作", "任务已停止；超时未确认也会拒绝执行"),
    USER_STOPPED("你已终止任务", "需要继续时请重新发起任务"),
    DEVICE_ERROR("设备操作异常", "请检查无障碍服务和当前页面后重试");

    companion object {
        fun from(code: String?): FailureReason? = entries.firstOrNull { it.name.equals(code, true) }
        fun classify(raw: String): FailureReason {
            val text = raw.lowercase()
            return when {
                listOf("quota", "balance", "billing", "overdue").any { it in text } -> QUOTA
                listOf("permission", "accessibility", "401", "403").any { it in text } -> PERMISSION_MISSING
                "timeout" in text || "timed out" in text -> TIMEOUT
                "max_steps" in text -> MAX_STEPS
                "stuck_loop" in text -> STUCK_LOOP
                "app_not_installed" in text -> APP_NOT_INSTALLED
                "blacklist" in text -> BLACKLISTED_APP
                "model_unable" in text || "interaction_unavailable" in text -> MODEL_UNABLE
                "user_denied" in text || "confirmation_timeout" in text -> USER_DENIED
                "user_stopped" in text -> USER_STOPPED
                "reasoning_failed" in text || "model_error" in text -> MODEL_ERROR
                else -> DEVICE_ERROR
            }
        }
    }
}

data class TaskResult(
    val taskId: String,
    val instruction: String,
    val status: TaskStatus,
    val reason: FailureReason?,
    val totalSteps: Int,
    val elapsedSeconds: Double,
    val inputUsage: Long,
    val outputUsage: Long,
    val answer: String = "",
    val sourceStep: Int? = null,
    val sourceScreenshot: String? = null,
    val finishedAt: Long = System.currentTimeMillis(),
    val usedMemoryIds: List<String> = emptyList(),
    val learnedMemoryId: String? = null,
    val learningStatus: String = "disabled",
    val memorySuggestions: String = "[]",
) {
    val statusLabel: String get() = when (status) {
        TaskStatus.COMPLETED -> "已完成"
        TaskStatus.STOPPED -> "已终止"
        else -> "未完成"
    }
    val speechText: String get() = "任务$statusLabel。" + (reason?.title?.plus("。") ?: "") + answer
    fun toJson(): JSONObject = JSONObject().put("task_id", taskId).put("instruction", instruction)
        .put("status", status.name).put("reason_code", reason?.name?.lowercase())
        .put("total_steps", totalSteps).put("elapsed_seconds", elapsedSeconds)
        .put("input_usage", inputUsage).put("output_usage", outputUsage).put("answer", answer)
        .put("source_step", sourceStep).put("source_screenshot", sourceScreenshot).put("finished_at", finishedAt)
        .put("used_memory_ids", org.json.JSONArray(usedMemoryIds)).put("learned_memory_id", learnedMemoryId)
        .put("learning_status", learningStatus).put("memory_suggestions", org.json.JSONArray(memorySuggestions))

    companion object {
        fun fromJson(o: JSONObject): TaskResult = TaskResult(
            o.getString("task_id"), o.optString("instruction"), TaskStatus.valueOf(o.getString("status")),
            FailureReason.from(o.optString("reason_code")), o.optInt("total_steps"),
            o.optDouble("elapsed_seconds", 0.0).coerceAtLeast(0.0),
            o.optLong("input_usage"), o.optLong("output_usage"), o.optString("answer"),
            o.optInt("source_step").takeIf { it > 0 },
            o.optString("source_screenshot").takeIf { it.isNotBlank() && it != "null" }, o.optLong("finished_at"),
            memoryIds(o), o.optString("learned_memory_id").takeIf { it.isNotBlank() && it != "null" },
            o.optString("learning_status", "disabled"), o.optJSONArray("memory_suggestions")?.toString() ?: "[]")

        fun fromRunner(json: String, fallbackId: String, instruction: String, steps: Int,
            elapsed: Double, stopped: Boolean = false): TaskResult {
            val o = JSONObject(json)
            val reason = if (stopped) FailureReason.USER_STOPPED else if (o.optBoolean("completed")) null
                else FailureReason.from(o.optString("reason_code")) ?: FailureReason.classify(
                    o.optString("aborted_reason") + " " + o.optString("detail"))
            val tokens = o.optJSONObject("tokens")
            return TaskResult(o.optString("task_id").ifBlank { fallbackId }, instruction,
                if (stopped || reason == FailureReason.USER_STOPPED) TaskStatus.STOPPED
                else if (o.optBoolean("completed")) TaskStatus.COMPLETED else TaskStatus.ABORTED,
                reason, o.optInt("total_steps", steps), o.optDouble("elapsed_seconds", elapsed),
                tokens?.optLong("input") ?: o.optLong("total_input_tokens"),
                tokens?.optLong("output") ?: o.optLong("total_output_tokens"),
                o.optString("answer"), o.optInt("answer_source_step").takeIf { it > 0 },
                o.optString("answer_screenshot").takeIf { it.isNotBlank() && it != "null" },
                usedMemoryIds = memoryIds(o), learnedMemoryId = o.optString("learned_memory_id")
                    .takeIf { it.isNotBlank() && it != "null" }, learningStatus = o.optString("learning_status", "disabled"),
                memorySuggestions = o.optJSONArray("memory_suggestions")?.toString() ?: "[]")
        }
        private fun memoryIds(o: JSONObject): List<String> = o.optJSONArray("used_memory_ids")?.let { a ->
            (0 until a.length()).map { a.getString(it) }
        } ?: emptyList()
    }
}
