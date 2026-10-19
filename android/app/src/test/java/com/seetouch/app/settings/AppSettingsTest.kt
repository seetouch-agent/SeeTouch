package com.seetouch.app.settings

import android.content.SharedPreferences
import java.lang.reflect.Proxy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertFalse
import org.json.JSONObject
import org.junit.Test

class AppSettingsTest {
    private fun preferences(values: MutableMap<String, Any>): SharedPreferences {
        val editor = Proxy.newProxyInstance(
            SharedPreferences.Editor::class.java.classLoader,
            arrayOf(SharedPreferences.Editor::class.java),
        ) { proxy, method, args ->
            when (method.name) {
                "putString", "putInt" -> {
                    values[args!![0] as String] = args[1]
                    proxy
                }
                "apply" -> null
                else -> error("Unexpected editor call: ${method.name}")
            }
        } as SharedPreferences.Editor
        return Proxy.newProxyInstance(
            SharedPreferences::class.java.classLoader,
            arrayOf(SharedPreferences::class.java),
        ) { _, method, args ->
            when (method.name) {
                "getString", "getInt" -> values[args!![0]] ?: args[1]
                "contains" -> values.containsKey(args!![0])
                "edit" -> editor
                else -> error("Unexpected preferences call: ${method.name}")
            }
        } as SharedPreferences
    }

    @Test fun legacySettingsPreserveProviderAndThinking() {
        for (mode in listOf("enabled", "disabled", "auto")) {
            val settings = AppSettings(preferences(mutableMapOf(
                "doubao_api_key" to "legacy-key", "doubao_model_id" to "legacy-model",
                "thinking_mode" to mode, "max_steps" to 12,
            )))
            assertEquals("doubao", settings.reasoner)
            assertEquals("legacy-key", settings.apiKey)
            assertEquals("legacy-model", settings.modelId)
            assertEquals("https://ark.cn-beijing.volces.com/api/v3", settings.baseUrl)
            assertEquals(mode, settings.thinkingMode)
            assertEquals(12, settings.maxSteps)
        }
    }

    @Test fun switchingProvidersNeverCopiesCredentials() {
        val settings = AppSettings(preferences(mutableMapOf("doubao_api_key" to "legacy-key")))
        settings.reasoner = "openai"
        assertEquals("", settings.apiKey)
        assertEquals("", settings.modelId)
        assertEquals("https://api.openai.com/v1", settings.baseUrl)
        settings.apiKey = "new-key"
        settings.modelId = "new-model"
        settings.baseUrl = "https://proxy.example/v1/"
        settings.reasoner = "doubao"
        assertEquals("legacy-key", settings.apiKey)
        settings.reasoner = "openai"
        assertEquals("new-key", settings.apiKey)
        assertEquals("new-model", settings.modelId)
        assertEquals("https://proxy.example/v1", settings.baseUrl)
    }

    @Test fun newInstallDefaultsToGenericInterface() {
        val settings = AppSettings(preferences(mutableMapOf()))
        assertEquals("openai", settings.reasoner)
        assertEquals("chat_completions", settings.apiMode)
        assertEquals(60, settings.timeoutSeconds)
        assertNotNull(settings.connectionError())
    }

    @Test fun partiallyConfiguredLegacyInstallStaysOnDoubao() {
        val settings = AppSettings(preferences(mutableMapOf("thinking_mode" to "disabled")))
        assertEquals("doubao", settings.reasoner)
        assertEquals("disabled", settings.thinkingMode)
    }

    @Test fun saveAndReloadKeepProviderParametersIndependent() {
        val values = mutableMapOf<String, Any>(
            "doubao_api_key" to "legacy", "thinking_mode" to "disabled",
        )
        val settings = AppSettings(preferences(values))
        settings.saveConnection("openai", " new-key ", "https://proxy.example/custom/v1/",
            " vision ", "responses", 120, "enabled", "high", 30)
        assertEquals("disabled", settings.thinkingMode)
        assertEquals("legacy", settings.apiKeyFor("doubao"))
        val config = JSONObject(AppSettings(preferences(values)).toTaskConfigJson())
        assertEquals("openai", config.getString("reasoner"))
        assertEquals("new-key", config.getString("api_key"))
        assertEquals("vision", config.getString("model_id"))
        assertEquals("https://proxy.example/custom/v1", config.getString("base_url"))
        assertEquals("responses", config.getString("api_mode"))
        assertEquals(120, config.getInt("timeout"))
        assertEquals("high", config.getString("reasoning_effort"))
        assertEquals(30, config.getInt("max_steps"))
        assertFalse(config.has("thinking_mode"))
        assertNull(settings.connectionError())

        settings.saveConnection("doubao", "legacy", settings.baseUrlFor("doubao"),
            "", "chat_completions", 60, "auto", "", 15)
        assertEquals("responses", settings.apiMode)
        assertEquals(120, settings.timeoutSeconds)
        assertEquals("high", settings.reasoningEffort)
        val legacy = JSONObject(AppSettings(preferences(values)).toTaskConfigJson())
        assertEquals("auto", legacy.getString("thinking_mode"))
        assertEquals("legacy", legacy.getString("api_key"))
        assertFalse(legacy.has("reasoning_effort"))
        assertFalse(legacy.has("api_mode"))
        assertFalse(legacy.has("base_url"))
    }

    @Test fun invalidSaveLeavesSettingsUntouched() {
        val values = mutableMapOf<String, Any>("doubao_api_key" to "legacy")
        val before = values.toMap()
        val settings = AppSettings(preferences(values))
        try {
            settings.saveConnection("openai", "new", "https://proxy.example/v1/responses",
                "vision", "responses", 120, "enabled", "", 45)
            error("Expected rejection")
        } catch (_: IllegalArgumentException) {
            assertEquals(before, values)
        }
    }

    @Test fun invalidConnectionsAreRejectedBeforeTaskStart() {
        val invalidUrls = listOf("invalid", "https://user:pass@proxy.example/v1",
            "https://proxy.example/v1?key=test", "https://proxy.example/v1#fragment",
            "https://proxy.example/v1/chat/completions/", "https://proxy.example/v1/responses",
            "https://proxy.example:0/v1", "https://proxy.example:65536/v1")
        for (url in invalidUrls) {
            assertNotNull(url, AppSettings.validateConnection("openai", "key", url,
                "vision", "responses", 60))
        }
        assertNotNull(AppSettings.validateConnection("openai", "key", "https://proxy.example/v1",
            "", "responses", 60))
        assertNotNull(AppSettings.validateConnection("openai", "key", "https://proxy.example/v1",
            "vision", "invalid", 60))
        for (timeout in listOf(0, 4, 601)) {
            assertNotNull(AppSettings.validateConnection("openai", "key", "https://proxy.example/v1",
                "vision", "responses", timeout))
        }
    }
}
