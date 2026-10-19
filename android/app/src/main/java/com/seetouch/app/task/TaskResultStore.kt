package com.seetouch.app.task

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/** App-private result and feedback storage. No network or screenshot submission code. */
class TaskResultStore(private val directory: File) {
    constructor(context: Context) : this(File(context.filesDir, "results"))
    init { directory.mkdirs() }
    @Synchronized fun save(result: TaskResult) {
        write(file(result.taskId), result.toJson())
        write(File(directory, "latest.json"), JSONObject().put("task_id", result.taskId))
    }
    @Synchronized fun load(id: String): TaskResult? = runCatching {
        TaskResult.fromJson(JSONObject(file(id).readText()))
    }.getOrNull()
    fun latest(): TaskResult? = runCatching { load(JSONObject(File(directory, "latest.json").readText()).getString("task_id")) }.getOrNull()
    @Synchronized fun feedback(id: String): JSONObject? = runCatching {
        JSONObject(file("${id}_feedback").readText())
    }.getOrNull()
    @Synchronized fun saveFeedback(id: String, positive: Boolean, comment: String) {
        require(load(id) != null)
        write(file("${id}_feedback"), JSONObject().put("task_id", id).put("positive", positive)
            .put("comment", comment.take(4000)).put("updated_at", System.currentTimeMillis()))
    }
    private fun file(id: String): File {
        require(id.matches(Regex("[A-Za-z0-9_-]{1,120}"))) { "Invalid result identifier" }
        return File(directory, "$id.json")
    }
    private fun write(target: File, json: JSONObject) = synchronized(WRITE_LOCK) {
        val pending = File(directory, target.name + ".tmp")
        pending.writeText(json.toString(), Charsets.UTF_8)
        Files.move(pending.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING,
            StandardCopyOption.ATOMIC_MOVE)
    }
    companion object { private val WRITE_LOCK = Any() }
}
