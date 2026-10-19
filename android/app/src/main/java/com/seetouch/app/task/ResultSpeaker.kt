package com.seetouch.app.task

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale

object ResultSpeaker {
    private val handler = Handler(Looper.getMainLooper())
    private val spoken = mutableSetOf<String>()
    private var engine: TextToSpeech? = null
    fun stop() { handler.post { engine?.shutdown(); engine = null } }
    fun speak(context: Context, result: TaskResult, enabled: Boolean) {
        if (!enabled) return
        handler.post {
            if (!spoken.add(result.taskId)) return@post
            engine?.shutdown()
            val id = result.taskId
            var current: TextToSpeech? = null
            current = TextToSpeech(context.applicationContext) { status -> handler.post {
                val speech = current ?: return@post
                if (engine !== speech) { speech.shutdown(); return@post }
                if (status != TextToSpeech.SUCCESS || speech.setLanguage(Locale.SIMPLIFIED_CHINESE) < 0) {
                    speech.shutdown(); engine = null; return@post
                }
                speech.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) = Unit
                    override fun onDone(utteranceId: String?) = release()
                    @Deprecated("Platform callback") override fun onError(utteranceId: String?) = release()
                    private fun release() { handler.post {
                        if (engine === speech) engine = null
                        speech.shutdown()
                    } }
                })
                speech.speak(result.speechText.take(3500), TextToSpeech.QUEUE_FLUSH, null, id)
            } }
            engine = current
        }
    }
}
