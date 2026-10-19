package com.seetouch.app.ui

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import com.seetouch.app.task.TaskController
import com.seetouch.app.device.SeeTouchAccessibilityService
import java.lang.ref.WeakReference

/** Voice recognition fills a draft; user review is required before any task or answer is sent. */
class VoiceReplyActivity : ComponentActivity() {
    private val speech = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val text = if (result.resultCode == Activity.RESULT_OK) result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull() else null
        deliver(text)
        finish()
    }
    private fun deliver(text: String?) {
        if (intent.hasExtra(ENTRY_ID)) SeeTouchAccessibilityService.instance?.setEntryVoiceDraft(intent.getLongExtra(ENTRY_ID, -1), text)
        else text?.let { TaskController.setVoiceDraft(intent.getLongExtra(QUESTION_ID, -1), it) }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        active = WeakReference(this)
        val valid = if (intent.hasExtra(ENTRY_ID)) SeeTouchAccessibilityService.instance?.acceptsEntryVoice(intent.getLongExtra(ENTRY_ID, -1)) == true
            else TaskController.state.value.pendingQuestion?.id == intent.getLongExtra(QUESTION_ID, -1)
        if (!valid) { finish(); return }
        if (savedInstanceState == null) runCatching { speech.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")) }.onFailure {
            deliver(null)
            Toast.makeText(this, "系统语音输入不可用，请输入文字", Toast.LENGTH_LONG).show(); finish()
        }
    }
    override fun onDestroy() {
        if (active?.get() === this) active = null
        super.onDestroy()
    }
    companion object {
        const val QUESTION_ID = "voice_question_id"; const val ENTRY_ID = "voice_entry_id"
        private var active: WeakReference<VoiceReplyActivity>? = null
        fun closeForResume() { active?.get()?.finishAndRemoveTask() }
    }
}
