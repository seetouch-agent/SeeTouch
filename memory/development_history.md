---
name: development-history
description: 开发历程、真机验证结果、重要 bug 复盘、技术演化轨迹
metadata:
  type: project
---

# 开发历程

更新时间：2026-07-05

---

## 项目起源

**原始背景：** 2026 中兴捧月初赛 - 移动端 GUI Agent 赛道

**转型时刻：** 2026-05-21，用户明确："现在我不是在打比赛了，可以完全自由发挥做产品。"

**Why：** 比赛 BaseAgent 有签名验证、强制 disabled thinking、固定 model 等约束，对产品是束缚；比赛文件提交时会被替换，共享代码反而是隐患。

**结果：** 从零构建 `seetouch/` 产品包，与比赛代码完全独立，互不 import。

---

## 技术选型决策（2026-05-12）

| 项 | 选择 | 不选的原因 |
|---|---|---|
| 设备控制层 | uiautomator2 | 纯 ADB+ADBKeyboard 中文输入门槛高；Appium 配置重、启动慢 |
| 代码复用 | **从零写，不 import 比赛代码** | BaseAgent 强约束太多；参考 prompt/解析逻辑即可 |
| 执行模式 | 自动连续 + 敏感动作前确认 | 全自动有真实风险，每步确认极慢 |
| 坐标体系 | 0-1000 归一化（沿用比赛） | 模型已习惯；perception 层负责像素换算 |
| OPEN 启动策略 | 静态表 + 多级 fallback | 用户接受静态表但要求兜底，不要硬编码全量 |
| Doubao thinking | 默认 `auto`（不再强制 disabled） | 比赛规则不再约束，模型按需启动 VisualCoT |

---

## 里程碑事件

### 2026-05-21：产品包首次提交

- **commit**: `ccce867` (40 文件 / +2887 行)
- **核心模块**: core / device / perception / reasoning / safety / cli
- **测试覆盖**: 40 单元测试全绿
- **真机验证**: Xiaomi rubens / Android 12 / 1440×3200 / 447 包

**首次真机测试结果：**

| 任务 | 步数 | 时长 | tokens(in/out) | 结果 |
|---|---|---|---|---|
| 打开抖音 | 2 | 11s | 5145/165 | ✓ L2 直通 |
| 在哔哩哔哩搜索采莲曲 | 6 | 27s | 16468/458 | ✓ 完整闭环（含中文输入） |

**验证点：**
- OPEN/CLICK/TYPE(中文)/COMPLETE 四个动作端到端通
- Prompt 里 screen_summary 链路在真机上正确延续
- B 站任务路径：OPEN → CLICK 搜索框 → TYPE "采莲曲" → CLICK 搜索按钮 → COMPLETE

---

### 2026-05-21：启用 Doubao thinking

- **commit**: `73a9e41`
- **默认**: `auto` 模式（模型按需 VisualCoT）
- **配置**: `SEETOUCH_THINKING_MODE` 环境变量
- **成本监控**: `_extract_usage` 带 `reasoning_tokens`

---

### 2026-06-01：WAIT 协议 + 移除 fuzzy 匹配

- **commit**: `dde04ba` (+293 行 / -167 行)
- **核心变更**:
  - 新增 WAIT 动作（0.5-5 秒）
  - 移除 fuzzy_match 整段代码
  - 视觉兜底命中检测（前台切换时自动学习）
  - thinking 模式默认改 `enabled`（vision 模型不支持 auto）

**测试覆盖**: 42 单元测试（从 40 → 42）

---

### 2026-06-17：提取为独立仓库

- **仓库路径**: `D:\科研\phone-agent`
- **默认分支**: `main`
- **保留历史**: 3 个产品相关 commit（ccce867 / 73a9e41 / dde04ba）
- **目录结构**: `seetouch/` 提到根目录

---

### 2026-06-19：全局重命名 Phone Agent → SeeTouch

