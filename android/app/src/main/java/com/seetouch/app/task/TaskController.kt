package com.seetouch.app.task

import android.util.Log
import android.content.Context
import com.seetouch.app.settings.AppSettings
import com.chaquo.python.Python
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONObject
import java.util.concurrent.CompletableFuture
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.Executors
import java.util.UUID

object TaskController {
    private const val TAG = "SeeTouchTask"
    private val _state = MutableStateFlow(TaskUiState())
    val state: StateFlow<TaskUiState> = _state.asStateFlow()
    private val running = AtomicBoolean(false)
    private val control = TaskControl()
    private val expectedRevision = ThreadLocal<Long?>()
    private var confirmGate: ConfirmationGate? = null
    private var confirmationTimeout = 60
    private var appContext: Context? = null
    private val persistence = Executors.newSingleThreadExecutor()
    private var runId = ""
    private var startedNanos = 0L
    private var interactionFuture: CompletableFuture<String>? = null
    private var questionId = 0L
    private var confirmationId = 0L
    private var taskGeneration = 0L
    val isRunning: Boolean get() = running.get()

    fun init(context: Context) {
        appContext = context.applicationContext
        TaskResultStore(context).latest()?.let { result ->
            _state.value = TaskUiState(status = result.status, instruction = result.instruction, result = result)
        }
    }

    fun expectRevision(revision: Long) { expectedRevision.set(revision) }
    fun <T> withDeviceAction(operation: () -> T): T = control.dispatch(expectedRevision.get(), operation)
    fun controlJson(): String = JSONObject(control.snapshot()).toString()

    fun executeBlocking(instruction: String, taskConfigJson: String) {
        if (!running.compareAndSet(false, true)) return
        try {
            synchronized(control) {
                startedNanos = System.nanoTime()
                runId = "task_${System.currentTimeMillis() / 1000}_${UUID.randomUUID().toString().take(6)}"
                confirmationTimeout = JSONObject(taskConfigJson).optInt("confirmation_timeout", 60).coerceIn(10, 600)
                appContext?.let { AppSettings(it).rememberInstruction(instruction) }
                control.start()
                _state.value = TaskUiState(status = TaskStatus.RUNNING, instruction = instruction,
                    workerActive = true, taskGeneration = ++taskGeneration,
                    maxSteps = JSONObject(taskConfigJson).optInt("max_steps", 45).coerceIn(1, 200))
            }
            val result = Python.getInstance().getModule("seetouchapp.task_entry").callAttr(
                "run_task", instruction, JSONObject(taskConfigJson).put("task_id", runId).toString(),
                { json: String -> onStep(json); Unit },
                { message: String -> awaitConfirmation(message) },
                { json: String -> onProgress(json); Unit },
                { _: String -> controlJson() },
                { json: String -> awaitInteraction(json) },
            ).toString()
            onFinished(result)
        } catch (t: Throwable) {
            Log.e(TAG, "task crashed", t)
            synchronized(control) {
                finishResult(JSONObject().put("status", "error").put("detail", t.toString()).toString())
            }
        } finally {
            synchronized(control) {
                confirmGate?.cancel("stopped")
                interactionFuture?.complete(reply("stopped"))
                confirmGate = null; interactionFuture = null
                control.finish()
                expectedRevision.remove()
                _state.update { it.copy(workerActive = false, pendingConfirmation = null, pendingQuestion = null) }
                running.set(false)
            }
        }
    }

    fun pause() = synchronized(control) {
        if (control.mode !in setOf(TaskStatus.RUNNING, TaskStatus.WAITING_USER)) return@synchronized
        changeMode(TaskStatus.PAUSED, "已暂停，继续后重新观察屏幕")
        confirmGate?.cancel("interrupted")
        _state.update { it.copy(pendingConfirmation = null) }
    }

    fun resume() = synchronized(control) {
        if (control.mode !in setOf(TaskStatus.PAUSED, TaskStatus.TAKEOVER)) return@synchronized
        val target = if (_state.value.pendingQuestion != null) TaskStatus.WAITING_USER else TaskStatus.RUNNING
        changeMode(target)
        interactionFuture?.takeIf { target == TaskStatus.RUNNING }?.complete(reply("resumed"))
    }

    fun stop() = synchronized(control) {
        if (!control.transition(TaskStatus.STOPPED)) return@synchronized
        _state.update { it.copy(status = TaskStatus.STOPPED, pendingQuestion = null,
            pendingConfirmation = null, resultSummary = "已终止，不再下发新操作；正在结束当前请求") }
        confirmGate?.cancel("stopped")
        interactionFuture?.complete(reply("stopped"))
        finishResult("{}")
    }

    fun requestTakeover(reason: String = "用户选择我来操作") = synchronized(control) {
        if (!control.active || control.mode == TaskStatus.STOPPED || control.mode == TaskStatus.TAKEOVER)
            return@synchronized
        changeMode(TaskStatus.TAKEOVER, reason)
        confirmGate?.cancel("interrupted")
        interactionFuture?.complete(reply("interrupted"))
        _state.update { it.copy(pendingConfirmation = null, pendingQuestion = null) }
    }

