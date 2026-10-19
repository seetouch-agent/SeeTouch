package com.seetouch.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.seetouch.app.task.ConfirmationGate
import com.seetouch.app.task.PendingConfirmation
import com.seetouch.app.task.TaskController
import kotlinx.coroutines.delay

@Composable
fun ConfirmationCard(pending: PendingConfirmation) {
    val context = LocalContext.current
    val rejectFocus = remember(pending.id) { FocusRequester() }
    var remaining by remember(pending.id) { mutableStateOf(ConfirmationGate.secondsRemaining(pending.deadlineNanos)) }
    LaunchedEffect(pending.id) {
        rejectFocus.requestFocus()
        while (remaining > 0) { delay(250); remaining = ConfirmationGate.secondsRemaining(pending.deadlineNanos) }
    }
    AlertDialog(onDismissRequest = { TaskController.respondToConfirmation(false, pending.id) },
        title = { Text("敏感操作待确认") }, text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(pending.message)
                Text("可能后果：${pending.consequences}")
                AndroidView(factory = { MarkedScreenshotView(it) }, update = {
                    it.setSource(pending.screenshotPath, pending.parameters)
                }, modifier = Modifier.fillMaxWidth().height(220.dp))
                Text("${remaining} 秒后自动拒绝；红圈表示将操作的位置")
            }
        }, confirmButton = {
            TextButton(enabled = remaining > 0, onClick = {
                returnToTarget(context) { TaskController.respondToConfirmation(true, pending.id) }
            }) { Text("允许本次") }
        }, dismissButton = {
            TextButton(modifier = Modifier.focusRequester(rejectFocus), onClick = {
                TaskController.respondToConfirmation(false, pending.id)
            }) { Text("拒绝") }
        })
}