- **commit**: `e7e8cbe` (46 文件 / 99 行改动)
- **动机**: 项目准备开源到 GitHub，需要一个有辨识度的名字
- **命名由来**: "See" + "Touch" — 先**看**屏幕（视觉理解），再**触**控操作。一个词点明产品基于纯视觉（截图 + VLM），而非无障碍树（Accessibility Tree）的技术路线
- **变更范围**:
  - Python 包: `phone_agent` → `seetouch`
  - 品牌名: `Phone Agent` → `SeeTouch`
  - 环境变量: `PHONE_AGENT_*` → `SEETOUCH_*`
  - 用户目录: `~/.phone_agent/` → `~/.seetouch/`
  - CLI 命令: `phone-agent` → `seetouch`
  - pyproject.toml、README、CONTRIBUTING、LICENSE、memory 全量同步
- **验证**: 42 个单元测试全部通过，零残留

---

### 2026-06-19：正式开源发布到 GitHub

- **仓库地址**: https://github.com/YidaYang/SeeTouch
- **开源协议**: Apache License 2.0（由 GitHub 自动生成）
- **发布流程**: rebase 合并 GitHub 生成的 LICENSE commit → push
- **项目介绍**: Vision-driven mobile GUI agent that sees your screen and operates your phone via natural language.

---

### 2026-06-19：图形化调试器

- **动机**: 之前只能命令行运行 + 看 log 调试，不直观且不支持单步执行
- **commit**: `fc5c0e5`（feat 主体）→ `5500317`（修 Windows 启动崩溃）→ `f15c664`（修单步卡死）
- **架构变更**:
  - Runner 从紧耦合 for 循环重构为 `start()` / `step()` / `run()` 状态机
  - `run()` 变成 `start() + 循环 step()` 的语法糖，CLI 行为完全不变
  - ActionOutput 新增 `prompt_text` 字段（模型输入与输出对称）
  - 新增 `StepResult` 数据类，每步产出完整可观测数据
  - Session trace 扩展写入 prompt_text / reasoning_time / execution_time
- **调试器模块**: `seetouch/debugger/`
  - 后端: Flask + Flask-SocketIO（threading async_mode，WebSocket 实时推送）
  - 前端: 原生 HTML/CSS/JS 暗色主题 Web UI
  - 线程模型: SocketIO 事件在主线程，`Runner.step()` 在 worker 线程，用 `threading.Event` 同步
  - 截图 Canvas 标注: CLICK 画红点+十字准星、SCROLL 画虚线箭头
  - 控制: Step（单步）/ Run（连续）/ Pause / Stop
  - 时间线: 可点击回看任意历史步骤
  - Prompt / Model Output 可折叠查看
- **启动方式**: `python -m seetouch debug [--port 5000]`
- **依赖**: `pip install seetouch[debugger]`（flask + flask-socketio）
- **已知缺口**: 敏感动作确认当前 `Guard(prompt_fn=lambda msg: True)` 自动批准，未做 WebSocket 双向确认弹窗
- **验证**: 42 个现有测试全部通过，0 回归 + 真机单步/连续执行通过

### 2026-06-27：调试器实时反馈增强

- **动机**: 每步执行 5-12 秒（80% 在等 VLM API），期间前端完全无变化，用户体验差
- **架构变更**:
  - 新增 `core/event_bus.py`：发布-订阅事件总线（线程安全、异常隔离、多消费者）
  - 新增 `core/log_bridge.py`：自定义 `logging.Handler` → EventBus 桥接，把 seetouch 命名空间下所有日志转发为事件
  - Runner 新增可选 `event_bus` 参数，在 4 个关键节点 emit 事件（截屏完成 → 推理开始 → 推理完成 → 执行开始）
  - DebugSession 订阅 EventBus 事件，通过回调推送 WebSocket
  - app.py 作为组装层：创建 EventBus → 传给 Runner + DebugSession → 注册 `step_progress` / `log` 回调
- **前端新增**:
  - 思考覆盖层：截图完成后 0.3s 内立即显示新截图 + 🧠 脉冲光环动画 + "AI 思考中" + requestAnimationFrame 驱动的实时计时器
  - 日志面板：主布局第三列，实时滚动显示 Python logging 日志（按级别着色、500 条上限、自动滚动开关）