    fun submitAnswer(answer: String, id: Long? = null) = synchronized(control) {
        val question = _state.value.pendingQuestion ?: return@synchronized
        if (answer.isBlank() || (id != null && question.id != id) || control.mode == TaskStatus.STOPPED)
            return@synchronized
        val resume = control.mode == TaskStatus.WAITING_USER || _state.value.controlReason == QUESTION_TIMEOUT
        _state.update { it.copy(pendingQuestion = null) }
        if (resume) changeMode(TaskStatus.RUNNING)
        interactionFuture?.complete(reply("answered", answer.trim()))
    }

    fun setVoiceDraft(id: Long, draft: String) = synchronized(control) {
        _state.update { state ->
            val question = state.pendingQuestion
            if (question?.id != id) state else state.copy(pendingQuestion = question.copy(
                voiceDraft = draft, voiceRevision = question.voiceRevision + 1))
        }
    }

    fun respondToConfirmation(approved: Boolean, id: Long? = null) = synchronized(control) {
        val pending = _state.value.pendingConfirmation ?: return@synchronized
        if ((id != null && pending.id != id) || control.mode != TaskStatus.RUNNING) return@synchronized
        confirmGate?.respond(approved)
        _state.update { it.copy(pendingConfirmation = null) }
    }

    fun resetIfFinished() { if (!running.get()) _state.value = TaskUiState() }

    private fun changeMode(mode: TaskStatus, reason: String = "") {
        if (control.transition(mode, reason)) _state.update { it.copy(status = mode, controlReason = reason) }
    }

    private fun onStep(json: String) {
        val info = StepInfo.fromJson(json)
        _state.update { it.copy(steps = it.steps + info, progress = TaskProgress(info.step,
            TaskPhase.BETWEEN_STEPS, info.action, info.actionSummary)) }
    }

    private fun onProgress(json: String) {
        runCatching { TaskProgress.fromJson(json) }.onSuccess { progress ->
            _state.update { state -> if (state.status != TaskStatus.RUNNING) state else state.copy(
                progress = if (progress.step == state.progress.step && progress.phase == TaskPhase.EXECUTING)
                    progress.copy(actionSummary = state.progress.actionSummary) else progress) }
        }.onFailure { Log.w(TAG, "invalid progress", it) }
    }

    private fun awaitConfirmation(message: String): String {
        val gate = ConfirmationGate(confirmationTimeout)
        synchronized(control) {
            if (control.mode != TaskStatus.RUNNING) {
                gate.cancel("interrupted"); return gate.await()
            }
            confirmGate = gate
            _state.update { it.copy(pendingConfirmation = PendingConfirmation.fromRequest(message)
                .copy(id = ++confirmationId, deadlineNanos = gate.deadlineNanos)) }
        }
        return try { gate.await() }
        finally { synchronized(control) {
            if (confirmGate === gate) { confirmGate = null; _state.update { it.copy(pendingConfirmation = null) } }
        } }
    }

    private fun awaitInteraction(json: String): String {
        val request = JSONObject(json)
        val future = CompletableFuture<String>()
        val question = request.optString("type") == "ASK_USER"
        synchronized(control) {
            if (control.mode == TaskStatus.STOPPED) return reply("stopped")
            if (control.mode != TaskStatus.RUNNING) return reply("interrupted")
            interactionFuture = future
            if (question) {
                val options = request.optJSONArray("options")
                val pending = PendingQuestion(++questionId, request.getString("question"),
                    if (options == null) emptyList() else (0 until options.length()).map { options.getString(it) })
                changeMode(TaskStatus.WAITING_USER)
                _state.update { it.copy(pendingQuestion = pending) }
            } else changeMode(TaskStatus.TAKEOVER, request.optString("reason", "需要人工操作"))
        }
        return try {
            if (!question) future.get() else QuestionWaiter.await(future, {
                synchronized(control) {
                    if (interactionFuture === future && control.mode == TaskStatus.WAITING_USER)
                        changeMode(TaskStatus.PAUSED, QUESTION_TIMEOUT)
                }
            })
        } finally { synchronized(control) { if (interactionFuture === future) interactionFuture = null } }
    }

    private fun onFinished(json: String) = synchronized(control) { finishResult(json) }

    private fun finishResult(json: String) {
        val parsed = TaskResult.fromRunner(json, runId, _state.value.instruction, _state.value.steps.size,
            (System.nanoTime() - startedNanos) / 1e9, control.mode == TaskStatus.STOPPED)
        val previous = _state.value.result
        val result = if (parsed.status == TaskStatus.STOPPED && previous?.taskId == parsed.taskId)
            parsed.copy(elapsedSeconds = previous.elapsedSeconds) else parsed
        _state.update { it.copy(status = result.status, result = result,
            pendingConfirmation = null, pendingQuestion = null,
            resultSummary = "${result.statusLabel}，共 ${result.totalSteps} 步") }
        appContext?.let { context ->
            persistence.execute { runCatching { TaskResultStore(context).save(result) }
                .onFailure { Log.w(TAG, "cannot save task result", it) } }
            ResultSpeaker.speak(context, result, AppSettings(context).speakResults)
        }
    }

    private fun reply(status: String, answer: String = "") = JSONObject()
        .put("status", status).put("answer", answer).toString()
    const val QUESTION_TIMEOUT = "追问超过 5 分钟未回答，已暂停"
}
