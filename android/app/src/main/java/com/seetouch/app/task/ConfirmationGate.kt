package com.seetouch.app.task

import org.json.JSONObject
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import kotlin.math.ceil

/** One decision wins; late taps can never authorize an expired confirmation. */
class ConfirmationGate(timeoutSeconds: Int, private val clock: () -> Long = System::nanoTime) {
    val deadlineNanos = clock() + TimeUnit.SECONDS.toNanos(timeoutSeconds.toLong())
    private val decision = CompletableFuture<String>()
    @Synchronized fun respond(approved: Boolean): Boolean {
        if (clock() >= deadlineNanos) return cancel("timeout")
        return decision.complete(value(approved, if (approved) "allow" else "deny"))
    }
    @Synchronized fun cancel(reason: String): Boolean = decision.complete(value(false, reason))
    fun await(): String = try {
        decision.get((deadlineNanos - clock()).coerceAtLeast(0), TimeUnit.NANOSECONDS)
    } catch (_: TimeoutException) { cancel("timeout"); decision.get() }
    companion object {
        fun secondsRemaining(deadline: Long, now: Long = System.nanoTime()): Int =
            ceil((deadline - now).coerceAtLeast(0) / 1_000_000_000.0).toInt()
        private fun value(approved: Boolean, choice: String): String = JSONObject()
            .put("approved", approved).put("choice", choice).put("timestamp", System.currentTimeMillis() / 1000.0).toString()
    }
}
