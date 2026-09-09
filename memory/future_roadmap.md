---
name: future-roadmap
description: 产品路线图、待解决问题、扩展方向、on-device APP 迁移计划
metadata:
  type: project
---

# 产品路线图

更新时间：2026-09-09

---

## 最终目标形态

**on-device Android APP** — 独立运行在手机上，不依赖电脑的原生 Android 应用。

**Why：** 产品需要独立性和便携性，PC 端控制只是验证阶段的权宜之计。

**当前状态：** ✅ **已落地（2026-07-05，Chaquopy 混合架构 Phase 0-3 全部完成）**。CPython 3.12 嵌入 APK，`seetouch/` Python 包原封不动跑在手机上；无障碍服务设备层 + Compose UI + 前台 Service；模拟器端到端验证通过，待真机（Xiaomi Android 12）回归。PC 端 PoC（uiautomator2 + ADB）仍保留作开发调试用。

**Python 更新同步机制：** Gradle sourceSet 直接指向仓库根 `seetouch/`，PC 端改完 Python 重新 `./gradlew assembleDebug` 即同步，零移植。

---

## 近期待办

### 0. 通用云端模型接入 ✅（2026-09-09）

- 默认使用 OpenAI Chat Completions 兼容视觉 API
- API key、Base URL、模型 ID 均可配置
- 支持选择 `reasoning_effort`，也可使用模型默认行为
- Gemini 与 Doubao 后端继续保留
- 后续只需验证更多服务商的协议差异，不维护服务商硬编码列表

### 1. 应用名解析方案 ✅（2026-07-05 全部完成，含应用名一等公民重构）

**目标：** 彻底解决 OPEN 启动的"中文名 → package"映射问题，缩小视觉兜底使用范围。

**方案：** Android PackageManager + `queryIntentActivities(MAIN/LAUNCHER)` + `loadLabel(pm)` 在手机端读"桌面图标名"。

**实现路径（分阶段）：**

#### Stage 1：helper APK 验证 ✅（2026-07-05 已完成）
- `android/` Gradle 工程已落地（用户 Android Studio 创建骨架，工程名 SeeTouch）
- `applicationId=com.seetouch.app`，minSdk26 / targetSdk36，零三方依赖
- exported 透明 Activity `helper/AppListExportActivity`（无 LAUNCHER filter、后台线程查询）
- 输出 `getExternalFilesDir/applist.json`（tmp → rename + `.done` 标记，含 request_id 回显防新旧混淆）
- PC 端 `scripts/pull_applist.py` 一键触发+pull；fallback = base64 分块打到 logcat tag `SEETOUCH_APPLIST`
- 模拟器验证通过（双通道一致、zh-CN 中文应用名正确）；真机（Xiaomi）回归待做
- 注意：manifest 必须声明 `<queries>` MAIN/LAUNCHER（Android 11+ 包可见性）

#### Stage 2：seetouch 集成 ✅（2026-07-05 已完成，方案升级）
- `device/android/app_index.py` 已落地：AppIndex + AppIndexSource 抽象（on-device/PC/测试三种源）
- PC 端读 `~/.seetouch/applist.json`（pull_applist.py 自动同步），不再需要运行时触发 helper
- 静态表/alias 已废弃（非保留）：OPEN 改为应用名一等公民，见 technical_decisions.md

#### Stage 3：最终迁移（on-device APP 时） ✅（2026-07-05 已完成并升级）
- 初版：`label_resolver` 注入点 + `DeviceBridge.packageForLabel`（仅精确匹配）
- 当天升级：改为 `index_source` 注入 + `DeviceBridge.launchableApps()` 全量索引，
  Python 侧 AppIndex 做精确/模糊匹配与候选反馈
- 持久化：learned cache 写入 App 内部存储（HOME 指向 filesDir）

**构建环境要求：**
- 本机仅 JDK 17，无 Android SDK / Gradle / Studio
- 需装 Android SDK（cmdline-tools → build-tools + platform）
- Android Studio 与 CLI 工具共用 ANDROID_HOME，装哪个都不返工

详见 2026-06-08 会话记忆。

---

### 2. 视觉兜底 Iteration 3 验证

**待测场景：** 打开"李跳跳"（在桌面"系统工具"文件夹内）

**验证点：**
- 模型识别"系统工具"文件夹
- CLICK 展开文件夹
- 找到李跳跳后 CLICK 启动
- Runner 触发 `learn_app_from_visual("李跳跳", "cn.litiaotiao.app")` 写入 cache
- 下次"打开李跳跳"秒开（走 learned 路径）

**如果失败：** 看 trace 找新的 prompt 缺口，继续迭代。

---

### 3. prompt 优化（观察到的问题）

**模型保险性重复点击：**
- B 站任务 step 4-5 重复点搜索框，7-8 重复点搜索按钮
- 任务能完成但低效

**优化方向：** Prompt 加"刚才点过的位置不用再点，等待页面响应，不响应再 WAIT"。

**已部分缓解（2026-06-19）：** 新增 BACK 返回键动作 + prompt 规则，解决了"打开 app 停在错误子页面只能反复点击/卡死"的一类场景（详见 [[technical_decisions.md]] BACK 节）。剩余的"同一步保险性重复点击"仍待按上面方向优化。

---

### 4. 测试覆盖扩展

**当前：** Python 单元测试覆盖核心 Runner、动作解析、应用启动和多个 reasoner；
已有打开抖音、B 站搜索等真机场景。

