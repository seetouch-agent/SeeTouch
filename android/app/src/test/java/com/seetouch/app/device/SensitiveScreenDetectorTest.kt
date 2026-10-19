package com.seetouch.app.device

import org.junit.Assert.*
import org.junit.Test

class SensitiveScreenDetectorTest {
    @Test fun credentialPagesTriggerTakeoverWithoutReturningContents() {
        val cases = listOf("请输入验证码", "支付密码", "使用指纹验证", "面容识别", "拖动滑块完成验证", "请先登录")
        for (text in cases) {
            val reason = SensitiveScreenDetector.reason(listOf(SensitiveScreenDetector.Node(text, false, false)))
            assertNotNull(text, reason)
            assertFalse(reason!!.contains("private-value"))
        }
        assertNotNull(SensitiveScreenDetector.reason(listOf(
            SensitiveScreenDetector.Node("private-value", true, true))))
    }

    @Test fun loginFormTriggersButOrdinarySearchAndLoginLinkDoNot() {
        assertNotNull(SensitiveScreenDetector.reason(listOf(
            SensitiveScreenDetector.Node("登录", false, true))))
        assertNull(SensitiveScreenDetector.reason(listOf(
            SensitiveScreenDetector.Node("搜索视频", false, true))))
        assertNull(SensitiveScreenDetector.reason(listOf(
            SensitiveScreenDetector.Node("登录", false, false))))
        assertNull(SensitiveScreenDetector.reason(listOf(
            SensitiveScreenDetector.Node("搜索", false, true),
            SensitiveScreenDetector.Node("登录", false, false))))
    }
}
