package com.seetouch.app.ui

import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

@Composable
fun ConnectionTestButton(configJson: String, validationError: String?) {
    var testing by remember { mutableStateOf(false) }
    // A changed draft gets a separate result holder; an old request cannot label it successful.
    var result by remember(configJson) { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    OutlinedButton(enabled = !testing, onClick = {
        if (validationError != null) { result = validationError; return@OutlinedButton }
        testing = true
        result = null
        scope.launch {
            try {
                val json = withContext(Dispatchers.IO) {
                    runCatching {
                        Python.getInstance().getModule("seetouchapp.connection_test")
                            .callAttr("test_connection", configJson).toString()
                    }.getOrElse {
                        """{"success":false,"message":"测试未完成，请检查模型配置和网络","elapsed_seconds":0}"""
                    }
                }
                val o = JSONObject(json)
                result = "${o.optString("message")}（${o.optDouble("elapsed_seconds")} 秒）"
            } finally { testing = false }
        }
    }) { Text(if (testing) "正在测试…" else "测试连接") }
    Text("使用当前填写的配置发送内置示例图和固定问题，不读取手机屏幕。")
    result?.let { Text(it) }
}
