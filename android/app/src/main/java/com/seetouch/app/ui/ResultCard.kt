package com.seetouch.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.seetouch.app.task.TaskResult
import com.seetouch.app.task.TaskResultStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun ResultCard(result: TaskResult) {
    val context = LocalContext.current
    val store = remember { TaskResultStore(context) }
    val scope = rememberCoroutineScope()
    var sourceOpen by remember(result.taskId) { mutableStateOf(false) }
    var positive by remember(result.taskId) { mutableStateOf<Boolean?>(null) }
    var comment by remember(result.taskId) { mutableStateOf("") }
    var saved by remember(result.taskId) { mutableStateOf(false) }
    var error by remember(result.taskId) { mutableStateOf<String?>(null) }
    LaunchedEffect(result.taskId) {
        val feedback = withContext(Dispatchers.IO) { store.feedback(result.taskId) }
        feedback?.let { positive = it.optBoolean("positive"); comment = it.optString("comment"); saved = true }
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(result.statusLabel, style = MaterialTheme.typography.titleLarge)
            Text(result.instruction)
            result.reason?.let { Text(it.title); Text("建议：${it.suggestion}") }
            Text("共 ${result.totalSteps} 步 · 用时 ${"%.1f".format(result.elapsedSeconds)} 秒")
            Text("模型用量：输入 ${result.inputUsage}，输出 ${result.outputUsage}")
            Text("实际扣费额度：服务商未返回，请以服务商账单为准", style = MaterialTheme.typography.bodySmall)
            if (result.answer.isNotBlank()) {
                Text("查询答案", style = MaterialTheme.typography.titleMedium)
                Text(result.answer)
                if (MarkedScreenshotView.privateImage(context, result.sourceScreenshot) != null)
                    OutlinedButton(onClick = { sourceOpen = true }) { Text("查看来源截图（第 ${result.sourceStep} 步）") }
                else Text("模型未提供有效的来源截图，请核对答案")
            }
            Row {
                FilterChip(selected = positive == true, onClick = { positive = true; saved = false }, label = { Text("完成得好") })
                Spacer(Modifier.width(8.dp))
                FilterChip(selected = positive == false, onClick = { positive = false; saved = false }, label = { Text("没完成好") })
            }
            OutlinedTextField(value = comment, onValueChange = { comment = it.take(4000); saved = false },
                label = { Text("补充评价（选填）") }, modifier = Modifier.fillMaxWidth())
            TextButton(enabled = positive != null, onClick = {
                val vote = positive ?: return@TextButton
                val text = comment
                scope.launch {
                    error = withContext(Dispatchers.IO) { runCatching {
                        store.saveFeedback(result.taskId, vote, text)
                    }.exceptionOrNull()?.let { "暂时无法保存评价，请重试" } }
                    saved = error == null
                }
            }) { Text(if (saved) "评价已保存，可修改" else "保存评价") }
            Text("评价仅保存在本机，不上传轨迹或截图", style = MaterialTheme.typography.bodySmall)
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
    if (sourceOpen) AlertDialog(onDismissRequest = { sourceOpen = false }, title = { Text("答案来源 · 第 ${result.sourceStep} 步") },
        text = { AndroidView(factory = { MarkedScreenshotView(it) }, update = { it.setSource(result.sourceScreenshot) },
            modifier = Modifier.fillMaxWidth().height(430.dp)) }, confirmButton = {
            TextButton(onClick = { sourceOpen = false }) { Text("关闭") }
        })
}

@Composable
fun ResultDetails(result: TaskResult, onBack: () -> Unit) {
    Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding().padding(16.dp).verticalScroll(rememberScrollState())) {
        TextButton(onClick = onBack) { Text("返回任务页") }
        ResultCard(result)
    }
}
