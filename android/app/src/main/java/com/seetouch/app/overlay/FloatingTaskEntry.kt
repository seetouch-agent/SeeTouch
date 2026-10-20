package com.seetouch.app.overlay

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowInsets
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.view.doOnLayout
import com.seetouch.app.settings.AppSettings
import com.seetouch.app.task.TaskController
import com.seetouch.app.task.TaskExecutionService
import com.seetouch.app.task.TaskUiState
import com.seetouch.app.ui.VoiceReplyActivity
import com.seetouch.app.ui.MainActivity
import org.json.JSONObject
import kotlin.math.abs

/** Idle entry point; a task launched here preserves the current application as its initial screen. */
class FloatingTaskEntry(private val service: AccessibilityService) {
    private val handler = Handler(Looper.getMainLooper())
    private val wm = service.getSystemService(WindowManager::class.java)
    private val visibility = OverlayVisibility()
    private val settings = AppSettings(service)
    private var added = false
    private var closed = false
    private var expanded = false
    private var starting = false
    private var voiceActive = false
    private var sessionId = 0L
    private var imeBottom = 0
    private var lastState = TaskUiState()
    private val input = EditText(service).apply {
        hint = "从当前页面开始，让手机做什么？"; setTextColor(Color.WHITE); setHintTextColor(Color.LTGRAY)
        minLines = 2; maxLines = 4; textSize = 14f; minHeight = dp(48)
    }
    private val message = TextView(service).apply { setTextColor(Color.rgb(255, 195, 100)); textSize = 12f }
    private val common = LinearLayout(service).apply { orientation = LinearLayout.VERTICAL }
    private val ball = button("S") { expanded = !expanded; if (expanded) sessionId++; render(lastState) }.apply {
        contentDescription = "SeeTouch 悬浮球，点击输入任务，拖动移动"
    }
    private val panelBody = ScrollView(service).apply {
        addView(LinearLayout(service).apply {
            orientation = LinearLayout.VERTICAL
            addView(input); addView(message); addView(common)
        })
    }
    private val panel = LinearLayout(service).apply {
        orientation = LinearLayout.VERTICAL
        addView(panelBody)
        addView(LinearLayout(service).apply {
            listOf(button("语音") { beginVoice() }, button("开始") { startTask() }, button("收起") {
                expanded = false; hideKeyboard(); render(lastState)
            }).forEach { addView(it, LinearLayout.LayoutParams(0, dp(48), 1f)) }
        })
    }
    private val root = LinearLayout(service).apply {
        orientation = LinearLayout.VERTICAL
        background = GradientDrawable().apply { setColor(Color.argb(245, 22, 30, 44)); cornerRadius = dp(28).toFloat() }
        addView(ball, LinearLayout.LayoutParams(dp(56), dp(56)))
        addView(panel)
    }
    private val params = WindowManager.LayoutParams(dp(56), -2, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
        PixelFormat.TRANSLUCENT).apply { gravity = Gravity.TOP or Gravity.LEFT; x = 0; y = dp(240); setFitInsetsTypes(0) }
    init {
        installDrag()
        root.setOnApplyWindowInsetsListener { _, insets ->
            val bottom = insets.getInsets(WindowInsets.Type.ime()).bottom
            if (imeBottom != bottom) { imeBottom = bottom; handler.post { position(false) } }
            insets
        }
    }
    fun render(state: TaskUiState) {
        lastState = state
        if (closed) return
        if (state.workerActive) { starting = false; expanded = false; hideKeyboard() }
        visibility.requested = settings.floatingEntryEnabled && !state.workerActive && !starting && !voiceActive
        if (!visibility.requested) { hide(); return }
        panel.visibility = if (expanded) View.VISIBLE else View.GONE
        params.width = dp(if (expanded) 300 else 56)
        params.flags = if (expanded) params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
            else params.flags or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        if (expanded) {
            common.removeAllViews()
            settings.recentInstructions().take(3).forEach { command ->
                common.addView(button(command.take(35)) { input.setText(command) })
            }
        }
        position(false)
        if (!visibility.visible) { hide(); return }
        if (!added) { if (runCatching { wm.addView(root, params) }.isFailure) return; added = true }
        applyVisibility()
        root.doOnLayout { position(false) }
    }
    fun acceptsVoice(id: Long): Boolean = expanded && id == sessionId && !lastState.workerActive
    fun voiceDraft(id: Long, text: String?) {
        if (!acceptsVoice(id)) return
        voiceActive = false
        text?.let { input.setText(it) }
        render(lastState)
    }
    private fun beginVoice() {
        voiceActive = true; hideKeyboard(); render(lastState)
        runCatching { service.startActivity(Intent(service, VoiceReplyActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra(VoiceReplyActivity.ENTRY_ID, sessionId)) }
            .onFailure { voiceActive = false; message.text = "无法启动系统语音输入，请输入文字"; render(lastState) }
    }
    private fun startTask() {
        val command = input.text.toString().trim()
        val error = when {
            command.isEmpty() || command.length > 500 -> "请输入 1–500 字的任务"
            TaskController.isRunning -> "请先结束当前任务"
            else -> settings.connectionError()
        }
        if (error != null) { message.text = error; return }
        val config = JSONObject(settings.toTaskConfigJson()).put("start_from_current", true).toString()
        starting = true; expanded = false; hideKeyboard(); render(lastState)
        MainActivity.hideIfVisible()
        VoiceReplyActivity.closeForResume()
        handler.postDelayed({ runCatching { TaskExecutionService.start(service, command, config) }.onFailure {
            starting = false; expanded = true; message.text = "任务未能启动，请回到应用重试"; render(lastState)
        } }, 250)
    }
    /** Called on main: remove the actual window, including its touch surface. */
    fun suppressForOperation(): Boolean {
        visibility.beginOperation()
        return runCatching { if (added) { wm.removeViewImmediate(root); added = false } }.isSuccess
    }
    fun restoreAfterOperation() { visibility.endOperation(); render(lastState) }
    fun close() { closed = true; hideKeyboard(); hide() }
    private fun hide() { if (added) { runCatching { wm.removeViewImmediate(root) }; added = false } }
    private fun applyVisibility() { root.visibility = if (!closed && visibility.visible) View.VISIBLE else View.GONE }
    private fun hideKeyboard() { service.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(root.windowToken, 0); input.clearFocus() }
    private fun position(snap: Boolean) {
        val metrics = wm.currentWindowMetrics
        val bars = metrics.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
        val left = bars.left; val right = metrics.bounds.width() - bars.right
        params.width = minOf(params.width, (right - left).coerceAtLeast(1))
        val bottom = metrics.bounds.height() - maxOf(bars.bottom, imeBottom)
        if (expanded) {
            panelBody.getChildAt(0).measure(View.MeasureSpec.makeMeasureSpec(params.width, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
            val height = minOf(panelBody.getChildAt(0).measuredHeight,
                (bottom - bars.top - dp(116)).coerceAtLeast(dp(48)))
            if (panelBody.layoutParams.height != height) panelBody.layoutParams = LinearLayout.LayoutParams(-1, height)
        }
        if (snap) params.x = if (params.x + params.width / 2 < metrics.bounds.width() / 2) left else right - params.width
        params.x = params.x.coerceIn(left, (right - params.width).coerceAtLeast(left))
        params.y = params.y.coerceIn(bars.top, (bottom - root.height.coerceAtLeast(dp(56))).coerceAtLeast(bars.top))
        if (added) runCatching { wm.updateViewLayout(root, params) }
    }
    private fun installDrag() {
        var x = 0f; var y = 0f; var sx = 0; var sy = 0; var dragged = false
        val slop = ViewConfiguration.get(service).scaledTouchSlop
        ball.setOnTouchListener { view, e -> when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> { x = e.rawX; y = e.rawY; sx = params.x; sy = params.y; dragged = false; true }
            MotionEvent.ACTION_MOVE -> {
                if (abs(e.rawX - x) > slop || abs(e.rawY - y) > slop) dragged = true
                if (dragged) { params.x = sx + (e.rawX - x).toInt(); params.y = sy + (e.rawY - y).toInt(); position(false) }; true
            }
            MotionEvent.ACTION_UP -> { if (dragged) position(true) else view.performClick(); true }
            else -> true
        } }
    }
    private fun button(text: String, action: () -> Unit) = Button(service).apply {
        this.text = text; textSize = 12f; isAllCaps = false; minHeight = dp(48); minimumHeight = dp(48)
        setTextColor(Color.rgb(89, 215, 194)); setOnClickListener { action() }
        background = GradientDrawable().apply { setColor(Color.TRANSPARENT) }
    }
    private fun dp(value: Int) = (value * service.resources.displayMetrics.density).toInt()
}
