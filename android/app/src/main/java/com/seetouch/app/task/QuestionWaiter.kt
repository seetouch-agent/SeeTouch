package com.seetouch.app.task

import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

/** Timing out pauses the host; it never fabricates an answer or terminates the waiting question. */
object QuestionWaiter {
    fun <T> await(future: CompletableFuture<T>, onTimeout: () -> Unit,
        timeoutMillis: Long = TimeUnit.MINUTES.toMillis(5)): T =
        try { future.get(timeoutMillis, TimeUnit.MILLISECONDS) }
        catch (_: TimeoutException) { onTimeout(); future.get() }
}