- **设计决策**:
  - 用 EventBus 而非简单回调：天然支持多订阅者（进度 + 日志是两类消费者）、松耦合、未来加 metrics 收集零改动
  - LogBridge 生命周期与任务绑定：start_task() install，do_stop() / worker 退出 uninstall，不泄露 Handler
  - 无 EventBus 时（CLI `run()` 路径、旧测试）零开销，所有 emit 走 `if self._event_bus:` 守卫
- **验证**: 65 个测试全绿（原 45 + 新增 20），0 回归。真机端到端验证待用户接设备确认。

### 2026-06-30：动作后等待手机响应（settle delay）

- **动机**: 发现 Runner 执行动作（CLICK/SCROLL/TYPE/BACK）后立刻截图，拿到的是操作前的旧画面或过渡态动画帧，导致模型误判"上一步没生效"而重复操作。这也是之前记录的"模型保险性重复点击"的真正根因。
- **变更**:
  - `core/runner.py`：Runner 新增 `action_settle_seconds` 参数（默认 1.0s），在 `_execute()` 成功后、下一轮截图前 sleep，让手机界面稳定。WAIT/COMPLETE 和执行失败时跳过。
  - `device/android/controller.py`：移除 `open_app()` 里硬编码的 `time.sleep(1.0)`，等待逻辑统一收到 Runner 层管理。
- **设计决策**:
  - settle delay 不算进 `execution_time`（保持 execution_time 反映设备动作本身耗时）
  - 默认 1.0s（与 OPEN 原来硬编码的值一致，覆盖绝大多数页面跳转/动画场景）
  - 真正需要等久的场景（app 启动加载）由模型自行输出 WAIT
- **验证**: 65 个测试全绿，0 回归。

### 2026-07-05：调试器日志重复修复

- **动机**: 调试器右侧日志面板中，相同的日志条目会显示两遍。
- **根因**: `LogBridge` 把 `_EventBusLogHandler` 挂在 `seetouch` logger 上，但 Python logging 默认 `propagate=True`，同一条 LogRecord 会沿 logger 层级向上传播到 root logger。在 Flask-SocketIO `threading` async_mode 下，propagation 链路中的副作用（transport 层消息双发 / 回调重入）导致前端收到两份。
- **修复（commit `2c3a4bf`）**:
  - `LogBridge.install()` 时将 `seetouch` logger 的 `propagate` 设为 `False`，完全隔离日志链路
  - 同时在 `seetouch` logger 上挂一个 `StreamHandler`，保持 stderr 终端输出
  - `uninstall()` 时恢复 `propagate` 原始值并移除 `StreamHandler`
- **验证**: 69 个测试全绿（原 65 + 新增 4），0 回归。新增 3 个 LogBridge 测试：propagate 隔离验证、root handler 存在时无重复、stderr handler 生命周期。

### 2026-07-05：调试器步骤渐进式渲染

- **动机**: 原先前端在整步执行完毕收到 `step_result` 后才创建步骤页面，推理期间（5-12 秒）信息面板还停留在上一步的数据，用户体验差。正确的逻辑应该是截图完成就新建步骤页面，显示截图和思考动画，推理完成后填充 prompt / 动作 / 思维链，执行完成后补充执行结果。
- **变更（commit `31ca0d5`）**:
  - `core/runner.py`：`STEP_REASONING_DONE` 事件扩展，新增 `prompt_text`、`raw_output`、`reasoning_content`、`screen_summary`、`action_summary`、`usage` 字段
  - `debugger/debug_session.py`：`_on_reasoning_done` 转发新增字段到前端
  - `debugger/static/app.js`：三阶段渐进渲染
    - `screenshot_taken` → 新建步骤（时间线 pending 条目 + 重置面板 + 显示截图 + 思考动画）
    - `reasoning_done` → 填充推理结果（action、prompt、思维链、model output、metrics，执行结果标为"⏳ 执行中"）
    - `step_result` → 收尾（执行结果 success/failure、execution_time、notes、最终 usage）
  - `debugger/static/style.css`：新增 `.timeline-step.pending` 脉冲动画
