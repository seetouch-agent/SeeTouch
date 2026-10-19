package com.seetouch.app.ui

import android.content.Intent
import androidx.compose.material3.Switch
import com.seetouch.app.task.TaskResult
import com.seetouch.app.task.TaskResultStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.lang.ref.WeakReference
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
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.seetouch.app.device.SeeTouchAccessibilityService
import com.seetouch.app.settings.AppSettings
import com.seetouch.app.task.StepInfo
import com.seetouch.app.task.TaskController
import com.seetouch.app.task.TaskExecutionService
import com.seetouch.app.task.TaskStatus
import com.seetouch.app.task.TaskUiState
import com.seetouch.app.task.TaskProgressDisplay

class MainActivity : ComponentActivity() {
    private var requestedResultId by mutableStateOf<String?>(null)

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent)
        requestedResultId = intent.getStringExtra(EXTRA_RESULT_ID)
        val state = TaskController.state.value
        if (state.workerActive && state.status == TaskStatus.RUNNING && state.pendingConfirmation == null) TaskController.pause()
    }

    override fun onStart() {
        super.onStart()
        visibleActivity = WeakReference(this)
        val state = TaskController.state.value
        if (state.workerActive && state.status == TaskStatus.RUNNING && state.pendingConfirmation == null) TaskController.pause()
    }

    override fun onStop() {
        if (visibleActivity?.get() === this) visibleActivity = null
        super.onStop()
    }

    companion object {
        const val EXTRA_RESULT_ID = "result_task_id"
        private var visibleActivity: WeakReference<MainActivity>? = null
        fun hideIfVisible() { visibleActivity?.get()?.moveTaskToBack(true) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val settings = AppSettings(this)
        requestedResultId = intent.getStringExtra(EXTRA_RESULT_ID)
        setContent {
            MaterialTheme {
                SeeTouchApp(settings, requestedResultId) { requestedResultId = null }
            }
        }
    }
}

@Composable
private fun SeeTouchApp(settings: AppSettings, requestedId: String?, onHandled: () -> Unit) {
    var showSettings by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<TaskResult?>(null) }
    var lastResultId by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current
    val state by TaskController.state.collectAsState()
    LaunchedEffect(requestedId) {
        if (requestedId != null) {
            result = state.result?.takeIf { it.taskId == requestedId }
                ?: withContext(Dispatchers.IO) { TaskResultStore(context).load(requestedId) }
            showSettings = false
            onHandled()
        }
    }
    LaunchedEffect(state.result) {
        val updated = state.result
        if (state.taskGeneration > 0 && updated != null) {
            if (result?.taskId == updated.taskId || lastResultId != updated.taskId) {
                result = updated; showSettings = false
            }
            lastResultId = updated.taskId
        }
    }
    when {
        result != null -> Column { TaskInteractionControls(state); ResultDetails(result!!) { result = null } }
        showSettings -> Column(Modifier.safeDrawingPadding()) { TaskInteractionControls(state); SettingsScreen(settings) { showSettings = false } }
        else -> TaskScreen(settings, { showSettings = true }, { result = it })
    }
    state.pendingConfirmation?.let { ConfirmationCard(it) }
}

// ============================ 任务页 ============================

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TaskScreen(settings: AppSettings, onOpenSettings: () -> Unit, onOpenResult: (TaskResult) -> Unit) {
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
            Text(
                if (settings.modelId.isNotBlank()) "当前模型：${settings.modelId}"
                else if (settings.reasoner == "doubao") "当前服务：豆包（默认模型）"
                else "请先在设置中添加模型服务",
                style = MaterialTheme.typography.bodyMedium,
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = instruction,
                onValueChange = { instruction = it },
                label = { Text("要手机做什么？例如：在哔哩哔哩搜索采莲曲") },
                modifier = Modifier.fillMaxWidth(),
                enabled = !state.workerActive,
                minLines = 2,
            )
            Spacer(Modifier.height(12.dp))
            Button(
                onClick = {
                    warning = null
                    val configError = settings.connectionError()
                    when {
                        instruction.isBlank() -> warning = "请输入任务指令"
                        configError != null -> warning = "请检查设置：$configError"
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
                enabled = !state.workerActive,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (state.workerActive) "任务处理中…" else "开始执行")
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
            state.result?.let { result -> TextButton(onClick = { onOpenResult(result) }) { Text("查看任务结果") } }
            TaskInteractionControls(state)
            Spacer(Modifier.height(8.dp))
            StepTimeline(state.steps)
        }
    }


}

