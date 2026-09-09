package com.seetouch.app.diag

import android.app.Activity
import android.os.Bundle
import android.util.Log
import com.chaquo.python.Python
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * 无 UI 任务执行入口(Phase 1 诊断用),由 ADB 触发:
 *
 *   adb shell am start -n com.seetouch.app/.diag.TaskRunActivity \
 *       --es instruction "打开设置" --es api_key "<API_KEY>" \
 *       --es base_url "https://api.openai.com/v1" --es model_id "gpt-4.1-mini"
 *
 * 前置条件:已在系统设置中启用 SeeTouch 无障碍服务。
 * 每步进度与最终结果打到 logcat tag SEETOUCH_RUN。
 */
class TaskRunActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val instruction = intent.getStringExtra("instruction") ?: "打开设置"
        val apiKey = intent.getStringExtra("api_key").orEmpty()
        val configJson = JSONObject()
            .put("api_key", apiKey)
            .put(
                "base_url",
                intent.getStringExtra("base_url") ?: "https://api.openai.com/v1",
            )
            .put("model_id", intent.getStringExtra("model_id") ?: "gpt-4.1-mini")
            .put("reasoning_effort", intent.getStringExtra("reasoning_effort").orEmpty())
            .put("max_steps", intent.getIntExtra("max_steps", 20))
            .toString()

        thread(name = "seetouch-task") {
            try {
                Log.i(TAG, "task start: $instruction")
                val result = Python.getInstance()
                    .getModule("seetouchapp.task_entry")
                    .callAttr(
                        "run_task", instruction, configJson,
                        { stepJson: String -> Log.i(TAG, "step: $stepJson"); Unit },
                        null,
                    )
                    .toString()
                Log.i(TAG, "result: $result")
            } catch (t: Throwable) {
                Log.e(TAG, "task crashed", t)
            }
        }
        // 立刻退出 Activity,把前台让给被操作的目标 app;任务线程继续运行
        finish()
    }

    companion object {
        const val TAG = "SEETOUCH_RUN"
    }
}