- **设计决策**:
  - prompt 在 `reasoning_done` 阶段才可用（它在 `reasoner.predict()` 内部构建），不在截图阶段显示
  - `step_result` 从"创建步骤"变成"更新已有步骤"，前端用 `activeStepIndex` 关联
  - 时间线步骤先以 pending 状态展示（蓝色脉冲动画），`step_result` 到来后 finalize 为 success/failure/terminal
- **验证**: 69 个测试全绿，0 回归。新增 1 个测试：验证 `reasoning_done` 事件包含扩展字段。

### 2026-07-05：helper APK 应用索引导出（Stage 1 落地）

- **背景**: 用户本地 Android Studio 创建 `android/` Gradle 工程骨架（工程名 SeeTouch，为升级为独立主 App 预留），AGP 9.2.1 / Gradle 9.4.1 / compileSdk 36 / minSdk 26 / Kotlin（AGP 内置）。
- **变更（commit `9ba950c` + `d1a0bdb`）**:
  - `appindex/`：`AppEntry` / `AppIndexProvider`(抽象) / `PackageManagerAppIndexProvider`（queryIntentActivities(MAIN/LAUNCHER) + loadLabel，distinctBy package）/ `AppIndexJson`（schema_version=1）
  - `export/`：可插拔通道 —— `FileAppIndexExporter`（tmp→rename+.done 标记）、`LogcatAppIndexExporter`（base64 分块，tag `SEETOUCH_APPLIST`）
  - `helper/AppListExportActivity`：exported 透明 Activity，ADB `am start` 触发，文件通道失败自动兜底 logcat
  - PC 端 `scripts/pull_applist.py`：触发 + 轮询 .done + pull + 解析，支持 logcat 通道解码
- **两个坑（均已修）**:
  1. **Android 11+ 包可见性**：不声明 `<queries>` 时 queryIntentActivities 只返回 2 个应用；manifest 加 MAIN/LAUNCHER intent 声明后可枚举全部
  2. **.done 新旧混淆竞态**：PC 脚本会读到上一次导出的旧标记；协议加 request_id（PC 带 uuid 触发，.done 回显，只认本次 id）
- **验证**（云端 Pixel 6 模拟器 / Android 14）: file/logcat 双通道数据一致；zh-CN locale 下中文应用名正确（设置/相机/云端硬盘）；待真机（Xiaomi）回归。
- **下一步**: Stage 2 —— `device/android/app_index.py` 集成为 OPEN 策略 L0.5 层。

### 2026-07-05：on-device 独立 App 落地（Chaquopy 混合架构，Phase 0-3 全部完成）

用户确认三项决策：① Chaquopy 混合方案 ② minSdk 26→30（用 `AccessibilityService.takeScreenshot`，免 MediaProjection）③ 必要时可降 AGP（实际无需，Chaquopy 17.0 官方支持 AGP 9.2）。

- **Phase 0 技术验证（commit `86350d2`）**: Chaquopy 17.0 嵌入 CPython 3.12；`sourceSet.srcDir` 直接指向仓库根 `seetouch/`（Python 更新→重新构建即同步，零移植）；pip: openai 1.30.0 / pydantic 1.10.22 / httpx 0.27.2 / pillow。模拟器自检全绿 + 真实 Doubao 推理跑通。APK ~54MB。
- **Phase 1 设备层闭环（commit `741d8cf`）**: `device/SeeTouchAccessibilityService`（dispatchGesture 点击滑动 / takeScreenshot / ACTION_SET_TEXT 中文输入 / 前台包名跟踪）+ `bridge/DeviceBridge`（Python↔Kotlin 唯一门面，全静态方法）+ `seetouch/device/android_native/controller.py`（实现 DeviceController Protocol）。无 UI 跑通"打开设置"2 步端到端。
  - **坑 1**: Chaquopy 里 `java.util.List` 不可迭代 → DeviceBridge 返回 `Array<String>`
  - **坑 2**: `go_home()` 返回时窗口事件未到，`current_app()` 读到旧前台 → 视觉兜底 baseline 误学 launcher 包名；`go_home()` 后加 0.6s sleep
