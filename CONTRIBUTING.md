# 贡献指南

欢迎为 SeeTouch 提交问题、文档或代码改进。当前主仓库为 [seetouch-agent/SeeTouch](https://github.com/seetouch-agent/SeeTouch)。

## 报告问题

在 [Issues](https://github.com/seetouch-agent/SeeTouch/issues) 中说明版本或 commit、使用入口（CLI / 调试器 / Android App）、模型配置、复现步骤、预期和实际结果。设备信息提供型号和 Android 版本即可，不必公开设备序列号、完整应用列表或个人目录。

分享日志前移除 API key、邮箱、账号、聊天内容和敏感截图。不要上传 `.env`、签名密钥、完整 `runs/` 或未经检查的应用索引。`completed=true` 只是当前程序状态，须结合截图和实际任务结果判断。

## 开发流程

1. Fork 仓库，然后克隆自己的 fork：

   ```bash
   git clone https://github.com/YOUR_USERNAME/SeeTouch.git seetouch
   cd seetouch
   git remote add upstream https://github.com/seetouch-agent/SeeTouch.git
   git switch -c docs/update-guide
   ```

2. 建立虚拟环境，按 [README](README.md) 激活，然后安装：

   ```bash
   python -m pip install -e ".[dev,debugger]"
   ```

3. 修改后运行相关检查：

   ```bash
   python -m pytest tests -q
   python -m ruff check seetouch
   git diff --check
   ```

   `tests/` 是当前维护的测试入口，`seetouch/tests/` 中仍有旧测试，不能混为同一套验证。需要查格式时可运行 `python -m ruff format --check seetouch`；不要为小修改批量格式化无关代码。

4. 审阅 diff 后提交，推送到自己的分支并创建 PR。提交信息保持简洁，例如 `docs: 更新 Android 构建说明`。

当前代码基线 `ec78e8d` 随附 2026-10-19 验证记录：两套 SDK 环境各 201 项 Python 测试、37 项 Android JVM 测试、APK 构建及 lint 通过。详见 [README 验证范围](README.md#开发与验证) 与 [Android 指南](android/README.md)。这些是已记录的验证，不表示每次文档修改均重跑全部检查；新增代码应有针对性验证。10月12日扩展 lint 的4项问题属于旧快照，复用前重新检查。

## 接口与分层

- `device/` 负责设备交互，遵循 `DeviceController` Protocol；PC 和 Android 原生实现分别位于 `android/` 与 `android_native/`。
- `reasoning/` 负责模型调用，遵循 `Reasoner.predict(instruction, screenshot, history) -> ActionOutput`。
- `perception/screen.py` 负责图像和坐标；坐标范围为 0–1000。
- `core/` 负责执行、记录和事件；`safety/` 负责关键词确认机制。
- Android 修改应保持 `DeviceBridge` 边界，构建通过 Sync 任务复用仓库根的 Python 包。

新增推理器的最小接口示例（仅展示结构，未实现模型调用）：

```python
from PIL import Image
from seetouch.core.action import ActionOutput
from seetouch.reasoning.base import StepRecord

class CustomReasoner:
    def predict(
        self, instruction: str, screenshot: Image.Image, history: list[StepRecord]
    ) -> ActionOutput:
        raise NotImplementedError("接入模型并返回 ActionOutput")
```

解析器入口为 `parse_model_output(text, image_size)`，返回 `Action`；失败抛出 `ParseError`。降级到 WAIT 由 Reasoner 完成，不是 parser 自己返回完成或等待动作。

## 验证与 PR 描述

先说明问题和改动后的行为，再列出实际执行的验证。涉及真机时写清入口、设备型号、任务、步数和人工观察结果。日志摘要文件是 `runs/<task_id>/summary.json`，不是 `report.json`。

不要在普通单元测试里调用真实 API 或操作已连接手机。Gemini API 错误误记完成、调试器自动批准、Android 凭据存储等现有缺口见 [路线图](memory/future_roadmap.md)。

## 文档、隐私与许可证

- 用户流程改动同步 README 和对应指南；架构决策同步 `memory/technical_decisions.md`；历史记录注明当时版本与验证范围。
- 公开文档使用相对路径或 `<repo>` 等占位符，保留作者署名但避免个人邮箱和电脑路径。
- Git 提交邮箱可在 GitHub Settings → Emails 中选择平台提供的 noreply 地址；修改本地配置只影响新提交，旧提交原始元数据不会自动变化。
- 项目采用 [Apache-2.0](LICENSE)，与 pyproject.toml 的许可证声明一致。新增第三方代码、模型或素材时保留来源和相应许可证。