**待补充：**
- 敏感动作拦截真机验证（美团下单、支付宝转账）
- 视觉兜底真机回归（李跳跳、冷门 app）
- 复杂多步任务（对应比赛 11 条样例的真实版本）
- 异常场景（网络断开、app 崩溃、权限拒绝）

---

## 中期方向

### 1. 多轮对话 + 任务澄清

**当前：** 单轮指令 → 执行 → 完成

**目标：** 
- 指令不清晰时主动澄清（"你要买哪家店的？"）
- 任务执行中遇到歧义时询问用户（"有多个结果，要哪个？"）
- 支持多轮交互式任务

**实现要点：**
- Runner 支持暂停 / 恢复
- Reasoner 新增 `ASK_USER` 动作
- CLI 支持交互式输入

---

### 2. 用户偏好持久化

**场景：**
- 常用地址（外卖默认地址）
- 常用账号（支付宝 / 微信切换）
- 操作习惯（跳过广告 vs 看完广告）

**实现：** `~/.seetouch/preferences.json`

---

### 3. Web UI 前端

**目标：** 非技术用户友好界面

**进展（2026-06-19）：** 图形化**调试器**已落地，技术栈确定为 **Flask + Flask-SocketIO + 原生 HTML/CSS/JS（暗色主题）**，不再"待定"。已实现：任务输入框 ✓、实时截图 + 动作 Canvas 可视化 ✓、时间线历史回看 ✓。详见 [[development_history.md]] 2026-06-19 图形化调试器。

**剩余缺口（调试器是开发者工具，离面向终端用户的产品 UI 还差）：**
- **敏感动作确认弹窗**：调试器当前 `Guard(prompt_fn=lambda msg: True)` 自动批准，需做 WebSocket 双向确认
- 面向非技术用户的简化界面（隐藏 prompt / token / 原始输出等调试信息）
- 历史任务列表 + 跨会话回放（当前仅单会话内时间线）

**技术栈：** Flask + Flask-SocketIO + 原生 JS（已由调试器验证可行）

---

### 4. 跨平台支持

**扩展点已预留：** `device/base.py` Protocol

**候选平台：**
- `device/web/` — Selenium / Playwright 浏览器自动化
- `device/desktop/` — pyautogui / Windows UI Automation
- `device/ios/` — Appium / WebDriverAgent（需 macOS）

---

## 长期愿景

### 1. on-device APP 完整实现

**核心组件：**
- **Accessibility Service** — 替代 uiautomator2，直接读取 UI 树 + 注入手势
- **截图服务** — MediaProjection API，无需 ADB
- **PackageManager** — 应用名解析、启动、查询
- **前台 Activity** — 任务配置、历史查看、用户确认
- **后台 Service** — 长驻守护，接收任务指令

**技术栈：** Kotlin + Jetpack Compose + Room + WorkManager

**模型部署：**
- **云端推理**（当前方案）：HTTPS 调用任意 OpenAI 兼容视觉 API，亦可选 Gemini /
  Doubao，灵活但依赖网络
- **on-device 推理**（未来可选）：ONNX / TFLite / MediaPipe，隐私优先但模型能力受限

---

### 2. 多模态能力扩展

**当前：** 视觉输入（截图）→ 文本输出（动作）

**扩展方向：**
- **语音输入** — 语音 → 文本 → 任务（Google Speech API / 讯飞）
- **语音输出** — 任务进度 / 结果播报（TTS）
- **OCR 增强** — 复杂场景文本识别（PaddleOCR / Google ML Kit）

---

### 3. 任务模板 + Playbook

**目标：** 高频任务模板化，降低推理成本

**实现：**
- 用户标注"这次操作很好，保存为模板"
- 提取关键路径 → 生成 playbook（条件分支 + 兜底）
- 下次同类任务优先匹配 playbook，只在分支点调模型

**示例：**
- "美团外卖下单" playbook：OPEN 美团 → CLICK 外卖 Tab → TYPE 店名 → ...
- 分支点：搜索结果有多个店 → 调模型识别目标店

---

### 4. 安全与隐私

**当前：** 敏感动作前用户确认

**增强方向：**
- **沙盒模式** — 限制动作范围（只能操作指定 app）
- **审计日志** — 所有动作记录 + 截图存档
- **隐私保护** — 截图脱敏（模糊密码框、身份证号）
- **权限最小化** — Accessibility Service 权限按需申请

---

## 已知技术债

### 1. 坐标精度问题

**当前：** 归一化坐标 0-1000，单位约 1.44 像素（1440×3200 设备）

**问题：** 小控件（< 50×50 像素）点击可能偏移

**方案：**
- 提高归一化精度（0-10000）
- 或 perception 层做"点击中心"补偿

---

### 2. 中文输入兼容性

**当前：** `d(focused=True).set_text()` 走 UIAutomator

**已知问题：** 部分输入框不响应（游戏内输入框、WebView）

**方案：**
- fallback 到 ADBKeyboard IME（需手动切输入法）
- 或 Accessibility `ACTION_SET_TEXT`

---

### 3. 动态内容识别

**挑战：** 信息流 / 推荐列表每次内容不同

**当前：** 模型靠位置 / 文本特征识别

**改进方向：**
- OCR 提取关键词定位
- 或 UI 树元素 ID / content-desc 辅助

---

## 相关记忆

- [[product_overview.md]] — 产品定位、当前能力
- [[technical_decisions.md]] — OPEN 启动策略、视觉兜底机制
- [[development_history.md]] — 真机验证结果、已解决问题
- [[collaboration_style.md]] — 协作偏好、不要做的事
