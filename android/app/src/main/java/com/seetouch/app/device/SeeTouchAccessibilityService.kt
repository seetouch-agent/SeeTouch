package com.seetouch.app.device

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.content.res.Configuration
import android.os.Bundle
import android.util.Log
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import com.seetouch.app.overlay.TaskProgressOverlay
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
    @Volatile private var progressOverlay: TaskProgressOverlay? = null

    @Volatile
    private var foregroundPackage: String? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        overlayJob?.cancel()
        progressOverlay?.close()
        val overlay = TaskProgressOverlay(this)
        progressOverlay = overlay
        overlayJob = overlayScope.launch { TaskController.state.collect { overlay.render(it) } }
        Log.i(TAG, "accessibility service connected")
    }

    override fun onDestroy() {
        overlayScope.cancel()
        progressOverlay?.close()
        progressOverlay = null
        if (instance === this) instance = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        if (windows.any { it.id == event.windowId &&
                it.type == AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY }) return
        val pkg = event.packageName?.toString() ?: return
        // 输入法窗口不代表前台 app 切换
        if (pkg.contains("inputmethod") || pkg.contains(".ime")) return
        foregroundPackage = pkg
    }

    override fun onInterrupt() {}

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        progressOverlay?.onConfigurationChanged()
    }

    // ------------------------- 查询 -------------------------

    fun currentPackage(): String? =
        foregroundPackage ?: rootInActiveWindow?.packageName?.toString()

    // ------------------------- 截图 -------------------------

    /** 截取默认显示屏,返回软件位图;失败返回 null。 */
    fun takeScreenshotBitmap(): Bitmap? = withoutProgressOverlay { takeUnobstructedScreenshot() }

    private fun takeUnobstructedScreenshot(): Bitmap? {
        val latch = CountDownLatch(1)
        var bitmap: Bitmap? = null
        val mainExecutor: Executor = mainExecutor
        takeScreenshot(
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
        )
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
        val dispatched = dispatchGesture(
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
        )
        if (!dispatched) return false
        latch.await(GESTURE_TIMEOUT_S, TimeUnit.SECONDS)
        return ok
    }

    // ------------------------- 文本输入 -------------------------

    /** 向当前焦点输入框写入文本(替换原内容),支持中文。 */
    fun setTextOnFocused(text: String): Boolean {
        val node = findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: findEditableNode(rootInActiveWindow)
            ?: return false
        val args = Bundle().apply {
            putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text
            )
        }
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
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

    fun pressBack(): Boolean = performGlobalAction(GLOBAL_ACTION_BACK)

    fun pressHome(): Boolean = performGlobalAction(GLOBAL_ACTION_HOME)

    private fun <T> withoutProgressOverlay(operation: () -> T): T {
        val overlay = progressOverlay
        return if (overlay == null) operation() else overlay.withoutOverlay(operation)
    }

    companion object {
        private const val TAG = "SeeTouchA11y"
        private const val TAP_DURATION_MS = 80L
        private const val SCREENSHOT_TIMEOUT_S = 5L
        private const val GESTURE_TIMEOUT_S = 5L

        @Volatile
        var instance: SeeTouchAccessibilityService? = null
            private set
    }
}
