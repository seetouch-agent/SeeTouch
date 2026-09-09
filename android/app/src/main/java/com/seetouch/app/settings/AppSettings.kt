package com.seetouch.app.settings

import android.content.Context
import org.json.JSONObject

/** 轻量配置存取,与 PC 端 .env 的可配置项对齐。 */
class AppSettings(context: Context) {

    private val prefs =
        context.getSharedPreferences("seetouch_settings", Context.MODE_PRIVATE)

    var apiKey: String
        get() = prefs.getString(KEY_API_KEY, null)
            ?: prefs.getString(LEGACY_KEY_API_KEY, "").orEmpty()
        set(value) = prefs.edit().putString(KEY_API_KEY, value.trim()).apply()

    var baseUrl: String
        get() = prefs.getString(KEY_BASE_URL, null)
            ?: if (hasLegacyDoubaoConfig()) DEFAULT_DOUBAO_BASE_URL else DEFAULT_BASE_URL
        set(value) = prefs.edit().putString(KEY_BASE_URL, value.trim().trimEnd('/')).apply()

    var modelId: String
        get() {
            val current = prefs.getString(KEY_MODEL_ID, null)
            if (current != null) return current
            val legacy = prefs.getString(LEGACY_KEY_MODEL_ID, "").orEmpty()
            return legacy.ifBlank {
                if (hasLegacyDoubaoConfig()) DEFAULT_DOUBAO_MODEL_ID else DEFAULT_MODEL_ID
            }
        }
        set(value) = prefs.edit().putString(KEY_MODEL_ID, value.trim()).apply()

    /** 空串 = 使用模型默认；其余值按 OpenAI reasoning_effort 发送。 */
    var reasoningEffort: String
        get() = prefs.getString(KEY_REASONING_EFFORT, "").orEmpty()
        set(value) = prefs.edit().putString(KEY_REASONING_EFFORT, value).apply()

    var maxSteps: Int
        get() = prefs.getInt(KEY_MAX_STEPS, 45)
        set(value) = prefs.edit().putInt(KEY_MAX_STEPS, value).apply()

    /** 组装 task_entry.run_task 需要的运行配置 JSON。 */
    fun toTaskConfigJson(): String =
        JSONObject()
            .put("api_key", apiKey)
            .put("base_url", baseUrl)
            .put("model_id", modelId)
            .put("reasoning_effort", reasoningEffort)
            .put("max_steps", maxSteps)
            .toString()

    private fun hasLegacyDoubaoConfig(): Boolean =
        !prefs.contains(KEY_API_KEY) &&
            !prefs.getString(LEGACY_KEY_API_KEY, "").isNullOrBlank()

    companion object {
        private const val DEFAULT_BASE_URL = "https://api.openai.com/v1"
        private const val DEFAULT_MODEL_ID = "gpt-4.1-mini"
        private const val DEFAULT_DOUBAO_BASE_URL =
            "https://ark.cn-beijing.volces.com/api/v3"
        private const val DEFAULT_DOUBAO_MODEL_ID = "doubao-seed-1-6-vision-250815"
        private const val KEY_API_KEY = "openai_api_key"
        private const val KEY_BASE_URL = "openai_base_url"
        private const val KEY_MODEL_ID = "openai_model_id"
        private const val KEY_REASONING_EFFORT = "reasoning_effort"
        private const val KEY_MAX_STEPS = "max_steps"
        private const val LEGACY_KEY_API_KEY = "doubao_api_key"
        private const val LEGACY_KEY_MODEL_ID = "doubao_model_id"
    }
}