- **Phase 2 Compose UI + 前台 Service（commit `90d6006`）**: `task/TaskController`（单例 StateFlow<TaskUiState>，Python step/confirm 回调 → UI）、`task/TaskExecutionService`（前台服务 specialUse 子类型，任务线程）、`ui/MainActivity`（任务输入 + 实时步骤时间线 + 敏感动作确认弹窗(5 分钟超时默认拒绝) + 设置页）、`settings/AppSettings`（API key/模型 ID/最大步数/thinking 开关，与 PC 端 .env 可配置项对齐）。`run_task` 改为 config JSON 传参。
  - **关键发现**: agent 与手机同机运行，任务启动时首张截图是 SeeTouch 自己的界面，模型误判"应用正在处理"反复 WAIT 直到 stuck_loop 中止 → `task_entry` 在 runner 启动前先 `go_home()`
- **Phase 3 OPEN 接入 on-device 应用索引（commit `636df1c`）**: `AppLauncher` 新增可选 `label_resolver` 注入点（L1.5，仅精确匹配禁止模糊）；`DeviceBridge.packageForLabel` 复用 helper 的 `PackageManagerAppIndexProvider` 按显示名 trim+忽略大小写匹配。OPEN 层级变为 learned → L1 表 → L1' alias → **L1.5 label** → L2 直通 → L4 视觉兜底。
- **验证**（云端 Pixel 6 模拟器 / Android 14）: UI 全流程 "Open Clock" 3 步完成（OPEN→WAIT→COMPLETE），'时钟' 经 L1.5 命中 `com.google.android.deskclock` 免视觉兜底；时间线实时渲染、完成/中止状态、设置页读写均正常。PC 端 64 单测全绿。待真机（Xiaomi Android 12）回归。
- **helper 模式保留**: AppListExportActivity 原样可用，同一 APK 双模式。

### 2026-09-09：OpenAI 兼容 API 成为默认推理后端

- **目标**：允许用户通过 API key、Base URL 和模型 ID 接入任意支持视觉输入的 OpenAI
  Chat Completions 兼容服务，同时保留 Gemini 和 Doubao。
- **Python**：
  - 新增 `OpenAICompatibleReasoner`，复用既有 prompt、图像编码、历史摘要、动作解析、
    `ActionOutput` 和 token 统计链路。
  - 新增 reasoner factory，CLI 与调试器默认使用 `openai`，仍可显式选择 `doubao` /
    `gemini`。
  - `reasoning_effort` 支持 `minimal`、`low`、`medium`、`high`、`xhigh`；留空时不发送。
- **Android**：
  - 设置页新增 Base URL，thinking 开关升级为思考强度单选。
  - Chaquopy 任务入口默认组装 OpenAI 兼容 reasoner。
  - 读取旧 Doubao SharedPreferences key，并在旧配置未迁移时保留 Doubao 地址和模型默认值。
- **兼容性决策**：Android 固定的 `openai==1.30.0` 通过 `extra_body` 发送
  `reasoning_effort`，避免依赖较新 SDK 签名。

## 重大 bug 复盘

### 调试器不显示思维链（2026-06-26）

**症状：** thinking=enabled 时调试器只显示模型最终输出（Model Output），看不到 VisualCoT 思维链。

**根因（非显然）：** Doubao thinking 开启后，思维链放在 `response.choices[0].message.reasoning_content` 这个**独立字段**，**不在** `message.content` 里。`DoubaoReasoner._extract_response_text` 只读 `content`，所以思维链在数据进入系统的第一步就被丢弃——不是前端没渲染，是后端根本没拿到。

