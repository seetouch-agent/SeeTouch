package com.seetouch.app.ui

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.seetouch.app.device.SeeTouchAccessibilityService
import com.seetouch.app.settings.AppSettings
import com.seetouch.app.task.StepInfo
import com.seetouch.app.task.TaskController
import com.seetouch.app.task.TaskExecutionService
import com.seetouch.app.task.TaskStatus
import com.seetouch.app.task.TaskUiState

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val settings = AppSettings(this)
        setContent {
            MaterialTheme {
                SeeTouchApp(settings)
            }
        }
    }
}

@Composable
private fun SeeTouchApp(settings: AppSettings) {
    var showSettings by remember { mutableStateOf(false) }
    if (showSettings) {
        SettingsScreen(settings, onBack = { showSettings = false })
    } else {
        TaskScreen(settings, onOpenSettings = { showSettings = true })
    }
}

// ============================ 任务页 ============================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TaskScreen(settings: AppSettings, onOpenSettings: () -> Unit) {
    val context = LocalContext.current
    val state by TaskController.state.collectAsState()
    var instruction by remember { mutableStateOf("") }
    var warning by remember { mutableStateOf<String?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("SeeTouch") },
                actions = {
                    IconButton(onClick = onOpenSettings) {
                        Icon(Icons.Default.Settings, contentDescription = "设置")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
        ) {
            OutlinedTextField(
                value = instruction,
                onValueChange = { instruction = it },
                label = { Text("要手机做什么？例如：在哔哩哔哩搜索采莲曲") },
                modifier = Modifier.fillMaxWidth(),
                enabled = state.status != TaskStatus.RUNNING,
                minLines = 2,
            )
            Spacer(Modifier.height(12.dp))
            Button(
                onClick = {
                    warning = null
                    when {
                        instruction.isBlank() -> warning = "请输入任务指令"
                        settings.apiKey.isBlank() ->
                            warning = "请先在设置页填入 OpenAI 兼容 API key"
                        settings.modelId.isBlank() -> warning = "请先在设置页填写模型 ID"
                        SeeTouchAccessibilityService.instance == null ->
                            warning = "请先开启 SeeTouch 无障碍服务（点下方按钮跳转）"
                        else -> {
                            TaskController.resetIfFinished()
                            TaskExecutionService.start(
                                context, instruction.trim(), settings.toTaskConfigJson()
                            )
                        }
                    }
                },
                enabled = state.status != TaskStatus.RUNNING,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (state.status == TaskStatus.RUNNING) "执行中…" else "开始执行")
            }
            warning?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = MaterialTheme.colorScheme.error)
            }
            if (SeeTouchAccessibilityService.instance == null) {
                Spacer(Modifier.height(8.dp))
                OutlinedButton(
                    onClick = {
                        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("去开启无障碍服务") }
            }

            Spacer(Modifier.height(16.dp))
            HorizontalDivider()
            Spacer(Modifier.height(8.dp))
            StatusLine(state)
            Spacer(Modifier.height(8.dp))
            StepTimeline(state.steps)
        }
    }

    state.pendingConfirmation?.let { pending ->
        AlertDialog(
            onDismissRequest = { /* 必须显式选择 */ },
            title = { Text("敏感动作待确认") },
            text = { Text(pending.message) },
            confirmButton = {
                TextButton(onClick = { TaskController.respondToConfirmation(true) }) {
                    Text("允许执行")
                }
            },
            dismissButton = {
                TextButton(onClick = { TaskController.respondToConfirmation(false) }) {
                    Text("拒绝")
                }
            },
        )
    }
}

@Composable
private fun StatusLine(state: TaskUiState) {
    val text = when (state.status) {
        TaskStatus.IDLE -> "就绪"
        TaskStatus.RUNNING -> "执行中：${state.instruction}"
        TaskStatus.COMPLETED -> state.resultSummary ?: "任务完成"
        TaskStatus.ABORTED -> state.resultSummary ?: "任务中止"
        TaskStatus.ERROR -> "出错：${state.errorDetail?.take(300)}"
    }
    val color = when (state.status) {
        TaskStatus.ERROR, TaskStatus.ABORTED -> MaterialTheme.colorScheme.error
        else -> MaterialTheme.colorScheme.onSurface
    }
    Text(text, color = color, style = MaterialTheme.typography.bodyMedium)
}

@Composable
private fun StepTimeline(steps: List<StepInfo>) {
    val listState = rememberLazyListState()
    LaunchedEffect(steps.size) {
        if (steps.isNotEmpty()) listState.animateScrollToItem(steps.size - 1)
    }
    LazyColumn(
        state = listState,
        verticalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        items(steps, key = { it.step }) { step -> StepCard(step) }
    }
}

@Composable
private fun StepCard(step: StepInfo) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row {
                Text(
                    "步骤 ${step.step}",
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    step.action + if (step.success == false) "（失败）" else "",
                    color = if (step.success == false) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.weight(1f))
                Text(
                    "${step.reasoningTime}s",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
            if (step.actionSummary.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(step.actionSummary, style = MaterialTheme.typography.bodySmall)
            }
            if (step.screenSummary.isNotBlank()) {
                Text(
                    step.screenSummary,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
            step.notes.forEach { note ->
                Text(
                    note,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary,
                )
            }
        }
    }
}

// ============================ 设置页 ============================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingsScreen(settings: AppSettings, onBack: () -> Unit) {
    var apiKey by remember { mutableStateOf(settings.apiKey) }
    var baseUrl by remember { mutableStateOf(settings.baseUrl) }
    var modelId by remember { mutableStateOf(settings.modelId) }
    var reasoningEffort by remember { mutableStateOf(settings.reasoningEffort) }
    var maxSteps by remember { mutableStateOf(settings.maxSteps.toString()) }
    var saved by remember { mutableStateOf(false) }
    val reasoningOptions = listOf(
        "" to "模型默认",
        "minimal" to "极低",
        "low" to "低",
        "medium" to "中",
        "high" to "高",
        "xhigh" to "极高",
    )

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("设置") },
                navigationIcon = {
                    TextButton(onClick = onBack) { Text("返回") }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it; saved = false },
                label = { Text("OpenAI 兼容 API Key") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = baseUrl,
                onValueChange = { baseUrl = it; saved = false },
                label = { Text("API Base URL") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = modelId,
                onValueChange = { modelId = it; saved = false },
                label = { Text("模型 ID") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = maxSteps,
                onValueChange = { maxSteps = it.filter(Char::isDigit); saved = false },
                label = { Text("最大步数") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(Modifier.height(12.dp))
            Text("思考强度（模型不支持时请选择“模型默认”）")
            reasoningOptions.forEach { (value, label) ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(
                        selected = reasoningEffort == value,
                        onClick = { reasoningEffort = value; saved = false },
                    )
                    Text(label)
                }
            }
            Spacer(Modifier.height(12.dp))
            Button(
                onClick = {
                    settings.apiKey = apiKey
                    settings.baseUrl = baseUrl
                    settings.modelId = modelId
                    settings.reasoningEffort = reasoningEffort
                    settings.maxSteps = maxSteps.toIntOrNull()?.coerceIn(1, 200) ?: 45
                    saved = true
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("保存") }
            if (saved) {
                Spacer(Modifier.height(8.dp))
                Text("已保存", color = MaterialTheme.colorScheme.primary)
            }
        }
    }
}
