package com.seetouch.app.device

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.content.res.Configuration
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import com.seetouch.app.overlay.TaskProgressOverlay
import com.seetouch.app.overlay.FloatingTaskEntry
import com.seetouch.app.overlay.OverlayOperationGate
import com.seetouch.app.task.TaskController
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit

/**
 * SeeTouch 设备层核心:手势注入 / 截图 / 前台 app 跟踪 / 全局导航。
 *
 * 所有阻塞式方法(截图、手势)必须在后台线程调用(Python Runner 线程),
 * 回调本身跑在主线程,内部用 CountDownLatch 桥接。
 */
class SeeTouchAccessibilityService : AccessibilityService() {
    private val overlayScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var overlayJob: Job? = null
    private var sensitiveScanJob: Job? = null
    @Volatile private var progressOverlay: TaskProgressOverlay? = null
    @Volatile private var floatingEntry: FloatingTaskEntry? = null
    private val overlayHandler = Handler(Looper.getMainLooper())
    private val overlayGate = OverlayOperationGate(
        post = { overlayHandler.post(it) },
        settle = { overlayHandler.postDelayed(it, 80) },
        isUiThread = { Looper.myLooper() == Looper.getMainLooper() },
    )

    @Volatile
    private var foregroundPackage: String? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        overlayJob?.cancel()
        sensitiveScanJob?.cancel()
        progressOverlay?.close()
        floatingEntry?.close()
        val overlay = TaskProgressOverlay(this)
        progressOverlay = overlay
        val entry = FloatingTaskEntry(this)
        floatingEntry = entry
        overlayJob = overlayScope.launch { TaskController.state.collect { overlay.render(it); entry.render(it) } }
        Log.i(TAG, "accessibility service connected")
    }

    override fun onDestroy() {
        TaskController.pause()
        overlayScope.cancel()
        progressOverlay?.close()
        progressOverlay = null
        floatingEntry?.close(); floatingEntry = null
        if (instance === this) instance = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return
        if (windows.any { it.id == event.windowId &&
                it.type == AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY }) return
        val pkg = event.packageName?.toString() ?: return
        val state = TaskController.state.value
        if (state.status == com.seetouch.app.task.TaskStatus.RUNNING && pkg != packageName && sensitiveScanJob?.isActive != true) {
            // Node reads can involve hundreds of remote calls. Never block overlay removal/callbacks on main.
            val generation = state.taskGeneration
            sensitiveScanJob = overlayScope.launch(Dispatchers.IO) {
                val reason = runCatching { takeoverReason() }.getOrNull()
                val current = TaskController.state.value
                if (reason != null && current.taskGeneration == generation &&
                    current.status == com.seetouch.app.task.TaskStatus.RUNNING) TaskController.requestTakeover(reason)
            }
        }
        if (event.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        // 输入法窗口不代表前台 app 切换
        if (pkg.contains("inputmethod") || pkg.contains(".ime")) return
        foregroundPackage = pkg
    }

    override fun onInterrupt() {}

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        progressOverlay?.onConfigurationChanged()
        refreshFloatingEntry()
    }

    // ------------------------- 查询 -------------------------

    fun currentPackage(): String? =
        foregroundPackage ?: rootInActiveWindow?.packageName?.toString()

    /** Compact active-window tree for model grounding (text/desc/id/bounds/flags). */
    fun uiNodes(limit: Int = 120): Array<String> {
        val root = rootInActiveWindow ?: return emptyArray()
        val out = mutableListOf<String>()
        val seen = HashSet<String>()
        var visited = 0
        fun clean(value: CharSequence?): String =
            (value?.toString() ?: "").replace('\t', ' ').replace('\n', ' ')
                .replace('"', '\'').trim().take(80)
        fun walk(node: AccessibilityNodeInfo?, depth: Int) {
            if (node == null || depth > 30 || visited >= 400 || out.size >= limit) return
            visited++
            val pkg = node.packageName?.toString() ?: ""
            if (pkg != "com.android.systemui" && pkg != packageName && node.isVisibleToUser) {
                val text = clean(node.text)
                val desc = clean(node.contentDescription)
                val id = node.viewIdResourceName?.substringAfterLast('/') ?: ""
                val clickable = node.isClickable
                val scrollable = node.isScrollable
                val editable = node.isEditable
                if (text.isNotEmpty() || desc.isNotEmpty() || clickable || scrollable || editable) {
                    val rect = android.graphics.Rect()
                    node.getBoundsInScreen(rect)
                    if (rect.width() > 0 && rect.height() > 0) {
                        val flags = buildList {
                            if (clickable) add("click")
                            if (scrollable) add("scroll")
                            if (editable) add("edit")
                            if (node.isFocused) add("focus")
                        }.joinToString(",").ifEmpty { "-" }
                        val line = listOf(
                            text, desc, id, node.className?.toString()?.substringAfterLast('.') ?: "",
                            rect.left, rect.top, rect.right, rect.bottom, flags,
                        ).joinToString("\t")
                        if (seen.add(line)) out.add(line)
                    }
                }
            }
            for (i in 0 until node.childCount) {
                if (out.size >= limit || visited >= 400) break
                walk(node.getChild(i), depth + 1)
            }
        }
        walk(root, 0)
        return out.toTypedArray()
    }

    fun takeoverReason(): String? {
        val root = rootInActiveWindow ?: return null
        if (root.packageName?.toString() == packageName) return null
        val nodes = mutableListOf<SensitiveScreenDetector.Node>()
        var visited = 0
        fun visit(node: AccessibilityNodeInfo?, depth: Int) {
            if (node == null || depth > 30 || visited >= 300) return
            visited++
            if (node.isVisibleToUser) nodes.add(SensitiveScreenDetector.Node(
                if (node.isPassword) "" else listOfNotNull(node.text, node.contentDescription, node.hintText)
                    .joinToString(" ") { it.take(512).toString() },
                node.isPassword, node.isEditable))
            for (i in 0 until node.childCount) {
                if (visited >= 300) break
                visit(node.getChild(i), depth + 1)
            }
        }
        visit(root, 0)
        return SensitiveScreenDetector.reason(nodes)
    }

    internal fun <T> controlled(operation: () -> T): T = TaskController.withDeviceAction {
        if (TaskController.isRunning) takeoverReason()?.let {
            TaskController.requestTakeover(it)
            error("Sensitive screen requires human takeover")
        }
        operation()
    }

    // ------------------------- 截图 -------------------------

    /** 截取默认显示屏,返回软件位图;失败返回 null。 */
    fun takeScreenshotBitmap(): Bitmap? = withoutProgressOverlay { takeUnobstructedScreenshot() }

    private fun takeUnobstructedScreenshot(): Bitmap? {
        val latch = CountDownLatch(1)
        var bitmap: Bitmap? = null
        val mainExecutor: Executor = mainExecutor
        controlled { takeScreenshot(
            Display.DEFAULT_DISPLAY,
            mainExecutor,
            object : TakeScreenshotCallback {
                override fun onSuccess(result: ScreenshotResult) {
                    try {
                        val hw = Bitmap.wrapHardwareBuffer(
                            result.hardwareBuffer, result.colorSpace
                        )
                        bitmap = hw?.copy(Bitmap.Config.ARGB_8888, false)
                        result.hardwareBuffer.close()
                    } catch (t: Throwable) {
                        Log.e(TAG, "convert screenshot failed", t)
                    }
                    latch.countDown()
                }

                override fun onFailure(errorCode: Int) {
                    Log.e(TAG, "takeScreenshot failed: errorCode=$errorCode")
                    latch.countDown()
                }
            }
        ) }
        latch.await(SCREENSHOT_TIMEOUT_S, TimeUnit.SECONDS)
        return bitmap
    }

    // ------------------------- 手势 -------------------------

    fun tap(x: Float, y: Float): Boolean {
        val path = Path().apply { moveTo(x, y) }
        return dispatchGestureBlocking(
            GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0, TAP_DURATION_MS))
                .build()
        )
    }

    /** 长按:在原地保持按压 LONG_PRESS_DURATION_MS,触发系统长按。 */
    fun longPress(x: Float, y: Float): Boolean {
        val path = Path().apply { moveTo(x, y) }
        return dispatchGestureBlocking(
            GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0, LONG_PRESS_DURATION_MS))
                .build()
        )
    }

    fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, durationMs: Long): Boolean {
        val path = Path().apply {
            moveTo(x1, y1)
            lineTo(x2, y2)
        }
        return dispatchGestureBlocking(
            GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
                .build()
        )
    }

    private fun dispatchGestureBlocking(gesture: GestureDescription): Boolean =
        withoutProgressOverlay { dispatchUnobstructedGesture(gesture) }

    private fun dispatchUnobstructedGesture(gesture: GestureDescription): Boolean {
        val latch = CountDownLatch(1)
        var ok = false
        val dispatched = controlled { dispatchGesture(
            gesture,
            object : GestureResultCallback() {
                override fun onCompleted(g: GestureDescription?) {
                    ok = true
                    latch.countDown()
                }

                override fun onCancelled(g: GestureDescription?) {
                    latch.countDown()
                }
            },
            null,
        ) }
        if (!dispatched) return false
        latch.await(GESTURE_TIMEOUT_S, TimeUnit.SECONDS)
        return ok
    }

    // ------------------------- 文本输入 -------------------------

    /** 向当前焦点输入框写入文本(替换原内容),支持中文。 */
    fun setTextOnFocused(text: String): Boolean = withoutProgressOverlay { setUnobstructedText(text) }

    private fun setUnobstructedText(text: String): Boolean {
        val node = findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: findEditableNode(rootInActiveWindow)
            ?: return false
        if (node.isPassword && TaskController.isRunning) {
            TaskController.requestTakeover("检测到密码输入，请手动完成")
            return false
        }
        val args = Bundle().apply {
            putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text
            )
        }
        return controlled { node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args) }
    }

    private fun findEditableNode(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        root ?: return null
        if (root.isEditable && root.isFocused) return root
        for (i in 0 until root.childCount) {
            findEditableNode(root.getChild(i))?.let { return it }
        }
        return null
    }

    // ------------------------- 全局导航 -------------------------

    fun pressBack(): Boolean = withoutProgressOverlay { controlled { performGlobalAction(GLOBAL_ACTION_BACK) } }

    fun pressHome(): Boolean = withoutProgressOverlay { controlled { performGlobalAction(GLOBAL_ACTION_HOME) } }

    /** Explicit notification-control navigation, outside automated task actions. */
    fun dismissNotificationShade() {
        if (android.os.Build.VERSION.SDK_INT >= 31) performGlobalAction(GLOBAL_ACTION_DISMISS_NOTIFICATION_SHADE)
        else if (rootInActiveWindow?.packageName?.toString()?.contains(".systemui") == true)
            performGlobalAction(GLOBAL_ACTION_BACK)
    }

    private fun <T> withoutProgressOverlay(operation: () -> T): T {
        val overlay = progressOverlay
        val entry = floatingEntry
        return overlayGate.run(hide = {
            // Always begin suppression on both windows, even when one removal fails.
            val progressHidden = overlay?.suppressForOperation() ?: true
            val entryHidden = entry?.suppressForOperation() ?: true
            check(progressHidden && entryHidden) { "Could not remove SeeTouch overlay windows" }
        }, restore = {
            overlay?.restoreAfterOperation()
            entry?.restoreAfterOperation()
        }, operation = operation)
    }

    fun refreshFloatingEntry() { floatingEntry?.render(TaskController.state.value) }
    fun acceptsEntryVoice(id: Long): Boolean = floatingEntry?.acceptsVoice(id) == true
    fun setEntryVoiceDraft(id: Long, text: String?) { floatingEntry?.voiceDraft(id, text) }

    companion object {
        private const val TAG = "SeeTouchA11y"
        private const val TAP_DURATION_MS = 80L
        private const val LONG_PRESS_DURATION_MS = 800L
        private const val SCREENSHOT_TIMEOUT_S = 5L
        private const val GESTURE_TIMEOUT_S = 5L

        @Volatile
        var instance: SeeTouchAccessibilityService? = null
            private set
    }
}
