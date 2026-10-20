package com.seetouch.app.overlay

import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicBoolean

/** Wait for UI window removal without depending on app frame/vsync delivery in the background. */
internal class OverlayOperationGate(
    private val post: (() -> Unit) -> Unit,
    private val settle: (() -> Unit) -> Unit,
    private val isUiThread: () -> Boolean,
    private val timeoutMillis: Long = 2000,
) {
    fun <T> run(hide: () -> Unit, restore: () -> Unit, operation: () -> T): T {
        check(!isUiThread()) { "Device operations must run on a background thread" }
        val ready = CompletableFuture<Unit>()
        val cancelled = AtomicBoolean(false)
        var begun = false // Accessed only by posted UI callbacks.
        post {
            if (!cancelled.get()) {
                begun = true
                try {
                    hide()
                    settle { if (!cancelled.get()) ready.complete(Unit) }
                } catch (error: Exception) { ready.completeExceptionally(error) }
            }
        }
        return try {
            try { ready.get(timeoutMillis, TimeUnit.MILLISECONDS) }
            catch (error: TimeoutException) {
                throw IllegalStateException("Timed out removing SeeTouch overlay windows before device operation", error)
            }
            operation()
        } finally {
            cancelled.set(true)
            post { if (begun) restore() }
        }
    }
}