**修复（commit `c84f935`，端到端 6 处，沿用 BACK/prompt_text 链路模式）：**
- `doubao.py`：新增 `_extract_reasoning_content()` 从 `message.reasoning_content` 提取
- `action.py`：`ActionOutput` 加 `reasoning_content` 字段（默认 `""`，不破坏旧构造）
- `runner.py`：4 处 `StepResult` 构造透传
- `session.py`：`StepResult` 加字段
- `debugger/debug_session.py`：`StepData` + `to_dict` + `step_result_to_data` 透传
- 前端：Prompt 与 Model Output 之间新增「🧠 思维链」折叠区，**有内容才显示**（disabled 时为空 → 隐藏整个区块，不留空框，符合「thinking 开关由用户指定」约定）

**验证：** 45 个测试全绿（之前 42，期间又增了几个），集成测试 `test_runner_with_mock_device.py` 覆盖 `StepResult` 链路，0 回归。真机验证（开 thinking 跑任务看思维链）待用户接设备确认。

**经验：**
- **OpenAI 兼容 API 的"额外能力"往往在 message 的非标准字段上**（reasoning_content、tool_calls 等），`message.content` 只是最小公共子集。接新模型/新能力时，先 `dir(message)` 或打印整个 response 看有哪些字段，别假设都在 content 里。
- 这次踩坑印证了"数据丢在第一跳"的排查顺序：UI 不显示某数据，先逆着链路问"这字段是从哪一步开始有值的"，往往根因在最上游的提取处，而非展示层。
- **测试路径坑**：测试在仓库根 `tests/`（45 个），不是 `seetouch/tests/`（那里只有 10 个旧的 app_launcher）。跑全套用 `python -m pytest tests`。

### 调试器单步执行卡死（2026-06-19）

**症状：** 点 Step 执行完当前步骤后，只有 Stop 按钮可点，其他按钮全灰；一点 Stop 整个会话结束、记录像是丢了，无法继续单步。

**根因链：**
1. 前端点 Step → 后端 `on_step` 把状态置 `stepping` 并同步 `emit("status","stepping")`，前端按钮只剩 Stop（这是正确的执行中态）
2. worker 线程执行完该步，在后台把状态改回 `paused`，但**只 emit 了 `step_result`，从不 emit `status`**
3. 前端 `step_result` 处理器仅在 `terminal` 时才 `updateState`，非终止步不更新 → 前端永远停在 `stepping`，按钮永久卡死
4. 用户被迫只能 Stop，而 Stop 会 `debug_session = None` 拆掉会话 → 误以为"记录丢了"

**修复（commit `f15c664`）：**
- DebugSession 新增 `on_state_change` 回调 + `_set_state()` 方法（释放锁后再触发回调，避免死锁）
- worker 所有后台状态转换（`stepping→paused` / `→finished` / 异常兜底 / `finally`）统一经 `_set_state()` 推送 `status`
- app.py 注册 `on_state_change → socketio.emit("status")`
- 顺带修掉 `runner.step()` 抛异常时前端同样卡在 `stepping` 的同类 bug

**经验：** 工作线程的**每一次**状态变更都必须主动推送给前端，不能依赖"前端从其他事件里推断状态"。主线程同步 emit 的只是发起瞬间的中间态（stepping/running），后台线程完成后的回落态（paused/finished）若不显式推送，UI 必然与真实状态脱节。事件驱动 UI 里，状态机的每个出边都要有对应的通知边。

### 首次真机死循环（2026-05-20）

**症状：** "打开抖音" 连续 12+ 步重复 OPEN，直到用户打断。

**根因链：**
1. 模型输出 `com.zhiliaoapp.musically`（TikTok 海外版，非国内抖音）
2. 设备未安装，L3 fuzzy_match 在 447 个包里误匹配到 `com.biquge.ebook.app`（笔趣阁）
   - `com.` 公共前缀让相似度虚高
   - `app` 末尾段 3 字符未被黑名单化
3. `_learn` 立即把错误结果写入 cache，后续重试始终用错的
4. 模型识别出"这是笔趣阁不是抖音"，再次 OPEN，Runner 无死循环检测 → 无止境

**修复措施（全部已上线）：**
- **移除 fuzzy_match**（从 L3 直接跳 L4 视觉兜底）
- PACKAGE_ALIASES 表（TikTok → 抖音等）
- verify-then-learn（启动后轮询 `current_app()`，通过才写 cache）
- Runner 加 `consecutive_identical_actions=3`，3 步同动作即 abort
- Prompt 强调"必须用国内大陆版 package"

