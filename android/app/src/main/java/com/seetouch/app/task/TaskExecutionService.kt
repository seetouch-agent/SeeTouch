package com.seetouch.app.task

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import com.seetouch.app.device.SeeTouchAccessibilityService
import com.seetouch.app.ui.MainActivity
import com.seetouch.app.ui.VoiceReplyActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.concurrent.thread

class TaskExecutionService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var workerStarted = false
    private var lastEvent = ""
    private val manager by lazy { getSystemService(NotificationManager::class.java) }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onCreate() {
        super.onCreate()
        manager.createNotificationChannel(NotificationChannel(PROGRESS_CHANNEL, "执行进度", NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(NotificationChannel(EVENT_CHANNEL, "任务交互与结果", NotificationManager.IMPORTANCE_HIGH))
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action?.startsWith("com.seetouch.app.") == true &&
            intent.getLongExtra(GENERATION, -1) != TaskController.state.value.taskGeneration) {
            if (!workerStarted && !TaskController.isRunning) stopSelf()
            return START_NOT_STICKY
        }
        when (intent?.action) {
            ACTION_PAUSE -> TaskController.pause()
            ACTION_RESUME -> returnToTarget { TaskController.resume() }
            ACTION_STOP -> TaskController.stop()
            ACTION_TAKEOVER -> TaskController.requestTakeover()
            ACTION_ANSWER -> RemoteInput.getResultsFromIntent(intent)?.getCharSequence(REPLY_KEY)?.let {
                val answer = it.toString()
                returnToTarget { TaskController.submitAnswer(answer, intent.getLongExtra(QUESTION_ID, -1)) }
            }
            ACTION_ALLOW -> returnToTarget { TaskController.respondToConfirmation(true, intent.getLongExtra(CONFIRMATION_ID, -1)) }
            ACTION_DENY -> TaskController.respondToConfirmation(false, intent.getLongExtra(CONFIRMATION_ID, -1))
            else -> {
                val instruction = intent?.getStringExtra(EXTRA_INSTRUCTION)
                val config = intent?.getStringExtra(EXTRA_CONFIG_JSON)
                if (instruction.isNullOrBlank() || config.isNullOrBlank()) {
                    if (!TaskController.isRunning) stopSelf()
                    return START_NOT_STICKY
                }
                if (workerStarted || TaskController.isRunning) return START_NOT_STICKY
                workerStarted = true
                val generation = TaskController.state.value.taskGeneration + 1
                startForeground(PROGRESS_ID, build(TaskUiState(status = TaskStatus.RUNNING,
                    instruction = instruction, workerActive = true), false))
                scope.launch { TaskController.state.collect { state ->
                    if (state.taskGeneration >= generation) renderNotifications(state)
                } }
                scope.launch {
                    while (workerStarted) {
                        delay(1000)
                        val state = TaskController.state.value
                        if (state.pendingConfirmation != null) renderNotifications(state)
                    }
                }
                thread(name = "seetouch-task") {
                    try { TaskController.executeBlocking(instruction, config) }
                    finally { Handler(Looper.getMainLooper()).post {
                        TaskController.state.value.result?.let { postResult(TaskController.state.value) }
                        workerStarted = false
                        manager.cancel(EVENT_ID)
                        stopForeground(STOP_FOREGROUND_REMOVE)
                        stopSelf()
                    } }
                }
            }
        }
        if (!workerStarted && !TaskController.isRunning) stopSelf()
        return START_NOT_STICKY
    }
    override fun onDestroy() { TaskController.stop(); scope.cancel(); super.onDestroy() }

    private fun renderNotifications(state: TaskUiState) {
        if (state.workerActive) notify(PROGRESS_ID, build(state, false))
        if (state.result != null) { manager.cancel(EVENT_ID); postResult(state); return }
        val content = NotificationContent.from(state)
        if (content.important && state.workerActive) {
            val key = "${state.taskGeneration}:${state.status}:${state.pendingQuestion?.id}:${state.pendingConfirmation?.id}"
            notify(EVENT_ID, build(state, true, key == lastEvent))
            lastEvent = key
        } else { manager.cancel(EVENT_ID); lastEvent = "" }
    }
    private fun postResult(state: TaskUiState) {
        val result = state.result ?: return
        notify(100 + (result.taskId.hashCode() and 0x3fffffff), build(state, true, true))
    }
    private fun notify(id: Int, notification: Notification) { runCatching { manager.notify(id, notification) } }
    private fun returnToTarget(operation: () -> Unit) {
        SeeTouchAccessibilityService.instance?.dismissNotificationShade()
        MainActivity.hideIfVisible()
        VoiceReplyActivity.closeForResume()
        val generation = TaskController.state.value.taskGeneration
        Handler(Looper.getMainLooper()).postDelayed({
            if (TaskController.state.value.taskGeneration == generation) operation()
        }, 250)
    }
    private fun action(state: TaskUiState, caption: String, command: String, answer: Boolean = false): Notification.Action {
        val intent = Intent(this, TaskExecutionService::class.java).setAction(command)
            .putExtra(GENERATION, state.taskGeneration)
            .putExtra(QUESTION_ID, state.pendingQuestion?.id ?: -1)
            .putExtra(CONFIRMATION_ID, state.pendingConfirmation?.id ?: -1)
        val stamp = state.pendingQuestion?.id ?: state.pendingConfirmation?.id ?: 0
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or if (answer) PendingIntent.FLAG_MUTABLE else PendingIntent.FLAG_IMMUTABLE
        val pending = PendingIntent.getService(this, command.hashCode() xor stamp.toInt() xor state.taskGeneration.toInt(), intent, flags)
        return Notification.Action.Builder(null, caption, pending).apply {
            if (answer) addRemoteInput(RemoteInput.Builder(REPLY_KEY).setLabel("回答（在卡片中查看问题）")
                .setAllowFreeFormInput(true).build())
        }.build()
    }
    private fun build(state: TaskUiState, important: Boolean, silentUpdate: Boolean = true): Notification {
        val content = NotificationContent.from(state)
        val result = state.result
        val open = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        if (result != null) open.putExtra(MainActivity.EXTRA_RESULT_ID, result.taskId)
        val pending = PendingIntent.getActivity(this, result?.taskId?.hashCode() ?: 0, open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val channel = if (important) EVENT_CHANNEL else PROGRESS_CHANNEL
        val public = Notification.Builder(this, channel).setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentTitle(content.title).setContentText("解锁后查看任务").build()
        return Notification.Builder(this, channel).setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentTitle(content.title).setContentText(content.text)
            .setContentIntent(pending).setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(public)
            .setOngoing(result == null).setAutoCancel(result != null).setOnlyAlertOnce(silentUpdate)
            .apply {
                if (state.pendingConfirmation != null) setSubText(
                    "${ConfirmationGate.secondsRemaining(state.pendingConfirmation.deadlineNanos)} 秒后自动拒绝")
                if (result == null && state.status != TaskStatus.STOPPED) {
                    when {
                        state.pendingConfirmation != null -> {
                            addAction(action(state, "拒绝", ACTION_DENY)); addAction(action(state, "允许本次", ACTION_ALLOW))
                        }
                        state.pendingQuestion != null -> {
                            addAction(action(state, "回答", ACTION_ANSWER, true))
                            val voice = PendingIntent.getActivity(this@TaskExecutionService, state.pendingQuestion.id.toInt(),
                                Intent(this@TaskExecutionService, VoiceReplyActivity::class.java)
                                    .putExtra(VoiceReplyActivity.QUESTION_ID, state.pendingQuestion.id),
                                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                            addAction(Notification.Action.Builder(null, "语音回答", voice).build())
                        }
                        state.status in setOf(TaskStatus.PAUSED, TaskStatus.TAKEOVER) -> addAction(action(state, "我已完成，继续", ACTION_RESUME))
                        else -> addAction(action(state, "暂停", ACTION_PAUSE))
                    }
                    addAction(action(state, "终止", ACTION_STOP))
                }
            }.build()
    }
    companion object {
        private const val PROGRESS_CHANNEL = "seetouch_progress_v2"
        private const val EVENT_CHANNEL = "seetouch_events_v2"
        private const val PROGRESS_ID = 1
        private const val EVENT_ID = 2
        private const val REPLY_KEY = "answer"
        private const val QUESTION_ID = "question_id"
        private const val CONFIRMATION_ID = "confirmation_id"
        private const val GENERATION = "task_generation"
        const val EXTRA_INSTRUCTION = "instruction"
        const val EXTRA_CONFIG_JSON = "config_json"
        const val ACTION_PAUSE = "com.seetouch.app.PAUSE"
        const val ACTION_RESUME = "com.seetouch.app.RESUME"
        const val ACTION_STOP = "com.seetouch.app.STOP"
        const val ACTION_TAKEOVER = "com.seetouch.app.TAKEOVER"
        const val ACTION_ANSWER = "com.seetouch.app.ANSWER"
        const val ACTION_ALLOW = "com.seetouch.app.ALLOW"
        const val ACTION_DENY = "com.seetouch.app.DENY"
        fun start(context: Context, instruction: String, taskConfigJson: String) {
            context.startForegroundService(Intent(context, TaskExecutionService::class.java)
                .putExtra(EXTRA_INSTRUCTION, instruction).putExtra(EXTRA_CONFIG_JSON, taskConfigJson))
        }
    }
}
