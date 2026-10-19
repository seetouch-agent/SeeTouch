package com.seetouch.app.ui

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import com.seetouch.app.task.TaskController
import com.seetouch.app.task.TaskStatus
import com.seetouch.app.task.TaskUiState

/** Hide SeeTouch before releasing a waiter, so the next observation sees the target app. */
fun returnToTarget(context: Context, action: () -> Unit) {
    val generation = TaskController.state.value.taskGeneration
    var current: Context? = context
    while (current is ContextWrapper && current !is Activity) current = current.baseContext
    (current as? Activity)?.moveTaskToBack(true)
    Handler(Looper.getMainLooper()).postDelayed({
        if (TaskController.state.value.taskGeneration == generation) action()
    }, 250)
}

@Composable
fun TaskInteractionControls(state: TaskUiState) {
    val context = LocalContext.current
    val active = state.workerActive && state.status != TaskStatus.STOPPED
    if (active) {
        Row {
            if (state.status in setOf(TaskStatus.PAUSED, TaskStatus.TAKEOVER)) {
                OutlinedButton(onClick = { returnToTarget(context) { TaskController.resume() } }) { Text("继续") }
            } else OutlinedButton(onClick = { TaskController.pause() }) { Text("暂停") }
            OutlinedButton(onClick = { TaskController.stop() }) { Text("终止") }
            if (state.status != TaskStatus.TAKEOVER)
                TextButton(onClick = { TaskController.requestTakeover(); (context as? Activity)?.moveTaskToBack(true) }) {
                    Text("我来操作")
                }
        }
    }
    var notificationsAllowed by remember { mutableStateOf(Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) }
    val notificationPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        notificationsAllowed = it
    }
    if (!notificationsAllowed) TextButton(onClick = {
        if (Build.VERSION.SDK_INT >= 33) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }) { Text("开启任务通知（暂停、继续和快捷回复）") }

    state.pendingQuestion?.let { question ->
        var answer by remember(question.id) { mutableStateOf("") }
        var voiceError by remember(question.id) { mutableStateOf<String?>(null) }
        val speech = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { answer = it }
        }
        AlertDialog(onDismissRequest = { }, title = { Text("需要你的回答") }, text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(question.question)
                question.options.forEach { option ->
                    OutlinedButton(onClick = { answer = option }, modifier = Modifier.fillMaxWidth()) { Text(option) }
                }
                OutlinedTextField(value = answer, onValueChange = { answer = it }, label = { Text("补充信息") })
                TextButton(onClick = {
                    runCatching { speech.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                        .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                        .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")) }
                        .onFailure { voiceError = "系统语音输入不可用，请直接输入文字" }
                }) { Text("语音回答") }
                voiceError?.let { Text(it) }
                if (state.status == TaskStatus.PAUSED) Text(state.controlReason)
            }
        }, confirmButton = {
            TextButton(enabled = answer.isNotBlank(), onClick = {
                returnToTarget(context) { TaskController.submitAnswer(answer, question.id) }
            }) { Text("提交回答") }
        }, dismissButton = {
            Row {
                TextButton(onClick = { TaskController.requestTakeover(); (context as? Activity)?.moveTaskToBack(true) }) { Text("我来操作") }
                TextButton(onClick = { TaskController.pause() }) { Text("暂停") }
                TextButton(onClick = { TaskController.stop() }) { Text("终止") }
            }
        })
    }
}