**经验：**
- fuzzy match 在 Android 包名场景假阳性极高，不适用
- learned cache 永远不要在执行前写入，只能事后基于结果回写
- 死循环检测是产品必须，不能依赖人工监控

详见 [[technical_decisions.md]]

---

### WAIT 协议缺失（2026-05-31）

**症状：** "在哔哩哔哩搜索采莲曲"，B 站启动后模型输出 `{"action": "WAIT"}`，parser 失败兜底返回 `Action(COMPLETE)`，任务被"假完成"提前终止。

**修复：**
- Action 新增 `ACTION_WAIT`，参数 `{"seconds": float}` 可选
- parser 失败的 fallback 从 COMPLETE 改成 WAIT
- Prompt 加 WAIT 用法说明

**经验：** 静默 fallback 到 COMPLETE 极其危险——任何 parser bug 都会被伪装成"任务完成"。模型有合理需求时优先**加协议**，不要用兜底掩盖问题。

---

### thinking_mode=auto 不支持（2026-05-31）

**症状：** API 报 400：`Unsupported thinking type for the current model: auto`

**根因：** doubao-seed-1-6-vision-250815 只支持 `enabled` / `disabled`，vision 模型的 thinking 模式集合比文本模型小。

**修复：** 默认改 `enabled`（准确率优先）

**经验：** 添加新模型时先用 `extra_body={"thinking": {"type": "..."}}` 探测支持的模式集合。

---

## 真机测试数据

### 设备环境
- **型号**: Xiaomi rubens（MIUI）
- **系统**: Android 12 / SDK 31
- **分辨率**: 1440×3200
- **已装应用**: 447 个包
- **静态表命中率**: 17/34（B 站、抖音、微信、QQ、小红书、淘宝、京东、拼多多、美团、高德、百度地图、去哪儿、支付宝、夸克等）

### thinking=enabled 性能（2026-05-31）

| 任务 | 步数 | 时长 | tokens(in/out) | 结果 |
|---|---|---|---|---|
| 打开抖音 | 2 | 102s | 5565/297 | ✓ L2 直通 |
| 在哔哩哔哩搜索采莲曲 | 9 | 67s | 28409/1705 | ✓（发现 WAIT bug，修复后通过） |

**观察：**
- 步均 7-12s，比 disabled 慢 2-3 倍
- 识别准确率明显提高（B 站开屏广告自动跳过、复杂搜索场景不再瞎点）
- B 站任务有 step 重复（4-5 重复点搜索框，7-8 重复点搜索按钮）—— 模型保险性重复，任务能完成但低效

**优化方向：** Prompt 可加"刚才点过的位置不用再点，等待页面响应，不响应再 WAIT"。

---

## 视觉兜底演化（三轮迭代）

测试对象：**李跳跳**（`cn.litiaotiao.app`，无障碍跳广告工具），装了但桌面没直接图标——被放在桌面第一页"系统工具"文件夹里。

### Iteration 1：无 prompt 引导
- **现象**: step 1 OPEN 失败 → step 2/3 继续 OPEN 同名 app → 死循环
- **根因**: Runner 加的 note 只是 `open_app_visual_fallback: 李跳跳`，模型不知道要换 CLICK

### Iteration 2：note + prompt 加硬规则
- **note 激进措辞**: "❗ OPEN 'xxx' 失败，本步绝对不要再 OPEN 同名 app，必须 CLICK 桌面图标"
- **prompt 硬规则**: 历史里看到 `OPEN '<app>' 失败` 字样，本步绝对不能再 OPEN
- **效果**: 不再死循环，正确 SCROLL 翻页 + 上滑抽屉，但翻 8 页找不到（因为在文件夹里）

### Iteration 3：桌面文件夹支持（待真机验证）
- **识别**: 图标内 4/9 个 app 预览 + 外框 + 分组名
- **展开**: CLICK 文件夹中心
- **退出**: CLICK 屏幕底部空白（如 `[500,950]`）
- **放弃条件**: 翻完所有页 + 探索过名字相关的文件夹 + 抽屉滚到底

