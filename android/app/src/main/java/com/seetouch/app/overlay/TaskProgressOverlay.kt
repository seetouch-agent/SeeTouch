package com.seetouch.app.overlay

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.text.TextUtils
import android.util.Log
import android.view.Choreographer
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.EditText
import android.view.inputmethod.InputMethodManager
import androidx.core.view.doOnLayout
import com.seetouch.app.task.TaskController
import com.seetouch.app.task.TaskProgressDisplay
import com.seetouch.app.task.TaskStatus
import com.seetouch.app.task.TaskUiState
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.abs

/** Owned by the connected accessibility service; no separate overlay permission is needed. */
class TaskProgressOverlay(private val service: AccessibilityService) {
    private val handler = Handler(Looper.getMainLooper())
    private val windowManager = service.getSystemService(WindowManager::class.java)
    private val visibility = OverlayVisibility()
    private var added = false
    private var closed = false
    private var collapsed = false
    private var positioned = false
    private var lastState = TaskUiState()
    private val accent = Color.rgb(89, 215, 194)
    private val root = LinearLayout(service).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(12), dp(6), dp(12), dp(10))
        background = GradientDrawable().apply {
            setColor(Color.argb(245, 22, 30, 44))
            cornerRadius = dp(14).toFloat()
            setStroke(dp(1), Color.rgb(63, 79, 96))
        }
        elevation = dp(8).toFloat()
    }
    private val title = label(14f, Color.WHITE).apply {
        setTypeface(null, Typeface.BOLD)
        maxLines = 1
        ellipsize = TextUtils.TruncateAt.END
    }
    private val detail = label(12f, Color.WHITE).apply {
        maxLines = 3
        ellipsize = TextUtils.TruncateAt.END
        setPadding(0, dp(6), 0, dp(6))
    }
    private val detailContainer = ScrollView(service).apply { addView(detail) }
    private val count = label(11f, Color.LTGRAY)
    private val busy = ProgressBar(service, null, android.R.attr.progressBarStyleHorizontal).apply {
        isIndeterminate = true
        indeterminateTintList = ColorStateList.valueOf(accent)
    }
    private val collapse = button("收起") {
        collapsed = !collapsed
        render(lastState)
    }
    private val allow = button("允许执行") {
        lastState.pendingConfirmation?.let { TaskController.respondToConfirmation(true, it.id) }
    }
    private val reject = button("拒绝") {
        lastState.pendingConfirmation?.let { TaskController.respondToConfirmation(false, it.id) }
    }
    private val returnToApp = button("回到应用") {
        service.packageManager.getLaunchIntentForPackage(service.packageName)?.let {
            service.startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }
    private val dismiss = button("关闭") { hide() }
    private val pauseResume = button("暂停") {
        if (lastState.status in setOf(TaskStatus.PAUSED, TaskStatus.TAKEOVER)) TaskController.resume()
        else TaskController.pause()
    }
    private val stop = button("终止") { TaskController.stop() }
    private val takeover = button("我来操作") { TaskController.requestTakeover() }
    private val controls = LinearLayout(service).apply {
        listOf(pauseResume, stop, takeover).forEach { addView(it, LinearLayout.LayoutParams(0, dp(42), 1f)) }
    }
    private val answer = EditText(service).apply {
        hint = "输入回答"; setTextColor(Color.WHITE); setHintTextColor(Color.LTGRAY)
        textSize = 13f; maxLines = 3
        inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
        imeOptions = android.view.inputmethod.EditorInfo.IME_ACTION_SEND
        setOnEditorActionListener { _, actionId, _ ->
            if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_SEND) {
                submitCurrentAnswer(); true
            } else false
        }
    }
    private val questionContent = LinearLayout(service).apply { orientation = LinearLayout.VERTICAL }
    private val questionPanel = ScrollView(service).apply { addView(questionContent) }
    private var questionId: Long? = null
    private val actions = LinearLayout(service).apply {
        orientation = LinearLayout.HORIZONTAL
        listOf(allow, reject, returnToApp, dismiss).forEach {
            addView(it, LinearLayout.LayoutParams(0, dp(42), 1f))
        }
    }
    private val params = WindowManager.LayoutParams(
        dp(248), WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.LEFT
        setTitle("SeeTouch task progress")
        setFitInsetsTypes(0)
        layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
    }
    private val finishHide = Runnable { hide() }

    init {
        val header = LinearLayout(service).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(label(11f, accent).apply { text = "SeeTouch · 拖动移动" },
                LinearLayout.LayoutParams(0, dp(36), 1f))
            addView(collapse, LinearLayout.LayoutParams(dp(56), dp(36)))
        }
        installDrag(header)
        installDrag(title)
        root.addView(header)
        root.addView(title)
        root.addView(detailContainer)
        root.addView(count)
        root.addView(busy, LinearLayout.LayoutParams(-1, dp(3)).apply { topMargin = dp(8) })
        root.addView(actions)
        root.addView(questionPanel, LinearLayout.LayoutParams(-1, dp(180)))
        root.addView(controls)
    }

    fun render(state: TaskUiState) {
        if (closed) return
        lastState = state
        handler.removeCallbacks(finishHide)
        if (state.status == TaskStatus.IDLE) { hide(); return }
        val display = TaskProgressDisplay.from(state)
        val question = state.pendingQuestion
        val fullPrompt = display.confirmation != null || question != null
        val compact = collapsed && display.confirmation == null && question == null
        title.text = display.title
        title.setTextColor(if (display.confirmation != null) Color.rgb(255, 207, 112) else Color.WHITE)
        detail.text = display.detail
        detail.maxLines = if (fullPrompt) Int.MAX_VALUE else 3
        detail.ellipsize = if (fullPrompt) null else TextUtils.TruncateAt.END
        val metrics = windowManager.currentWindowMetrics
        val bars = metrics.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars())
        val promptHeight = minOf(dp(140),
            (metrics.bounds.height() - bars.top - bars.bottom - dp(160)).coerceAtLeast(dp(48)))
        detailContainer.layoutParams = LinearLayout.LayoutParams(-1,
            if (fullPrompt) promptHeight else LinearLayout.LayoutParams.WRAP_CONTENT)
        detailContainer.visibility = if (compact) View.GONE else View.VISIBLE
        count.text = display.stepCount
        count.visibility = if (compact) View.GONE else View.VISIBLE
        busy.visibility = if (display.running && display.confirmation == null) View.VISIBLE else View.GONE
        collapse.text = if (collapsed) "展开" else "收起"
        collapse.visibility = if (display.confirmation == null && display.active && question == null) View.VISIBLE else View.GONE
        allow.visibility = if (display.confirmation != null) View.VISIBLE else View.GONE
        reject.visibility = allow.visibility
        returnToApp.visibility = if (!display.running || question != null) View.VISIBLE else View.GONE
        returnToApp.text = if (question != null) "应用 / 语音回答" else "回到应用"
        dismiss.visibility = if (!display.active) View.VISIBLE else View.GONE
        actions.visibility = if (display.confirmation != null || !display.running || question != null) View.VISIBLE else View.GONE
        controls.visibility = if (display.active && state.status != TaskStatus.STOPPED) View.VISIBLE else View.GONE
        pauseResume.text = if (state.status in setOf(TaskStatus.PAUSED, TaskStatus.TAKEOVER)) "继续" else "暂停"
        takeover.visibility = if (state.status == TaskStatus.TAKEOVER) View.GONE else View.VISIBLE
        questionPanel.visibility = if (question != null) View.VISIBLE else View.GONE
        if (question?.id != questionId) {
            questionId = question?.id
            questionContent.removeAllViews()
            if (question != null) {
                answer.setText("")
                (answer.parent as? android.view.ViewGroup)?.removeView(answer)
                questionContent.addView(answer)
                question.options.forEach { option ->
                    questionContent.addView(button(option) { answer.setText(option) })
                }
                questionContent.addView(button("提交回答") { submitCurrentAnswer() })
            } else {
                service.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(root.windowToken, 0)
                answer.clearFocus()
            }
        }
        params.flags = if (question != null) params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
            else params.flags or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        params.softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        params.width = dp(if (compact) 200 else 248)
        visibility.requested = true
        if (!added) {
            updatePosition()
            try {
                windowManager.addView(root, params)
                added = true
            } catch (e: RuntimeException) {
                Log.w(TAG, "cannot attach progress overlay", e)
                return
            }
        }
        applyVisibility()
        root.doOnLayout { updatePosition() }
        if (!display.active) handler.postDelayed(finishHide, 6000)
    }

    /** Called on the Runner thread. Wait for the hidden surface to render before capture/input. */
    fun <T> withoutOverlay(operation: () -> T): T {
        check(Looper.myLooper() != Looper.getMainLooper()) { "Device operations need a worker thread" }
        val ready = CountDownLatch(1)
        handler.post {
            val wasVisible = added && visibility.visible
            visibility.beginOperation()
            applyVisibility()
            if (wasVisible) {
                Choreographer.getInstance().postFrameCallback {
                    Choreographer.getInstance().postFrameCallback { ready.countDown() }
                }
            } else ready.countDown()
        }
        try {
            check(ready.await(2, TimeUnit.SECONDS)) { "Progress overlay did not hide in time" }
            return operation()
        } finally {
            handler.post {
                visibility.endOperation()
                applyVisibility()
            }
        }
    }

    fun onConfigurationChanged() { if (added) render(lastState) }

    fun close() {
        closed = true
        handler.removeCallbacks(finishHide)
        hide()
    }

    private fun hide() {
        visibility.requested = false
        if (added) {
            runCatching { windowManager.removeViewImmediate(root) }
                .onFailure { Log.w(TAG, "cannot remove progress overlay", it) }
            added = false
        }
    }

    private fun applyVisibility() {
        root.visibility = if (!closed && visibility.visible) View.VISIBLE else View.GONE
    }

    private fun updatePosition() {
        if (closed) return
        val metrics = windowManager.currentWindowMetrics
        val insets = metrics.windowInsets.getInsetsIgnoringVisibility(
            WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout(),
        )
        val left = insets.left + dp(8)
        val top = insets.top + dp(8)
        val right = metrics.bounds.width() - insets.right - dp(8)
        val bottom = metrics.bounds.height() - insets.bottom - dp(8)
        params.width = params.width.coerceAtMost((right - left).coerceAtLeast(1))
        if (!positioned) {
            params.x = right - params.width
            params.y = top + dp(64)
            positioned = true
        }
        params.x = params.x.coerceIn(left, (right - params.width).coerceAtLeast(left))
        params.y = params.y.coerceIn(top, (bottom - root.height.coerceAtLeast(dp(64))).coerceAtLeast(top))
        if (added) runCatching { windowManager.updateViewLayout(root, params) }
            .onFailure { Log.w(TAG, "cannot reposition progress overlay", it) }
    }

    private fun installDrag(view: View) {
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var dragging = false
        val slop = ViewConfiguration.get(service).scaledTouchSlop
        view.setOnTouchListener { touched, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX; downY = event.rawY
                    startX = params.x; startY = params.y; dragging = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - downX
                    val dy = event.rawY - downY
                    if (abs(dx) > slop || abs(dy) > slop) dragging = true
                    if (dragging) {
                        params.x = startX + dx.toInt(); params.y = startY + dy.toInt()
                        updatePosition()
                    }
                    true
                }
                MotionEvent.ACTION_UP -> { if (!dragging) touched.performClick(); true }
                MotionEvent.ACTION_CANCEL -> true
                else -> false
            }
        }
    }

    private fun label(size: Float, color: Int) = TextView(service).apply {
        textSize = size; setTextColor(color)
    }

    private fun submitCurrentAnswer() {
        val question = lastState.pendingQuestion ?: return
        val value = answer.text.toString()
        if (value.isBlank()) return
        service.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(root.windowToken, 0)
        answer.clearFocus()
        handler.postDelayed({ TaskController.submitAnswer(value, question.id) }, 250)
    }

    private fun button(caption: String, action: () -> Unit) = Button(service).apply {
        text = caption; textSize = 12f; isAllCaps = false
        minWidth = 0; minimumWidth = 0; minHeight = 0; minimumHeight = 0
        setPadding(dp(4), 0, dp(4), 0)
        setTextColor(accent)
        background = GradientDrawable().apply { setColor(Color.TRANSPARENT); cornerRadius = dp(8).toFloat() }
        setOnClickListener { action() }
    }

    private fun dp(value: Int): Int = (value * service.resources.displayMetrics.density).toInt()

    companion object { private const val TAG = "SeeTouchOverlay" }
}
