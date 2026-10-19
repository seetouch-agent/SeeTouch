package com.seetouch.app.task

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.os.Handler
import android.os.Looper
import com.seetouch.app.device.SeeTouchAccessibilityService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlin.concurrent.thread

class TaskExecutionService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var workerStarted = false
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action?.startsWith("com.seetouch.app.") == true &&
            intent.getLongExtra(GENERATION, -1) != TaskController.state.value.taskGeneration)
            return START_NOT_STICKY
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
                startForeground(NOTIFICATION_ID, buildNotification(TaskUiState(
                    status = TaskStatus.RUNNING, instruction = instruction, workerActive = true)))
                scope.launch { TaskController.state.collect { state ->
                    if (state.workerActive) getSystemService(NotificationManager::class.java)
                        .notify(NOTIFICATION_ID, buildNotification(state))
                } }
                thread(name = "seetouch-task") {
                    try { TaskController.executeBlocking(instruction, config) }
                    finally { Handler(Looper.getMainLooper()).post {
                        workerStarted = false; stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
                    } }
                }
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() { TaskController.stop(); scope.cancel(); super.onDestroy() }

    private fun returnToTarget(operation: () -> Unit) {
        SeeTouchAccessibilityService.instance?.dismissNotificationShade()
        val generation = TaskController.state.value.taskGeneration
        Handler(Looper.getMainLooper()).postDelayed({
            if (TaskController.state.value.taskGeneration == generation) operation()
        }, 250)
    }

    private fun action(caption: String, command: String, question: PendingQuestion? = null): Notification.Action {
        val intent = Intent(this, TaskExecutionService::class.java).setAction(command)
            .putExtra(GENERATION, TaskController.state.value.taskGeneration)
        if (question != null) intent.putExtra(QUESTION_ID, question.id)
        val confirmation = TaskController.state.value.pendingConfirmation
        if (confirmation != null) intent.putExtra(CONFIRMATION_ID, confirmation.id)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or if (question != null)
            PendingIntent.FLAG_MUTABLE else PendingIntent.FLAG_IMMUTABLE
        val requestCode = command.hashCode() xor (question?.id?.toInt() ?: confirmation?.id?.toInt() ?: 0) xor
            TaskController.state.value.taskGeneration.toInt()
        val pending = PendingIntent.getService(this, requestCode, intent, flags)
        return Notification.Action.Builder(null, caption, pending).apply {
            if (question != null) addRemoteInput(RemoteInput.Builder(REPLY_KEY).setLabel("回答")
                .setChoices(question.options.toTypedArray()).setAllowFreeFormInput(true).build())
        }.build()
    }

    private fun buildNotification(state: TaskUiState): Notification {
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "任务执行", NotificationManager.IMPORTANCE_DEFAULT))
        val content = PendingIntent.getActivity(this, 0,
            packageManager.getLaunchIntentForPackage(packageName), PendingIntent.FLAG_IMMUTABLE)
        val display = TaskProgressDisplay.from(state)
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentTitle("SeeTouch · ${display.title}")
            .setContentText(display.detail)
            .setStyle(Notification.BigTextStyle().bigText(display.detail))
            .setContentIntent(content).setOngoing(true).setOnlyAlertOnce(true)
            .apply {
                if (state.status != TaskStatus.STOPPED) {
                    state.pendingQuestion?.let { addAction(action("回答", ACTION_ANSWER, it)) }
                    if (state.pendingConfirmation != null) {
                        addAction(action("允许", ACTION_ALLOW)); addAction(action("拒绝", ACTION_DENY))
                    } else if (state.status in setOf(TaskStatus.PAUSED, TaskStatus.TAKEOVER))
                        addAction(action("继续", ACTION_RESUME))
                    else addAction(action("暂停", ACTION_PAUSE))
                    if (state.pendingQuestion == null && state.pendingConfirmation == null && state.status != TaskStatus.TAKEOVER)
                        addAction(action("我来操作", ACTION_TAKEOVER))
                    addAction(action("终止", ACTION_STOP))
                }
            }.build()
    }

    companion object {
        private const val CHANNEL_ID = "seetouch_task"
        private const val NOTIFICATION_ID = 1
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
