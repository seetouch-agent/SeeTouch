package com.seetouch.app.settings

import android.content.SharedPreferences
import java.lang.reflect.Proxy
import org.junit.Assert.assertEquals
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
}
