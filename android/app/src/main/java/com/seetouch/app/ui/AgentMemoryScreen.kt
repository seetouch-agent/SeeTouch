package com.seetouch.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.seetouch.app.task.AgentMemory
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

private val categories = linkedMapOf("address" to "常用地址", "contact" to "联系人称呼",
    "platform" to "偏好平台", "preference" to "个人偏好", "procedure" to "操作经验")

@Composable
fun AgentMemoryScreen(onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var snapshot by remember { mutableStateOf(JSONObject()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var editor by remember { mutableStateOf<JSONObject?>(null) }
    var deleteId by remember { mutableStateOf<String?>(null) }
    fun perform(operation: String, payload: JSONObject = JSONObject()) {
        busy = true; error = null
        scope.launch {
            runCatching { AgentMemory.command(operation, payload) }
                .onSuccess { snapshot = it; editor = null }
                .onFailure { error = "记忆操作失败，请检查输入、敏感凭据或本地存储后重试" }
            busy = false
        }
    }
    LaunchedEffect(Unit) { perform("list") }
    val entries = snapshot.optJSONArray("entries")?.let { a ->
        (0 until a.length()).map { a.getJSONObject(it) }.sortedByDescending { it.optDouble("updated_at") }
    } ?: emptyList()
    LazyColumn(Modifier.fillMaxSize().safeDrawingPadding().imePadding().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row { TextButton(onClick = onBack) { Text("返回") }; Text("记忆与经验", style = MaterialTheme.typography.headlineSmall) }
            Text("条目保存在本机；与任务相关的条目会随推理请求发送给你配置的模型服务。")
            Row {
                Switch(snapshot.optBoolean("enabled", true), enabled = !busy && snapshot.has("enabled"), onCheckedChange = {
                    perform("configure", JSONObject().put("enabled", it).put("learning_enabled", snapshot.optBoolean("learning_enabled", true)))
                }); Text("使用本地记忆")
            }
            Row {
                Switch(snapshot.optBoolean("learning_enabled", true), enabled = !busy && snapshot.optBoolean("enabled", false), onCheckedChange = {
                    perform("configure", JSONObject().put("enabled", true).put("learning_enabled", it))
                }); Text("任务完成后自动积累经验")
            }
            Text("经验由任务结束时的模型响应提炼，不额外调用模型。每一步仍观察当前屏幕；差评会暂停相关经验的自动复用。")
            Text("关闭记忆后停止加载和积累，已有条目保留。地址、联系人等建议须确认后才保存。")
            Row {
                OutlinedButton(enabled = !busy, onClick = { editor = JSONObject() }) { Text("新增") }
                TextButton(enabled = !busy, onClick = { perform("list") }) { Text("刷新") }
                TextButton(enabled = !busy && (entries.isNotEmpty() || error != null), onClick = { deleteId = "all" }) { Text("清空") }
            }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (!busy && entries.isEmpty()) Text("还没有记忆。可手动添加偏好，或完成任务后积累经验。")
        }
        items(entries, key = { it.getString("id") }) { entry ->
            val reviews = entry.optJSONObject("reviews")
            val unsuitable = reviews?.keys()?.asSequence()?.any { !reviews.optBoolean(it, true) } == true
            val enabled = entry.optBoolean("enabled", true) && !unsuitable
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(entry.getString("name"), style = MaterialTheme.typography.titleMedium)
                    Text("${categories[entry.optString("category")] ?: "记忆"} · ${if (enabled) "可复用" else "已停用"}")
                    Text(entry.getString("content"))
                    val words = entry.optJSONArray("keywords")
                    if (words != null && words.length() > 0) Text("关联词：" + (0 until words.length()).joinToString("、") { words.getString(it) })
                    Text(when (entry.optString("source")) {
                        "learned" -> "由模型报告完成的任务提炼 · ${entry.optJSONArray("source_tasks")?.length() ?: 0} 条来源；仍需实际核对"
                        "suggested" -> "模型建议，已由你确认保存"
                        else -> "手动维护"
                    }, style = MaterialTheme.typography.bodySmall)
                    Row {
                        TextButton(enabled = !busy, onClick = { editor = entry }) { Text("编辑") }
                        TextButton(enabled = !busy, onClick = { perform("enabled", JSONObject().put("id", entry.getString("id")).put("enabled", !enabled)) }) {
                            Text(if (enabled) "停用" else "重新启用")
                        }
                        TextButton(enabled = !busy, onClick = { deleteId = entry.getString("id") }) { Text("删除") }
                    }
                }
            }
        }
    }
    editor?.let { entry -> MemoryEditor(entry, busy, error, { editor = null }, { perform("save", it) }) }
    deleteId?.let { id -> AlertDialog(onDismissRequest = { deleteId = null }, title = { Text(if (id == "all") "清空全部记忆？" else "删除这条记忆？") },
        text = { Text("删除后后续任务将不再加载这些条目。") }, confirmButton = {
            TextButton(onClick = { deleteId = null; perform(if (id == "all") "clear" else "remove", JSONObject().put("id", id)) }) { Text("删除") }
        }, dismissButton = { TextButton(onClick = { deleteId = null }) { Text("取消") } }) }
}

