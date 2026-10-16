package com.seetouch.app.settings

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONObject

/** 各后端分别存储凭据；未选择后端的旧配置继续使用豆包。 */
class AppSettings internal constructor(private val prefs: SharedPreferences) {
    constructor(context: Context) : this(
        context.getSharedPreferences("seetouch_settings", Context.MODE_PRIVATE),
    )

    var reasoner: String
        get() = prefs.getString("reasoner", "doubao").orEmpty()
        set(value) {
            require(value in setOf("doubao", "openai"))
            prefs.edit().putString("reasoner", value).apply()
        }

    fun apiKeyFor(provider: String): String =
        prefs.getString("${provider}_api_key", "").orEmpty()

    fun baseUrlFor(provider: String): String =
        prefs.getString("${provider}_base_url", if (provider == "doubao")
            "https://ark.cn-beijing.volces.com/api/v3" else "https://api.openai.com/v1").orEmpty()

    fun modelIdFor(provider: String): String =
        prefs.getString("${provider}_model_id", "").orEmpty()

    var apiKey: String
        get() = apiKeyFor(reasoner)
        set(value) = prefs.edit().putString("${reasoner}_api_key", value.trim()).apply()

    var baseUrl: String
        get() = baseUrlFor(reasoner)
        set(value) = prefs.edit().putString("${reasoner}_base_url", value.trim().trimEnd('/')).apply()

    var modelId: String
        get() = modelIdFor(reasoner)
        set(value) = prefs.edit().putString("${reasoner}_model_id", value.trim()).apply()

    /** 保留旧版本用户选择，不转换为 reasoning_effort。 */
    var thinkingMode: String
        get() = prefs.getString("thinking_mode", "enabled").orEmpty()
        set(value) = prefs.edit().putString("thinking_mode", value).apply()

    var reasoningEffort: String
        get() = prefs.getString("reasoning_effort", "").orEmpty()
        set(value) = prefs.edit().putString("reasoning_effort", value).apply()

    var maxSteps: Int
        get() = prefs.getInt("max_steps", 45)
        set(value) = prefs.edit().putInt("max_steps", value).apply()

    fun toTaskConfigJson(): String = JSONObject()
        .put("reasoner", reasoner)
        .put("api_key", apiKey)
        .put("model_id", modelId)
        .put("max_steps", maxSteps)
        .apply {
            if (reasoner == "doubao") {
                put("api_url", baseUrl)
                put("thinking_mode", thinkingMode)
            } else {
                put("base_url", baseUrl)
                put("reasoning_effort", reasoningEffort)
            }
        }.toString()
}
