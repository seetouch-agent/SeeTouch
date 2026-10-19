package com.seetouch.app.device

/** Pure local classification. Return fixed labels, never field contents or credentials. */
object SensitiveScreenDetector {
    data class Node(val text: String, val password: Boolean, val editable: Boolean)
    fun reason(nodes: List<Node>): String? {
        if (nodes.any { it.password }) return "检测到密码输入，请在目标应用手动完成"
        val text = nodes.joinToString(" ") { it.text }.lowercase()
        if (listOf("支付密码", "payment password", "pay password").any { it in text })
            return "需要用户输入支付密码"
        if (listOf("验证码", "verification code", "one-time", "验证短信").any { it in text } || Regex("\\botp\\b").containsMatchIn(text))
            return "需要用户完成验证码验证"
        if (listOf("指纹", "面容", "人脸识别", "生物识别", "fingerprint", "face id", "biometric").any { it in text })
            return "需要用户完成生物识别"
        if (listOf("滑块", "拖动滑动", "拖动滑块", "slide to verify", "captcha").any { it in text })
            return "需要用户完成滑块或人机验证"
        if (listOf("请先登录", "登录后继续", "登录以继续", "sign in to continue", "log in to continue").any { it in text } ||
            (nodes.any { it.editable } && listOf("登录", "登陆", "sign in", "log in").any { it in text } &&
                (listOf("手机号", "用户名", "账号", "邮箱", "phone number", "email", "username").any { it in text } ||
                    !listOf("搜索", "search").any { it in text })))
            return "需要用户在目标应用完成登录"
        return null
    }
}
