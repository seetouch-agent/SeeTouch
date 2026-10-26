package com.seetouch.app.bridge

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import com.seetouch.app.appindex.PackageManagerAppIndexProvider
import com.seetouch.app.device.SeeTouchAccessibilityService
import com.seetouch.app.task.TaskController
import java.io.ByteArrayOutputStream

/**
 * Python 侧唯一入口:seetouch/device/android_native/controller.py 通过
 * Chaquopy 调用本对象的静态方法完成全部设备操作。
 *
 * 设计约束:
 * - 方法签名只用基本类型 / ByteArray / List<String>,避免跨语言序列化陷阱
 * - 所有方法可从任意后台线程调用
 * - 无障碍服务未连接时抛 IllegalStateException,Python 侧包装成 DeviceError
 */
object DeviceBridge {

    @Volatile
    private var appContext: Context? = null

    /** App 启动时(Application.onCreate)注入,供 PackageManager / startActivity 使用。 */
    @JvmStatic
    fun init(context: Context) {
        appContext = context.applicationContext
    }

    @JvmStatic
    fun isServiceReady(): Boolean = SeeTouchAccessibilityService.instance != null

    @JvmStatic fun expectRevision(revision: Long) = TaskController.expectRevision(revision)
    @JvmStatic fun takeoverReason(): String? = service().takeoverReason()

    // ------------------------- 屏幕 -------------------------

    /** 截图并编码为 PNG 字节流(Python 侧 PIL 直接解码)。 */
    @JvmStatic
    fun screenshotPng(): ByteArray {
        val bitmap = service().takeScreenshotBitmap()
            ?: throw IllegalStateException("takeScreenshot failed")
        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
        bitmap.recycle()
        return out.toByteArray()
    }

    @JvmStatic
    fun screenWidth(): Int = service().resources.displayMetrics.widthPixels

    @JvmStatic
    fun screenHeight(): Int = service().resources.displayMetrics.heightPixels

    // ------------------------- 输入 -------------------------

    @JvmStatic
    fun click(xPx: Int, yPx: Int): Boolean =
        service().tap(xPx.toFloat(), yPx.toFloat())

    @JvmStatic
    fun longClick(xPx: Int, yPx: Int): Boolean =
        service().longPress(xPx.toFloat(), yPx.toFloat())

    @JvmStatic
    fun swipe(x1Px: Int, y1Px: Int, x2Px: Int, y2Px: Int, durationMs: Long): Boolean =
        service().swipe(
            x1Px.toFloat(), y1Px.toFloat(), x2Px.toFloat(), y2Px.toFloat(), durationMs
        )

    @JvmStatic
    fun typeText(text: String): Boolean = service().setTextOnFocused(text)

    @JvmStatic
    fun pressBack(): Boolean = service().pressBack()

    @JvmStatic
    fun pressHome(): Boolean = service().pressHome()

    // ------------------------- App 管理 -------------------------

    @JvmStatic
    fun currentPackage(): String? = service().currentPackage()

    @JvmStatic
    fun uiNodes(): Array<String> = service().uiNodes()

    /** 已安装且可启动(有 launcher 入口)的包名列表,供 OPEN fallback 匹配。
     *  返回数组而非 List:Chaquopy 对 java 数组有原生迭代支持。 */
    @JvmStatic
    fun installedPackages(): Array<String> {
        val pm = context().packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(intent, 0)
            .map { it.activityInfo.packageName }
            .distinct()
            .toTypedArray()
    }

    /** 桌面可启动应用的完整索引(复用 helper 的 AppIndexProvider),
     *  供 Python 侧 AppIndex 做应用名精确/模糊匹配。
     *  每行格式 "package\tlabel";返回数组:Chaquopy 对 java 数组有原生迭代支持。 */
    @JvmStatic
    fun launchableApps(): Array<String> =
        PackageManagerAppIndexProvider(context())
            .queryLaunchableApps()
            .map { "${it.packageName}\t${it.label}" }
            .toTypedArray()

    /** 通过 launcher intent 启动指定 package。 */
    @JvmStatic
    fun startApp(packageName: String): Boolean {
        val ctx = context()
        val intent = ctx.packageManager.getLaunchIntentForPackage(packageName)
            ?: return false
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        service().controlled { ctx.startActivity(intent) }
        return true
    }

    /** App 私有文件目录,Python 侧用作 runs/ 与 learned cache 的根目录。 */
    @JvmStatic
    fun filesDir(): String = context().filesDir.absolutePath

    // ------------------------- 内部 -------------------------

    private fun service(): SeeTouchAccessibilityService =
        SeeTouchAccessibilityService.instance
            ?: throw IllegalStateException(
                "SeeTouch accessibility service not connected; enable it in system settings"
            )

    private fun context(): Context =
        appContext
            ?: SeeTouchAccessibilityService.instance
            ?: throw IllegalStateException("DeviceBridge not initialized")
}
