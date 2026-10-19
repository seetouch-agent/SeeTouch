package com.seetouch.app.overlay

import org.junit.Assert.*
import org.junit.Test

class OverlayVisibilityTest {
    @Test fun progressUpdateCannotRevealWindowDuringCaptureOrGesture() {
        val state = OverlayVisibility()
        state.requested = true
        assertTrue(state.visible)
        state.beginOperation()
        state.beginOperation()
        state.requested = true // New progress arrives while both operations are hidden.
        state.endOperation()
        assertFalse(state.visible)
        state.endOperation()
        assertTrue(state.visible)
    }

    @Test fun operationCleanupDoesNotResurrectDismissedWindow() {
        val state = OverlayVisibility()
        state.requested = true
        state.beginOperation()
        try {
            state.requested = false // Task/overlay is closed before the screenshot returns.
            throw IllegalStateException("capture failed")
        } catch (_: IllegalStateException) {
            // The capture guard must release suppression even on failure.
        } finally {
            state.endOperation()
        }
        assertFalse(state.visible)
        state.requested = true // A later task can display normally.
        assertTrue(state.visible)
    }
}
