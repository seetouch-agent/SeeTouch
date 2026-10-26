# SeeTouch

Vision-driven mobile GUI agent that sees your screen and operates your phone via natural language.

SeeTouch 通过屏幕截图和视觉语言模型（VLM）理解手机界面，将自然语言指令转换为 Android 操作。项目仓库：[seetouch-agent/SeeTouch](https://github.com/seetouch-agent/SeeTouch)。

## 当前支持的运行方式

| 入口 | 设备控制 | 当前推理后端 | 敏感动作确认 |
|---|---|---|---|
| PC 命令行 `run` | ADB + uiautomator2 | 默认 Gemini；可选 `--reasoner doubao` 或 `--reasoner openai` | 命中关键词规则后在终端确认 |
| PC Web 调试器 `debug` | ADB + uiautomator2 | 默认 Doubao，可用 `--reasoner` 选择 Gemini / OpenAI | **当前自动批准，尚未接入交互确认** |
| Android 独立 App | 无障碍服务 + Kotlin/Python 桥接 | 新安装默认 OpenAI 兼容接口，支持 Chat Completions / Responses；保留旧豆包配置 | App、浮窗或通知确认，默认 60 秒超时拒绝 |

Android App 不依赖电脑执行任务，但仍需联网调用云端模型。悬浮球可从当前应用发起任务；进度窗显示当前步骤、阶段及最近 5 步。App、浮窗和通知支持暂停、继续、终止、追问与接管；敏感确认显示截图标注和倒计时。任务结束提供持久化结果卡片、查询答案来源、完成通知、本地评价及可选语音播报；通知不展示屏幕摘要或答案。构建与安装见 [Android 指南](android/README.md)。

Android 1.5 新增[本地记忆与经验积累](docs/memory-and-learning.md)：完成任务时由结束响应提炼通用经验，下次匹配相关任务后加载；可管理偏好、纠正或停用经验。个人偏好建议须确认保存，评价会影响操作经验的后续复用。每一步继续观察当前屏幕，经验不直接重放动作。

记忆功能对应 1.5 源码及本地构建；当前公共安装包下载仍为 1.4。

1.5.1 修复截图前等待浮窗隐藏导致的 `screenshot failed: Check failed` 路径：主线程统一移除两个浮窗、使用定时回调代替帧等待，并把无障碍事件节点扫描移到后台。此修复仍需在发生问题的手机上复验，见[安卓说明](android/README.md)。

本说明对应 2026-10-19 的工作树，包含 Android OpenAI 兼容接口、连接测试、执行控制及追问/人工接管；运行验证范围见文末。

## 下载与安装

**[下载 Android APK（1.4）](https://github.com/seetouch-agent/SeeTouch/releases/download/v1.4/SeeTouch-1.4-debug.apk)** · [Release 说明](https://github.com/seetouch-agent/SeeTouch/releases/tag/v1.4) · [SHA-256 校验文件](https://github.com/seetouch-agent/SeeTouch/releases/download/v1.4/SHA256SUMS.txt)

支持 Android 11 及以上，包含 arm64-v8a / x86_64，安装包约 69.3 MB。这是用于试用与评审的 Debug 签名安装包，与 Python 包版本独立。

1. 在安卓设备下载 APK，按系统提示允许当前浏览器或文件管理器安装该应用。
2. 安装后在系统设置中启用 SeeTouch 无障碍服务，并按需允许通知权限。
3. 在 App 设置中填写支持图片输入的模型 API Key、Base URL 和模型 ID，选择对应协议，点击“测试连接”后开始任务。模型服务需要联网，调用费用以服务商规则为准。

完整说明见 [Android 指南](android/README.md)；开发者也可从源码构建。

## 文档导航

- [架构对照](ARCHITECTURE_COMPARISON.md) / [改造记录](MIGRATION_LOG.md)：与 nanoMuse 的逐模块对照、许可证边界和每项修改的证据。
- [Agent 优化轮次](AGENT_OPTIMIZATION_ROUNDS.md)：以复杂多步任务驱动的 6 轮改造、参考源码和前后对比。
- [端到端测试指南](E2E_TEST_GUIDE.md) / [端到端测试报告](E2E_TEST_REPORT.md)：模拟器、真实模型、独立设备状态判定及 PC/APK 两条路径结果。
- [Android 构建与使用](android/README.md)：安装、模型设置、浮窗及任务结果。
- [Android 交互说明](docs/android-interactions.md)：连接测试、暂停/继续、追问、接管、确认与回放。
- [OpenAI 兼容接口指南](docs/openai-compatible.md) / [Gemini 指南](docs/gemini-integration.md)：后端配置与验证范围。
- [产品概览](memory/product_overview.md) / [技术决策](memory/technical_decisions.md) / [路线图](memory/future_roadmap.md)：当前能力、实现细节与待办。
- [开发历程](memory/development_history.md)：保留旧版本演化，已替换的方案不作为当前功能说明。

## PC 快速开始

需要 Python 3.10+、Android Platform Tools（`adb`），以及已开启 USB 调试并授权电脑的 Android 设备。先用 `adb devices` 确认连接状态。

```bash
git clone https://github.com/seetouch-agent/SeeTouch.git seetouch
cd seetouch
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

macOS / Linux：

```bash
source .venv/bin/activate
cp .env.example .env
```

安装依赖，然后在本地 `.env` 中填入所选服务的 API key：

```bash
python -m pip install -e .
```

### Gemini：CLI 默认后端

从 [Google AI Studio](https://aistudio.google.com/) 获取你有权使用的凭据。以下模型名是代码中的默认值，实际可用性、收费和配额以你的 API 项目为准；项目不保证固定免费额度。

```dotenv
GEMINI_API_KEY=replace-with-your-key
GEMINI_MODEL_ID=gemini-3.1-flash-lite
```

```bash
python -m seetouch run "打开设置"
python -m seetouch run "在哔哩哔哩搜索采莲曲" --reasoner gemini
```

配置与实现边界见 [Gemini 指南](docs/gemini-integration.md)。

### Doubao：CLI 可选，调试器和 Android App 使用

```dotenv
VLM_API_KEY=replace-with-your-key
DOUBAO_MODEL_ID=doubao-seed-1-6-vision-250815
DOUBAO_API_URL=https://ark.cn-beijing.volces.com/api/v3
SEETOUCH_THINKING_MODE=enabled
```

```bash
python -m seetouch run "打开设置" --reasoner doubao
```

`SEETOUCH_THINKING_MODE` 仅由 Doubao 适配器读取，Gemini 和 OpenAI 适配器不读取它。代码接受 `enabled`、`disabled`、`auto`；历史测试中的默认 Doubao Vision 模型不支持 `auto`，其他模型的支持情况需单独核实。

### OpenAI / OpenAI 兼容中转站

PC 端要求 `openai>=1.66.0`，以支持 Responses 和 `output_text`。已有环境请重新执行
`python -m pip install -e .` 更新依赖；仅更新源码不会升级 SDK。

使用支持图片输入的模型，在本地 `.env` 中配置：

```dotenv
OPENAI_API_KEY=replace-with-your-key
OPENAI_MODEL_ID=replace-with-your-vision-model-id
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_MODE=chat_completions
OPENAI_TIMEOUT=60
OPENAI_MAX_RETRIES=1
OPENAI_REASONING_EFFORT=
```

中转站请填写服务商提供的 API 基础地址（常见为 `https://your-host/v1`），
不要包含末尾的 `/chat/completions` 或 `/responses`；程序会按协议自动追加。
`OPENAI_API_MODE=chat_completions` 使用 Chat Completions；仅支持 Responses 的模型请设置
`OPENAI_API_MODE=responses`。程序不根据模型名称猜测协议，也不会在失败后自动换用另一种协议。
SDK 可能按 `OPENAI_MAX_RETRIES` 重试请求；调用费用以服务商规则为准。
Key 和模型 ID 必须来自同一个服务商；只支持文本的模型不适用于此入口。
第三方即使暴露 Responses 路由，也可能限制为特定客户端；403 应按服务商要求处理。
此适配器不发送豆包的 `thinking` 参数，也不读取 `VLM_API_KEY`。
可用 `OPENAI_REASONING_EFFORT` 显式设置模型支持的思考强度；留空不发送参数。
Chat Completions 使用 `reasoning_effort`，Responses 使用 `reasoning.effort`。
各服务商支持值不同，`none` 表示显式请求关闭推理，不能等同于留空。

```powershell
python -m seetouch run "打开设置" --reasoner openai --max-steps 3
```

调试顺序：

1. `python -m seetouch run --help` 确认 `--reasoner` 包含 `openai`。
2. 先用上面的小步数命令测试。日志应显示 `provider=openai`、模型名称和 HTTP 请求状态。
3. 401/403 检查 Key、模型权限和客户端限制；404 检查基础地址、模型 ID，以及服务是否提供所选协议；
   400 按响应说明检查协议、模型是否支持图片和 base64 data URL；429 检查配额或限流。
4. 超时可增加 `OPENAI_TIMEOUT`（每次请求的秒数）；排查重试时设 `OPENAI_MAX_RETRIES=0`。
5. 查看 `runs/<task_id>/step_001.png`、`trace.jsonl` 和 `summary.json`，或执行
   `python scripts/replay.py runs/<task_id>`。输出解析失败会降级 WAIT；API 错误、空文本或
   输出截断会终止任务，结果为 `completed=False`，而不会误报完成。

`trace.jsonl` 保存动作、摘要、执行结果、提示词、用量和交互等信息，普通步骤不保存完整模型原始输出或推理内容，离线回放不能恢复这些字段。启用任务控制时，暂停期间收到的旧预测可能连同原始输出保存在 `interactions.jsonl`；分享记录前同样需要检查。

已有进程环境变量优先于 `.env`；修改 `.env` 后重新启动命令。截图和任务会发送到配置的服务商。
分享日志和运行产物前请去除密钥及屏幕中的私人信息。Web 调试器用 `python -m seetouch debug --reasoner openai` 选择此后端。
Android 在设置页填写 Base URL、Key 和模型 ID，并按服务商说明选择 Chat Completions 或 Responses。高级设置支持思考强度、5–600 秒请求超时及最大步数；各后端分别保存凭据，保留原豆包 thinking 设置。

### CLI 参数和环境变量

```bash
python -m seetouch run --help
python -m seetouch run "打开设置" --reasoner doubao --max-steps 20 --runs-dir ./runs
```

| 设置 | 默认值 / 含义 |
|---|---|
| `--reasoner` | `gemini`；也可选 `doubao` 或 `openai`，不是环境变量自动选择 |
| `--serial` / `SEETOUCH_DEVICE_SERIAL` | 指定设备；未指定时由 uiautomator2 连接 |
| `--max-steps` / `SEETOUCH_MAX_STEPS` | 45 |
| `--runs-dir` / `SEETOUCH_RUNS_DIR` | `runs` |
| `SEETOUCH_LOG_LEVEL` | `INFO` |
| `SEETOUCH_APPLIST_PATH` | PC 应用索引路径，默认 `~/.seetouch/applist.json` |

已有环境变量优先于 `.env`。Gemini key 按 `GEMINI_API_KEY → VLM_API_KEY` 读取；Doubao 按 `VLM_API_KEY → DOUBAO_API_KEY` 读取；OpenAI 兼容后端仅读取 `OPENAI_API_KEY`。不同厂商凭据不能混用。

CLI 和调试器共用 Reasoner 工厂，但保留各自原有默认后端。`UnifiedConfig` 已存在，但入口仍使用兼容的 `AppSettings` 和各 Reasoner 配置。该类中的额外环境变量并未全部接入运行入口，详见 [技术决策](memory/technical_decisions.md)。

### 应用索引和运行记录

安装 SeeTouch Android APK 后，可从仓库根目录导出手机应用显示名索引：

```bash
python scripts/pull_applist.py
```

脚本默认写入当前目录 `applist.json`，同时同步到 `~/.seetouch/applist.json`。文件通道失败时可显式改用 `--channel logcat`；PC 脚本不会自动从失败的文件通道切换。索引包含应用和设备信息，不应直接公开。

每次运行在 `runs/<task_id>/` 保存 `step_001.png` 等截图、`trace.jsonl` 和 `summary.json`。回放是打印已有记录，不会重新操作手机：

```bash
python scripts/replay.py runs/<task_id>
```

环境诊断入口为 `python scripts/doctor.py`。它会连接设备，当前仅检查 Doubao 凭据且打印 key 前缀；仅配置 Gemini 或 OpenAI 时可能报缺少 key，不能据此判断这些后端配置无效，分享输出前应脱敏。

## Web 调试器

```bash
python -m pip install -e ".[debugger]"
python -m seetouch debug --port 5000
```

浏览器访问 `http://localhost:5000`。支持 Step / Run / Pause / Stop、截图动作标注、步骤时间线、模型输入输出、模型返回的推理内容、token 统计和实时日志。

调试器默认使用 Doubao；通过 `--reasoner gemini` 或 `--reasoner openai` 显式切换，单独设置 key 不会切换后端。服务监听 `0.0.0.0`，允许任意 CORS 来源且没有用户认证；敏感动作确认回调直接返回同意。应仅在受控开发环境运行，避免暴露到不可信网络，不用它执行支付、发消息或删除等敏感任务。

## 架构与动作

```text
seetouch/
├── core/           # Action、Task、Runner、Session、EventBus、异常类型
├── device/
│   ├── base.py     # DeviceController Protocol
│   ├── android/    # PC uiautomator2、AppIndex、AppLauncher
│   └── android_native/  # Android App 的 Kotlin 桥接适配器
├── perception/     # screen.py：缩放、坐标换算、图像编码
├── reasoning/      # base.py、doubao.py、gemini.py、openai.py、parser.py、prompts.py
├── safety/         # 关键词规则和确认回调
├── debugger/       # Flask / SocketIO + 原生 Web UI
└── cli/            # 命令行组装
android/            # Kotlin / Compose / Chaquopy App
scripts/            # doctor.py、pull_applist.py、replay.py
tests/              # 当前维护的 Python 测试入口
```

| 动作 | 参数 | 含义 |
|---|---|---|
| `CLICK` | `{"point": [x, y]}` | 点击 |
| `LONG_PRESS` | `{"point": [x, y]}` | 长按（约 800 ms），用于上下文菜单/应用信息等 |
| `TYPE` | `{"text": "..."}` | 输入文本 |
| `SCROLL` | `{"start_point": [x, y], "end_point": [x, y]}` | 滑动 |
| `OPEN` | `{"app_name": "设置"}` | 按本机显示名启动应用 |
| `BACK` | `{}` | 系统返回 |
| `WAIT` | `{}` 或 `{"seconds": 1.5}` | 默认 1.5 秒，执行时限制在 0.5–5 秒 |
| `COMPLETE` | `{}` | 模型声明结束；不是独立验证的成功指标 |
| `ASK_USER` | `{"question":"问题", "options":["甲","乙"]}` | 安卓端暂停并等待回答 |
| `TAKE_OVER` | `{"reason":"请完成登录"}` | 安卓端等待人工操作，继续后重观察 |
| `ANSWER` | `{"answer":"查询结果", "source_step":1}` | 返回答案并结束；可关联本次保存的步骤截图 |

`COMPLETE` 也可携带 `answer` / `source_step`；`COMPLETE` 和 `ANSWER` 均支持 `status="failed"` 与 `reason` 表达失败。截图关联不等于答案经过事实核验。CLI/Web 尚无追问和接管交互入口，遇到这两类动作会以 `interaction_unavailable` 中止；答案写入结果摘要，Android 提供结果卡片展示。

坐标采用 0–1000 归一化；设备层按实际屏幕尺寸换算。Runner 将截图宽度降至最多 720 像素，保持比例，供模型和本地记录使用。

OPEN 按应用显示名查找并启动应用；无法匹配时反馈候选或通过屏幕查找。实现细节见 [技术决策](memory/technical_decisions.md)。

## 已知限制与数据处理

- **Gemini 完成状态可能误报**：Gemini Reasoner 在捕获 API 异常时仍返回 `COMPLETE`，Runner 随后会记为 completed；这是待修问题。OpenAI 和 Doubao 适配器抛出 `VLMAPIError`，由 Runner 中止并记录失败。模型输出解析失败降级为 `WAIT` 与 API 失败处理不同。
- Guard 依赖任务文本和模型摘要中的关键词，可能漏判；各入口的确认方式不同，见首表。
- 截图、任务指令及历史摘要会发送给所选云端模型；本地截图、日志、trace 也可能包含聊天内容、账号或输入文本，当前没有自动脱敏。
- Android key 使用普通 SharedPreferences 保存；备份规则和 exported 诊断入口尚待加固，见 [隐私审计](docs/privacy-audit.md)。
- Android 已接入模型追问与人工接管，详见 [交互说明](docs/android-interactions.md)；CLI/Web 调试器尚未提供对应交互入口。Android 与 PC CLI 支持本地偏好和经验检索；快速 Playbook、Web/iOS/桌面控制尚未实现，Python Protocol 提供扩展点。

## 开发与验证

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q
python -m ruff check seetouch
```

1.5 本轮核对（2026-10-20）：两套 SDK 环境的 Python 全量测试各 **209 passed**，Android JVM **37 passed**；仅补记忆闭环、开关、反馈和存储异常等关键回归，并扩展已有序列化测试。最终各验证阶段连同 APK 构建和 Lint 合计 **133.46 秒**，低于 5 分钟。APK 为 1.5 / versionCode 6，包含两个 ABI；源码哈希、Python 记忆模块打包、APK 完整性与签名通过核对。Lint 0 errors / 39 warnings。真实模型的经验质量及重复任务收益尚未进行真机测量，详见[记忆与经验说明](docs/memory-and-learning.md)。

代码基线 `ec78e8d` 随附的 2026-10-19 验证记录：在 Android 固定的 `openai==1.30.0` / `pydantic==1.10.22` / `httpx==0.27.2` 及 PC 最低 SDK `openai==1.66.0` 两套环境中，`tests/` 各 **201 passed**；`ruff check seetouch`、该代码批次的 Python 测试/入口检查和 `git diff --check` 通过。测试覆盖真实 SDK 的 mock HTTP 请求，不调用真实模型服务或操作手机。该代码批次仅新增确认、结果、通知隐私等关键回归，重复映射和简单展示不单独写测试；完整 suite 以 5 分钟内为预算，实测见 Android 指南。

Android 英文路径构建副本与工作树源码哈希一致：`testDebugUnitTest` **37 passed**，`assembleDebug` 成功。APK 为 **1.4（versionCode 5）**，包含 arm64-v8a / x86_64，约 69.6 MB；已核对 Python 模块打包及 APK 签名。`lintDebug` 通过，0 errors / 39 warnings（版本、风格、无障碍提示和国际化建议）。

用户真机验证：CLI 通过 DeepSeek 的 OpenAI 兼容 Chat Completions 接口，在小米 Android 16 手机上执行“打开小红书”，最大步数设置为 3，人工确认应用成功打开。此记录未注明具体模型 ID 和实际执行步数；Responses 尚无真实服务成功验证记录。此 CLI 历史验证不能作为独立 App 回归结果。

早期记录包含 Doubao + PC 路径的真机试跑，以及 Android 模拟器闭环；上述代码批次已构建 APK，未连接手机或调用真实模型服务。此前文档同步仅核对源码、文档和链接，未重跑模型、真机、测试 suite 或 APK 构建。历史结果见 [开发历程](memory/development_history.md)，不能作为当前 Gemini 或 Android 真机回归结论。

2026-10-19 APK 发布核验：从当前源码执行 `assembleDebug` 成功，重新检查包名、版本、最低 Android 版本、两个 ABI 及 APK v2 签名；47个打包 Python 模块与源码的编译结果一致。发布 APK 为 69,283,260 字节，SHA-256 为 `897693a177f436ad70c96ce349e9f934542ccbacc5849dc5a1e3d5ce615b23dc`。本次未重跑功能测试 suite、lint、真实模型或真机任务，以上既有测试记录与本次发布检查分开说明。

贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，近期工作见 [路线图](memory/future_roadmap.md)。问题反馈：[GitHub Issues](https://github.com/seetouch-agent/SeeTouch/issues)。

## 许可声明

项目采用 [Apache-2.0](LICENSE)，与 `pyproject.toml` 的声明一致。第三方依赖、模型与服务遵循各自的许可证及服务条款。