**经验：** 桌面文件夹是 Android 设备非常普遍的 UI 元素，产品 prompt 不能假设 app 一定有顶层图标。

---

## MIUI 踩坑（已知问题，无需修复）

1. **`python -m uiautomator2 init` 末尾会报 ADBKeyboard.apk 安装失败** —— MIUI 默认拦截 USB 安装来源不明应用。**这不影响主流程**：产品的中文输入用 `d(focused=True).set_text()` 走原生 UIAutomator，不依赖 ADBKeyboard IME。出现 `Failure Unknown` 直接忽略。

2. **手机端开发者选项至少要开**：USB 调试、USB 调试(安全设置)、USB 安装。

3. u2 主服务装好的标志是 `[server] INFO: http server listening on *:9008`。

---

## OPEN 重构：应用名一等公民（2026-07-05）

**动机（用户拍板）：** VLM 没有包名知识只有应用名知识，旧的"输出包名+五级兜底"不好用。

**新链路：** VLM 输出应用桌面显示名 → AppIndex（learned cache → 精确 → 唯一强模糊直接启动）
→ 歧义/未命中 raise `OpenAppNotFound(suggestions)` → Runner 把候选写 notes 反馈 VLM 重选/换关键词
→ 累计 3 次未命中升级视觉兜底。静态表 `app_table.py`、alias、包名直通（VLM 路径）全部移除。

**关键文件：**
- 新增 `seetouch/device/android/app_index.py`（AppIndex/AppIndexSource/StaticAppIndexSource/AppListJsonSource）
- 重写 `app_launcher.py`；`base.py` 新增 `OpenAppNotFound`
- `runner.py`：`max_open_misses` 计数 + `_arm_visual_fallback()`（NeedsVisual 路径不再重复 go_home）
- Kotlin：`DeviceBridge.launchableApps()` 替代 `packageForLabel()`
- PC 端：`AppListJsonSource` 读 `~/.seetouch/applist.json`，`pull_applist.py` 自动同步一份

**验证：** 83 个测试全过（新增 app_index 单测 + launcher 单测重写 + Runner 候选反馈/升级集成测试）；
模拟器 e2e："打开时钟" 2 步完成；"打开哔哩哔哩"（未安装）反馈→换关键词→3 次后正确升级视觉兜底。

**踩坑：** 模拟器 GMS 应用（Maps/Gmail）无中文资源，label 是英文 "Maps"，"地图"匹配不上是数据问题不是代码问题——真机中文环境无此问题。

---

## 首次本地 APK 编译（2026-07-06）

- **构建环境**:
  - Android Studio: `D:\Programs\Android\Android Studio`（内含 JBR/JDK 21.0.10）
  - Android SDK: `C:\Users\Danny\AppData\Local\Android\Sdk`（Platform 36.1 + Build-Tools 36/37）
  - Gradle 9.4.1（wrapper）+ Chaquopy 16.x（CPython 3.12 嵌入）
- **踩坑（commit `4f3f59c`）**: 项目路径 `D:\科研\` 含中文，AGP 默认拒绝非 ASCII 路径。修复：`gradle.properties` 加 `android.overridePathCheck=true`
- **首次构建耗时**: ~6 分钟（下载 Chaquopy CPython 3.12 运行时 + pip 依赖 openai/pydantic/httpx/pillow，arm64-v8a 和 x86_64 双 ABI）
- **产物**: `android/app/build/outputs/apk/debug/app-debug.apk`（65.7 MB，含 CPython）
- **环境变量**: 已配置用户级 `JAVA_HOME`、`ANDROID_HOME`，并将 platform-tools / Studio JDK bin 加入 PATH

---

## 相关记忆

- [[technical_decisions.md]] — fuzzy 匹配移除详细原因、WAIT 协议设计
- [[product_overview.md]] — 产品定位、核心能力
- [[future_roadmap.md]] — 下一步计划、on-device APP 迁移路径
