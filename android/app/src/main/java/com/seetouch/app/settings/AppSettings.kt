package com.seetouch.app.settings

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONObject
import java.net.URI

/** 新安装使用通用接口；已有豆包配置保留原服务和思考设置。 */
class AppSettings internal constructor(private val prefs: SharedPreferences) {
    constructor(context: Context) : this(
        context.getSharedPreferences("seetouch_settings", Context.MODE_PRIVATE),
    )

    var reasoner: String
        get() = prefs.getString("reasoner", null)
            ?: if (listOf("doubao_api_key", "doubao_model_id", "doubao_base_url", "thinking_mode")
                .any(prefs::contains))
                "doubao" else "openai"
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

    var apiMode: String
        get() = prefs.getString("openai_api_mode", "chat_completions").orEmpty()
        set(value) = prefs.edit().putString("openai_api_mode", value).apply()

    var timeoutSeconds: Int
        get() = prefs.getInt("openai_timeout_seconds", 60)
        set(value) = prefs.edit().putInt("openai_timeout_seconds", value).apply()

    fun connectionError(): String? = validateConnection(
        reasoner, apiKey, baseUrl, modelId, apiMode, timeoutSeconds,
    )

    /** 一次性保存选中服务，避免凭据、地址和后端出现中间不一致状态。 */
    fun saveConnection(
        provider: String, key: String, url: String, model: String,
        mode: String, timeout: Int, thinking: String, effort: String, steps: Int,
    ) {
        require(validateConnection(provider, key, url, model, mode, timeout) == null)
        require(steps in 1..200)
        require(if (provider == "doubao") thinking in setOf("enabled", "disabled", "auto")
            else effort in setOf("", "none", "minimal", "low", "medium", "high", "xhigh"))
        val editor = prefs.edit()
            .putString("reasoner", provider)
            .putString("${provider}_api_key", key.trim())
            .putString("${provider}_base_url", url.trim().trimEnd('/'))
            .putString("${provider}_model_id", model.trim())
            .putInt("max_steps", steps)
        if (provider == "doubao") {
            editor.putString("thinking_mode", thinking)
        } else {
            editor.putString("openai_api_mode", mode)
                .putInt("openai_timeout_seconds", timeout)
                .putString("reasoning_effort", effort)
        }
        editor.apply()
    }

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
                put("api_mode", apiMode)
                put("timeout", timeoutSeconds)
            }
        }.toString()

    companion object {
        fun connectionConfigJson(provider: String, key: String, url: String, model: String,
            mode: String, timeout: Int, thinking: String, effort: String): String = JSONObject()
            .put("reasoner", provider).put("api_key", key.trim()).put("model_id", model.trim())
            .apply {
                if (provider == "doubao") {
                    put("api_url", url.trim().trimEnd('/')); put("thinking_mode", thinking)
                } else {
                    put("base_url", url.trim().trimEnd('/')); put("api_mode", mode)
                    put("timeout", timeout); put("reasoning_effort", effort)
                }
            }.toString()

        fun validateConnection(
            provider: String, key: String, url: String, model: String,
            mode: String, timeout: Int,
        ): String? {
            if (provider !in setOf("doubao", "openai")) return "请选择有效的服务类型"
            if (key.isBlank()) return "请填写 API Key"
            val base = url.trim().trimEnd('/')
            val uri = try { URI(base) } catch (_: Exception) { null }
            if (uri == null || uri.scheme !in setOf("https", "http") || uri.host.isNullOrBlank())
                return "请填写完整的 http:// 或 https:// 基础地址"
            if (uri.userInfo != null || uri.query != null || uri.fragment != null)
                return "基础地址不能包含账号密码、查询参数或片段"
            if (uri.port != -1 && uri.port !in 1..65535) return "基础地址端口应为 1–65535"
            if (base.endsWith("/chat/completions") || base.endsWith("/responses"))
                return "请填写基础地址，去掉末尾的 /chat/completions 或 /responses"
            if (provider == "openai") {
                if (model.isBlank()) return "请填写支持图片输入的模型 ID"
                if (mode !in setOf("chat_completions", "responses")) return "请选择接口协议"
                if (timeout !in 5..600) return "请求超时应为 5–600 秒"
            }
            return null
        }
    }
}