@Composable
private fun MemoryEditor(entry: JSONObject, busy: Boolean, error: String?, onCancel: () -> Unit, onSave: (JSONObject) -> Unit) {
    var name by remember(entry) { mutableStateOf(entry.optString("name")) }
    var content by remember(entry) { mutableStateOf(entry.optString("content")) }
    var category by remember(entry) { mutableStateOf(entry.optString("category", "preference")) }
    var words by remember(entry) { mutableStateOf(entry.optJSONArray("keywords")?.let { a -> (0 until a.length()).joinToString("，") { a.getString(it) } } ?: "") }
    AlertDialog(onDismissRequest = { if (!busy) onCancel() }, title = { Text("编辑记忆") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            categories.forEach { (value, label) -> Row { RadioButton(category == value, onClick = { category = value }); Text(label) } }
            OutlinedTextField(name, { name = it.take(80) }, label = { Text("名称（如：家）") })
            OutlinedTextField(content, { content = it.take(1800) }, label = { Text("内容") })
            OutlinedTextField(words, { words = it.take(400) }, label = { Text("关联词，以逗号分隔") })
            Text("如“回家、导航”；禁止保存密码、验证码、密钥和支付凭据。")
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }, confirmButton = {
        TextButton(enabled = !busy && name.isNotBlank() && content.isNotBlank(), onClick = {
            val payload = JSONObject().put("name", name).put("content", content).put("category", category)
                .put("keywords", JSONArray(words.split(',', '，', '\n').map { it.trim() }.filter { it.isNotEmpty() }))
            if (entry.has("id")) payload.put("id", entry.getString("id"))
            onSave(payload)
        }) { Text("保存") }
    }, dismissButton = { TextButton(enabled = !busy, onClick = onCancel) { Text("取消") } })
}

@Composable
fun MemoryResultSection(result: com.seetouch.app.task.TaskResult) {
    val scope = rememberCoroutineScope()
    var notice by remember(result.taskId) { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    val suggestions = remember(result.memorySuggestions) { runCatching { JSONArray(result.memorySuggestions) }.getOrDefault(JSONArray()) }
    Text("本次匹配 ${result.usedMemoryIds.size} 条记忆；" + when (result.learningStatus) {
        "saved" -> "已积累本次操作经验"
        "error" -> "经验保存失败，任务结果已保留"
        "skipped" -> "本次未生成可保存的经验"
        else -> "自动积累已关闭或未进行"
    }, style = MaterialTheme.typography.bodySmall)
    for (i in 0 until suggestions.length()) {
        val suggestion = suggestions.optJSONObject(i) ?: continue
        Text("要记住这个偏好吗？${suggestion.optString("name")}：${suggestion.optString("content")}")
        TextButton(enabled = !saving, onClick = {
            saving = true
            scope.launch {
                notice = runCatching { AgentMemory.command("confirm_suggestion", JSONObject(suggestion.toString()).put("task_id", result.taskId)) }
                    .fold({ "已确认保存；可在记忆页编辑或删除" }, { "未能保存，请检查记忆开关与内容后重试" })
                saving = false
            }
        }) { Text("确认保存这条偏好") }
    }
    notice?.let { Text(it) }
}
