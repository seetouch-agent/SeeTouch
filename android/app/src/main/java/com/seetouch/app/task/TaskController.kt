package com.seetouch.app.task

import android.util.Log
import com.chaquo.python.Python
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONObject
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 任务执行核心:持有 UI 可观察状态,驱动 Python Runner。
 *
 * 单例 —— 前台 Service 与 Compose UI 共享同一状态源。
 * 执行线程由 TaskExecutionService 提供;本类不管理线程生命周期。
 */
object TaskController {

    private const val TAG = "SeeTouchTask"
    private const val CONFIRM_TIMEOUT_MIN = 5L

    private val _state = MutableStateFlow(TaskUiState())
    val state: StateFlow<TaskUiState> = _state.asStateFlow()

    private val running = AtomicBoolean(false)

    @Volatile
    private var confirmFuture: CompletableFuture<Boolean>? = null

    val isRunning: Boolean get() = running.get()

    /** 在调用方线程内同步执行任务(应为 Service 的后台线程)。 */
    fun executeBlocking(instruction: String, taskConfigJson: String) {
        if (!running.compareAndSet(false, true)) {
            Log.w(TAG, "task already running, ignore")
            return
        }
        _state.value = TaskUiState(status = TaskStatus.RUNNING, instruction = instruction)
        try {
            val maxSteps = JSONObject(taskConfigJson).optInt("max_steps", 45).coerceIn(1, 200)
            _state.update { it.copy(maxSteps = maxSteps) }
            val result = Python.getInstance()
                .getModule("seetouchapp.task_entry")
                .callAttr(
                    "run_task", instruction, taskConfigJson,
                    { stepJson: String -> onStep(stepJson); Unit },
                    { message: String -> awaitConfirmation(message) },
                    { progressJson: String -> onProgress(progressJson); Unit },
                )
                .toString()
            onFinished(result)
        } catch (t: Throwable) {
            Log.e(TAG, "task crashed", t)
            _state.update { it.copy(status = TaskStatus.ERROR, errorDetail = t.toString()) }
        } finally {
            confirmFuture?.complete(false)
            confirmFuture = null
            _state.update { it.copy(pendingConfirmation = null) }
            running.set(false)
        }
    }

    /** UI 对敏感动作确认弹窗的回应。 */
    fun respondToConfirmation(approved: Boolean) {
        if (_state.value.pendingConfirmation == null) return
        _state.update { it.copy(pendingConfirmation = null) }
        confirmFuture?.complete(approved)
    }

    /** 开始新任务前清掉上一次的展示状态。 */
    fun resetIfFinished() {
        if (!running.get()) _state.value = TaskUiState()
    }

    // ------------------------- 内部 -------------------------

    private fun onStep(stepJson: String) {
        Log.i(TAG, "step: $stepJson")
        val info = StepInfo.fromJson(stepJson)
        _state.update { it.copy(steps = it.steps + info,
            progress = TaskProgress(info.step, TaskPhase.BETWEEN_STEPS,
                info.action, info.actionSummary)) }
    }

    private fun onProgress(progressJson: String) {
        runCatching { TaskProgress.fromJson(progressJson) }
            .onSuccess { progress ->
                _state.update { state ->
                    if (state.status != TaskStatus.RUNNING) state
                    else state.copy(progress = if (progress.step == state.progress.step &&
                        progress.phase == TaskPhase.EXECUTING)
                        progress.copy(actionSummary = state.progress.actionSummary) else progress)
                }
            }
            .onFailure { Log.w(TAG, "invalid progress callback", it) }
    }

    /** Python Runner 线程阻塞等待 UI 确认;超时视为拒绝。 */
    private fun awaitConfirmation(message: String): Boolean {
        val future = CompletableFuture<Boolean>()
        confirmFuture = future
        _state.update { it.copy(pendingConfirmation = PendingConfirmation.fromRunnerMessage(message)) }
        return try {
            future.get(CONFIRM_TIMEOUT_MIN, TimeUnit.MINUTES)
        } catch (t: Throwable) {
            Log.w(TAG, "confirmation timed out / failed -> deny", t)
            _state.update { it.copy(pendingConfirmation = null) }
            false
        } finally {
            confirmFuture = null
        }
    }

    private fun onFinished(resultJson: String) {
        Log.i(TAG, "result: $resultJson")
        val o = JSONObject(resultJson)
        if (o.optString("status") == "error") {
            _state.update {
                it.copy(status = TaskStatus.ERROR, errorDetail = o.optString("detail"))
            }
            return
        }
        val completed = o.optBoolean("completed", false)
        _state.update {
            it.copy(
                status = if (completed) TaskStatus.COMPLETED else TaskStatus.ABORTED,
                resultSummary = buildString {
                    append(if (completed) "任务完成" else "任务中止")
                    o.optString("aborted_reason").takeIf { r -> r.isNotEmpty() && r != "null" }
                        ?.let { r -> append("（$r）") }
                    append("，共 ${o.optInt("total_steps")} 步")
                },
            )
        }
    }
}
