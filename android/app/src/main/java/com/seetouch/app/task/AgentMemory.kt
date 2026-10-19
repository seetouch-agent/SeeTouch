package com.seetouch.app.task

import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** UI calls are off the main thread; Python owns validation, atomic writes and retrieval. */
object AgentMemory {
    suspend fun command(operation: String, payload: JSONObject = JSONObject()): JSONObject = withContext(Dispatchers.IO) {
        val result = JSONObject(Python.getInstance().getModule("seetouchapp.memory_entry")
            .callAttr("command", operation, payload.toString()).toString())
        check(result.optBoolean("ok")) { result.optString("error", "记忆操作失败") }
        result
    }
}
