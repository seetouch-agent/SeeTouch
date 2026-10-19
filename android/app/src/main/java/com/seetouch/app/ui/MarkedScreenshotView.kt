package com.seetouch.app.ui

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Only app-private run images can be opened; model text cannot turn this into a file browser. */
class MarkedScreenshotView(context: Context) : View(context) {
    private var bitmap: Bitmap? = null
    private var source = ""
    private var points = emptyList<Pair<Float, Float>>()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    init { contentDescription = "操作前截图，红圈标注目标位置"; minimumHeight = 120 }
    fun setSource(path: String?, parameters: String = "{}") {
        val key = "$path|$parameters"
        if (key == source) return
        source = key
        bitmap?.recycle(); bitmap = null
        val file = privateImage(context, path)
        if (file != null) {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(file.path, bounds)
            var sample = 1
            while (bounds.outWidth / sample > 960 || bounds.outHeight / sample > 1600) sample *= 2
            bitmap = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
        }
        points = runCatching {
            val p = JSONObject(parameters)
            listOfNotNull(p.optJSONArray("point"), p.optJSONArray("start_point"), p.optJSONArray("end_point"))
                .mapNotNull { point(it) }
        }.getOrDefault(emptyList())
        invalidate()
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(Color.rgb(30, 35, 43))
        val image = bitmap ?: return
        val scale = minOf(width.toFloat() / image.width, height.toFloat() / image.height)
        val w = image.width * scale; val h = image.height * scale
        val rect = RectF((width - w) / 2, (height - h) / 2, (width + w) / 2, (height + h) / 2)
        paint.style = Paint.Style.FILL
        canvas.drawBitmap(image, null, rect, paint)
        paint.color = Color.RED; paint.style = Paint.Style.STROKE; paint.strokeWidth = 3 * resources.displayMetrics.density
        points.forEach { (x, y) -> canvas.drawCircle(rect.left + x * w / 1000,
            rect.top + y * h / 1000, 13 * resources.displayMetrics.density, paint) }
    }
    private fun point(a: JSONArray): Pair<Float, Float>? = if (a.length() != 2) null else
        (a.getDouble(0).toFloat().coerceIn(0f, 1000f) to a.getDouble(1).toFloat().coerceIn(0f, 1000f))
    companion object {
        fun privateImage(context: Context, path: String?): File? = runCatching {
            if (path.isNullOrBlank()) return null
            val base = File(context.filesDir, "runs").canonicalFile
            val file = File(path).canonicalFile
            file.takeIf { it.isFile && it.extension == "png" && it.path.startsWith(base.path + File.separator) }
        }.getOrNull()
    }
}