@Composable
private fun StatusLine(state: TaskUiState) {
    val text = when (state.status) {
        TaskStatus.IDLE -> "就绪"
        TaskStatus.RUNNING -> "${TaskProgressDisplay.from(state).title}：${state.instruction}"
        TaskStatus.PAUSED, TaskStatus.WAITING_USER, TaskStatus.TAKEOVER ->
            "${TaskProgressDisplay.from(state).title}：${TaskProgressDisplay.from(state).detail}"
        TaskStatus.STOPPED -> state.resultSummary ?: "已终止"
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
    var reasoner by remember { mutableStateOf(settings.reasoner) }
    var apiKey by remember { mutableStateOf(settings.apiKey) }
    var baseUrl by remember { mutableStateOf(settings.baseUrl) }
    var modelId by remember { mutableStateOf(settings.modelId) }
    var reasoningEffort by remember { mutableStateOf(settings.reasoningEffort) }
    var thinkingMode by remember { mutableStateOf(settings.thinkingMode) }
    var maxSteps by remember { mutableStateOf(settings.maxSteps.toString()) }
    var apiMode by remember { mutableStateOf(settings.apiMode) }
    var timeoutSeconds by remember { mutableStateOf(settings.timeoutSeconds.toString()) }
    var showKey by remember(reasoner) { mutableStateOf(false) }
    var showAdvanced by remember { mutableStateOf(false) }
    var saveError by remember { mutableStateOf<String?>(null) }
    var saved by remember { mutableStateOf(false) }
    var confirmationTimeout by remember { mutableStateOf(settings.confirmationTimeout.toString()) }
    var speakResults by remember { mutableStateOf(settings.speakResults) }
    var floatingEntry by remember { mutableStateOf(settings.floatingEntryEnabled) }
    val reasoningOptions = listOf(
        "" to "模型默认",
        "none" to "关闭（需模型支持）",
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
            Text("模型服务", style = MaterialTheme.typography.titleMedium)
            Text("填写服务商提供的地址、密钥和支持图片输入的模型。")
            listOf("openai" to "OpenAI 兼容服务", "doubao" to "豆包专用配置").forEach { (value, label) ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(
                        selected = reasoner == value,
                        onClick = {
                            if (reasoner == value) return@RadioButton
                            reasoner = value
                            apiKey = settings.apiKeyFor(value)
                            baseUrl = settings.baseUrlFor(value)
                            modelId = settings.modelIdFor(value)
                            saved = false
                            saveError = null
                        },
                    )
                    Text(label)
                }
            }
            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it; saved = false; saveError = null },
                label = { Text("API Key") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                visualTransformation = if (showKey) VisualTransformation.None
                    else PasswordVisualTransformation(),
                trailingIcon = {
                    TextButton(onClick = { showKey = !showKey }) {
                        Text(if (showKey) "隐藏" else "显示")
                    }
                },
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = baseUrl,
                onValueChange = { baseUrl = it; saved = false; saveError = null },
                label = { Text("API Base URL") },
                supportingText = { Text("例如 https://api.openai.com/v1，保留服务商要求的路径前缀") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(Modifier.height(12.dp))
            if (reasoner == "openai") {
                Text("接口协议")
                listOf("chat_completions" to "Chat Completions", "responses" to "Responses")
                    .forEach { (value, label) ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(
                                selected = apiMode == value,
                                onClick = { apiMode = value; saved = false; saveError = null },
                            )
                            Text(label)
                        }
                    }
                Text("按服务商说明选择；程序不会在失败后自动切换协议。")
            }
            OutlinedTextField(
                value = modelId,
                onValueChange = { modelId = it; saved = false; saveError = null },
                label = { Text(if (reasoner == "doubao") "模型 ID（留空用默认）" else "模型 ID") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(Modifier.height(12.dp))
            Text("浮窗与结果", style = MaterialTheme.typography.titleMedium)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = floatingEntry, onCheckedChange = {
                    floatingEntry = it; settings.floatingEntryEnabled = it
                    SeeTouchAccessibilityService.instance?.refreshFloatingEntry()
                })
                Text("显示悬浮球入口")
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = speakResults, onCheckedChange = {
                    speakResults = it; settings.speakResults = it
                    if (!it) com.seetouch.app.task.ResultSpeaker.stop()
                })
                Text("任务结束后语音播报")
            }
            OutlinedTextField(value = confirmationTimeout,
                onValueChange = { confirmationTimeout = it.filter(Char::isDigit); saved = false },
                label = { Text("敏感操作确认超时（秒）") },
                supportingText = { Text("默认 60 秒；可设置 10–600 秒，超时自动拒绝") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            TextButton(onClick = { showAdvanced = !showAdvanced }) {
                Text(if (showAdvanced) "收起高级设置" else "高级设置：思考强度、超时与步数")
            }
            if (showAdvanced) {
                OutlinedTextField(
                    value = maxSteps,
                    onValueChange = { maxSteps = it.filter(Char::isDigit); saved = false; saveError = null },
                    label = { Text("最大步数") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
                Spacer(Modifier.height(12.dp))
                if (reasoner == "doubao") {
                    Text("豆包深度思考")
                    listOf("enabled" to "开启", "disabled" to "关闭", "auto" to "自动（需模型支持）")
                        .forEach { (value, label) ->
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                RadioButton(
                                    selected = thinkingMode == value,
                                    onClick = { thinkingMode = value; saved = false; saveError = null },
                                )
                                Text(label)
                            }
                        }
                } else {
                    OutlinedTextField(
                        value = timeoutSeconds,
                        onValueChange = { timeoutSeconds = it.filter(Char::isDigit); saved = false; saveError = null },
                        label = { Text("每次请求超时（秒）") },
                        supportingText = { Text("5–600 秒；推理较慢的模型可适当增加") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    Spacer(Modifier.height(12.dp))
                    Text("思考强度（模型不支持时请选择“模型默认”）")
                    reasoningOptions.forEach { (value, label) ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(
                                selected = reasoningEffort == value,
                                onClick = { reasoningEffort = value; saved = false; saveError = null },
                            )
                            Text(label)
                        }
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            ConnectionTestButton(
                AppSettings.connectionConfigJson(reasoner, apiKey, baseUrl, modelId, apiMode,
                    timeoutSeconds.toIntOrNull() ?: 0, thinkingMode, reasoningEffort),
                AppSettings.validateConnection(reasoner, apiKey, baseUrl, modelId, apiMode,
                    timeoutSeconds.toIntOrNull() ?: 0),
            )
            Button(
                onClick = {
                    val timeout = if (reasoner == "openai") timeoutSeconds.toIntOrNull()
                        else settings.timeoutSeconds
                    val steps = maxSteps.toIntOrNull()
                    saveError = AppSettings.validateConnection(
                        reasoner, apiKey, baseUrl, modelId, apiMode, timeout ?: 0,
                    ) ?: if (steps == null || steps !in 1..200) "最大步数应为 1–200"
                    else if (confirmationTimeout.toIntOrNull()?.let { it !in 10..600 } != false) "确认超时应为 10–600 秒" else null
                    if (saveError == null && timeout != null && steps != null) {
                        settings.saveConnection(
                            reasoner, apiKey, baseUrl, modelId, apiMode, timeout,
                            thinkingMode, reasoningEffort, steps,
                        )
                        settings.confirmationTimeout = confirmationTimeout.toInt()
                        saved = true
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("保存") }
            saveError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (saved) {
                Spacer(Modifier.height(8.dp))
                Text("已保存", color = MaterialTheme.colorScheme.primary)
            }
        }
    }
}
