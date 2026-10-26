package com.seetouch.app.overlay

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
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
import com.seetouch.app.task.*
import com.seetouch.app.ui.MainActivity
import com.seetouch.app.ui.MarkedScreenshotView
import com.seetouch.app.ui.VoiceReplyActivity
import kotlin.math.abs

/** Bounded scrolling content; pause/stop and confirmation choices remain outside the scroller. */
class TaskProgressOverlay(private val service: AccessibilityService) {
    private val handler = Handler(Looper.getMainLooper())
    private val wm = service.getSystemService(WindowManager::class.java)
    private val visibility = OverlayVisibility()
    private var added = false
    private var closed = false
    private var expanded = false
    private var positioned = false
    private var imeBottom = 0
    private var lastState = TaskUiState()
    private var confirmationId: Long? = null
    private var questionId: Long? = null
    private var voiceRevision = -1L
    private val accent = Color.rgb(89, 215, 194)
    private val root = LinearLayout(service).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(10), dp(4), dp(10), dp(8))
        background = GradientDrawable().apply { setColor(Color.argb(247, 22, 30, 44)); cornerRadius = dp(14).toFloat() }
        elevation = dp(8).toFloat()
    }
    private val title = label(14f).apply { setTypeface(null, Typeface.BOLD); maxLines = 2 }
    private val detail = label(13f)
    private val count = label(11f)
    private val recent = label(12f)
    private val consequence = label(13f)
    private val countdown = label(13f)
    private val thumbnail = MarkedScreenshotView(service)
    private val answer = EditText(service).apply {
        hint = "输入回答"; textSize = 14f; setTextColor(Color.WHITE); setHintTextColor(Color.LTGRAY)
        minHeight = dp(48); maxLines = 4
        imeOptions = android.view.inputmethod.EditorInfo.IME_ACTION_SEND
        setOnEditorActionListener { _, action, _ ->
            if (action == android.view.inputmethod.EditorInfo.IME_ACTION_SEND) { submitAnswer(); true } else false
        }
    }
    private val questionOptions = LinearLayout(service).apply { orientation = LinearLayout.VERTICAL }
    private val questionContent = LinearLayout(service).apply {
        orientation = LinearLayout.VERTICAL
        addView(answer); addView(questionOptions)
        addView(button("提交回答") { submitAnswer() })
        addView(button("语音回答") {
            lastState.pendingQuestion?.let { question -> service.startActivity(
                Intent(service, VoiceReplyActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    .putExtra(VoiceReplyActivity.QUESTION_ID, question.id)) }
        })
    }
    private val bodyContent = LinearLayout(service).apply {
        orientation = LinearLayout.VERTICAL
        addView(detail); addView(consequence)
        addView(thumbnail, LinearLayout.LayoutParams(-1, dp(180)))
        addView(countdown); addView(count); addView(recent); addView(questionContent)
    }
    private val body = ScrollView(service).apply { addView(bodyContent) }
    private val collapse = button("最近5步") { expanded = !expanded; render(lastState) }
    private val reject = button("拒绝") {
        lastState.pendingConfirmation?.let { TaskController.respondToConfirmation(false, it.id) }
    }.apply { isFocusableInTouchMode = true }
    private val allow = button("允许本次") {
        lastState.pendingConfirmation?.let { pending -> returnToTarget { TaskController.respondToConfirmation(true, pending.id) } }
    }
    private val confirmationActions = row(reject, allow)
    private val open = button("回到应用") { openApp() }
    private val dismiss = button("关闭") { hide() }
    private val extraActions = row(open, dismiss)
    private val pauseResume = button("暂停") {
        if (lastState.status in setOf(TaskStatus.PAUSED, TaskStatus.TAKEOVER)) returnToTarget { TaskController.resume() }
        else TaskController.pause()
    }
    private val stop = button("终止任务") { TaskController.stop() }
    private val takeover = button("我来操作") { TaskController.requestTakeover() }
    private val controls = row(pauseResume, stop, takeover)
    private val params = WindowManager.LayoutParams(dp(300), -2,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN, PixelFormat.TRANSLUCENT).apply {
        gravity = Gravity.TOP or Gravity.LEFT; setTitle("SeeTouch progress")
        setFitInsetsTypes(0)
    }
    private val finishHide = Runnable { hide() }
    private val tick = object : Runnable {
        override fun run() {
            val pending = lastState.pendingConfirmation ?: return
            val seconds = ConfirmationGate.secondsRemaining(pending.deadlineNanos)
            countdown.text = "${seconds} 秒后自动拒绝；红圈标注操作位置"
            allow.isEnabled = seconds > 0
            if (seconds > 0 && !closed) handler.postDelayed(this, 250)
        }
    }
    init {
        val header = row(label(11f).apply { text = "SeeTouch · 拖动" }, collapse)
        root.addView(header); root.addView(title); root.addView(body)
        root.addView(confirmationActions); root.addView(extraActions); root.addView(controls)
        installDrag(header); installDrag(title)
        root.setOnApplyWindowInsetsListener { _, insets ->
            val bottom = insets.getInsets(WindowInsets.Type.ime()).bottom
            if (bottom != imeBottom) { imeBottom = bottom; handler.post { resize(); updatePosition() } }
            insets
        }
    }
    fun render(state: TaskUiState) {
        if (closed) return
        if (lastState.taskGeneration != state.taskGeneration) expanded = false
        lastState = state
        handler.removeCallbacks(finishHide); handler.removeCallbacks(tick)
        if (state.status == TaskStatus.IDLE || (state.taskGeneration == 0L && !state.workerActive)) { hide(); return }
        val display = TaskProgressDisplay.from(state)
        val pending = display.confirmation
        val question = state.pendingQuestion
        title.text = display.title
        detail.text = display.detail
        count.text = display.stepCount
        recent.text = state.steps.takeLast(5).joinToString("\n\n") {
            "第 ${it.step} 步 · ${it.actionSummary.ifBlank { actionLabel(it.action) }}" +
                if (it.success == false) "（失败）" else ""
        }.ifBlank { "还没有已记录的步骤" }
        recent.visibility = if (expanded && pending == null && question == null) View.VISIBLE else View.GONE
        collapse.text = if (expanded) "收起记录" else "最近5步"
        consequence.text = pending?.consequences?.let { "可能后果：$it" }
        listOf(consequence, thumbnail, countdown, confirmationActions).forEach {
            it.visibility = if (pending != null) View.VISIBLE else View.GONE
        }
        if (pending != null) { thumbnail.setSource(pending.screenshotPath, pending.parameters); tick.run() }
        else thumbnail.setSource(null)
        questionContent.visibility = if (question != null) View.VISIBLE else View.GONE
        if (question?.id != questionId) {
            questionId = question?.id; voiceRevision = -1; answer.setText(""); questionOptions.removeAllViews()
            question?.options?.forEach { option -> questionOptions.addView(button(option) { answer.setText(option) }) }
        }
        if (question != null && question.voiceRevision != voiceRevision) {
            voiceRevision = question.voiceRevision
            if (voiceRevision > 0) answer.setText(question.voiceDraft)
        }
        val focused = pending != null || question != null
        params.flags = if (focused) params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
            else params.flags or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        if (!focused) {
            service.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(root.windowToken, 0)
            answer.clearFocus()
        }
        controls.visibility = if (display.active && state.status != TaskStatus.STOPPED) View.VISIBLE else View.GONE
        takeover.visibility = if (state.status == TaskStatus.TAKEOVER) View.GONE else View.VISIBLE
        pauseResume.text = when (state.status) {
            TaskStatus.TAKEOVER -> "我已完成，继续"
            TaskStatus.PAUSED -> "继续"
            else -> "暂停"
        }
        extraActions.visibility = if (question != null || state.status == TaskStatus.TAKEOVER || !display.active) View.VISIBLE else View.GONE
        open.text = if (state.result != null) "查看结果" else "回到应用"
        dismiss.visibility = if (!display.active) View.VISIBLE else View.GONE
        resize()
        visibility.requested = true
        if (!visibility.visible) { detach(); return }
        if (!added) {
            updatePosition()
            if (runCatching { wm.addView(root, params) }.isFailure) return
            added = true
        }
        applyVisibility()
        if (pending?.id != confirmationId) {
            confirmationId = pending?.id
            if (pending != null) reject.requestFocus()
        }
        root.doOnLayout { updatePosition() }
        if (!display.active) handler.postDelayed(finishHide, 6000)
    }
    private fun resize() {
        val metrics = wm.currentWindowMetrics
        val bars = metrics.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars())
        val available = metrics.bounds.height() - bars.top - maxOf(bars.bottom, imeBottom) - dp(20)
        val fixed = dp(48 + 42 + 12 + (if (confirmationActions.visibility == View.VISIBLE) 48 else 0) +
            (if (extraActions.visibility == View.VISIBLE) 48 else 0) + (if (controls.visibility == View.VISIBLE) 48 else 0))
        bodyContent.measure(View.MeasureSpec.makeMeasureSpec(params.width - dp(20), View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        val height = minOf(bodyContent.measuredHeight, dp(320), (available - fixed).coerceAtLeast(dp(48)))
        if (body.layoutParams.height != height) body.layoutParams = LinearLayout.LayoutParams(-1, height)
    }
    fun suppressForOperation(): Boolean {
        visibility.beginOperation()
        return runCatching { if (added) { wm.removeViewImmediate(root); added = false } }.isSuccess
    }
    fun restoreAfterOperation() { visibility.endOperation(); render(lastState) }
    fun onConfigurationChanged() { if (added) render(lastState) }
    fun close() { closed = true; handler.removeCallbacks(tick); handler.removeCallbacks(finishHide); hide() }
    private fun detach() { if (added) { runCatching { wm.removeViewImmediate(root) }; added = false } }
    private fun hide() { visibility.requested = false; detach() }
    private fun applyVisibility() { root.visibility = if (!closed && visibility.visible) View.VISIBLE else View.GONE }
    private fun openApp() {
        val intent = Intent(service, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        lastState.result?.let { intent.putExtra(MainActivity.EXTRA_RESULT_ID, it.taskId) }
        service.startActivity(intent)
    }
    private fun submitAnswer() {
        val question = lastState.pendingQuestion ?: return
        val text = answer.text.toString()
        if (text.isBlank()) return
        service.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(root.windowToken, 0)
        answer.clearFocus()
        returnToTarget { TaskController.submitAnswer(text, question.id) }
    }
    private fun returnToTarget(action: () -> Unit) {
        val generation = lastState.taskGeneration
        MainActivity.hideIfVisible()
        VoiceReplyActivity.closeForResume()
        handler.postDelayed({ if (TaskController.state.value.taskGeneration == generation) action() }, 250)
    }
    private fun updatePosition() {
        val m = wm.currentWindowMetrics
        val bars = m.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
        val left = bars.left + dp(8); val right = m.bounds.width() - bars.right - dp(8)
        val top = bars.top + dp(8); val bottom = m.bounds.height() - maxOf(bars.bottom, imeBottom) - dp(8)
        params.width = minOf(dp(300), (right - left).coerceAtLeast(1))
        if (!positioned) { params.x = right - params.width; params.y = top + dp(56); positioned = true }
        params.x = params.x.coerceIn(left, (right - params.width).coerceAtLeast(left))
        params.y = params.y.coerceIn(top, (bottom - root.height.coerceAtLeast(dp(96))).coerceAtLeast(top))
        if (added) runCatching { wm.updateViewLayout(root, params) }
    }
    private fun installDrag(view: View) {
        var x = 0f; var y = 0f; var startX = 0; var startY = 0; var dragging = false
        val slop = ViewConfiguration.get(service).scaledTouchSlop
        view.setOnTouchListener { touched, event -> when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> { x = event.rawX; y = event.rawY; startX = params.x; startY = params.y; dragging = false; true }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.rawX - x; val dy = event.rawY - y
                if (abs(dx) > slop || abs(dy) > slop) dragging = true
                if (dragging) { params.x = startX + dx.toInt(); params.y = startY + dy.toInt(); updatePosition() }; true
            }
            MotionEvent.ACTION_UP -> { if (!dragging) touched.performClick(); true }
            else -> true
        } }
    }
    private fun row(vararg views: View) = LinearLayout(service).apply {
        gravity = Gravity.CENTER_VERTICAL
        views.forEach { addView(it, LinearLayout.LayoutParams(0, -2, 1f)) }
    }
    private fun label(size: Float) = TextView(service).apply { textSize = size; setTextColor(Color.WHITE); setPadding(0, dp(4), 0, dp(4)) }
    private fun button(caption: String, action: () -> Unit) = Button(service).apply {
        text = caption; textSize = 12f; isAllCaps = false; minWidth = dp(48); minimumWidth = dp(48)
        minHeight = dp(48); minimumHeight = dp(48); setPadding(dp(2), 0, dp(2), 0)
        setTextColor(accent); setOnClickListener { action() }
        background = GradientDrawable().apply { setColor(Color.TRANSPARENT) }
    }
    private fun dp(value: Int) = (value * service.resources.displayMetrics.density).toInt()
    private fun actionLabel(action: String) = when (action) {
        "CLICK" -> "点击"; "LONG_PRESS" -> "长按"; "TYPE" -> "输入文字"; "SCROLL" -> "滑动"; "OPEN" -> "打开应用"
        "BACK" -> "返回"; "WAIT" -> "等待"; "ASK_USER" -> "追问"; "TAKE_OVER" -> "人工接管"
        "ANSWER" -> "给出答案"; "COMPLETE" -> "结束"; else -> "操作"
    }
}
