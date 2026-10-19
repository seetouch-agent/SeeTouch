package com.seetouch.app.overlay

/** Main-thread state: progress updates cannot reveal a window during capture/input. */
internal class OverlayVisibility {
    var requested: Boolean = false
    private var operations = 0
    val visible: Boolean get() = requested && operations == 0

    fun beginOperation() { operations++ }
    fun endOperation() {
        check(operations > 0)
        operations--
    }
}
