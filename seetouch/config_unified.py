"""统一配置管理:整合所有运行时参数到单一配置类。

设计原则:
  - 配置集中:所有可配置参数归集到 UnifiedConfig
  - 优先级:环境变量 > .env 文件 > 默认值
  - 类型安全:使用 dataclass + 类型注解
  - 向后兼容:保留旧的 AppSettings.from_env() 和各 Reasoner 配置类
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(env_file: Path | str | None = None) -> None:
    """加载 .env 文件到 os.environ。

    优先级:已存在的环境变量 > .env 文件。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    if env_file:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(override=False)


@dataclass
class UnifiedConfig:
    """统一运行时配置,整合设备、推理、安全、调试所有参数。"""

    # ==================== 设备控制 ====================
    device_serial: str | None
    """Android 设备 serial number。None 时自动选择（单设备场景）"""

    # ==================== 任务执行 ====================
    max_steps: int
    """单任务最大步数"""

    max_consecutive_failures: int
    """连续失败多少步后中止任务"""

    max_consecutive_identical_actions: int
    """连续重复相同动作多少次后判定死循环"""

    max_open_misses: int
    """OPEN 动作未匹配多少次后升级为视觉兜底"""

    action_settle_seconds: float
    """动作执行后等待界面响应的时间（秒）"""

    runs_dir: Path
    """任务记录保存目录"""

    # ==================== 推理层 ====================
    vlm_api_key: str
    """OpenAI 兼容 VLM API Key"""

    vlm_api_url: str
    """OpenAI 兼容 API 地址"""

    vlm_model_id: str
    """VLM 模型 ID"""

    reasoning_effort: str | None
    """思考强度: minimal|low|medium|high|xhigh; None 使用模型默认"""

    temperature: float | None
    """推理温度参数"""

    top_p: float | None
    """推理 top_p 参数"""

    history_window: int
    """历史摘要窗口大小（步数）"""

    # ==================== 应用索引 ====================
    applist_path: str | None
    """helper 导出的 applist.json 路径。None 时使用默认路径"""

    # ==================== 日志 ====================
    log_level: str
    """日志级别: DEBUG|INFO|WARNING|ERROR"""

    @classmethod
    def from_env(cls) -> "UnifiedConfig":
        """从环境变量加载配置,缺失值使用合理默认值。"""
        # VLM API Key 是必需的
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VLM_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "missing OPENAI_API_KEY (or VLM_API_KEY) environment variable"
            )

        return cls(
            # 设备控制
            device_serial=os.environ.get("SEETOUCH_DEVICE_SERIAL") or None,
            # 任务执行
            max_steps=int(os.environ.get("SEETOUCH_MAX_STEPS", "45")),
            max_consecutive_failures=int(os.environ.get("SEETOUCH_MAX_CONSECUTIVE_FAILURES", "2")),
            max_consecutive_identical_actions=int(
                os.environ.get("SEETOUCH_MAX_CONSECUTIVE_IDENTICAL_ACTIONS", "3")
            ),
            max_open_misses=int(os.environ.get("SEETOUCH_MAX_OPEN_MISSES", "3")),
            action_settle_seconds=float(os.environ.get("SEETOUCH_ACTION_SETTLE_SECONDS", "1.0")),
            runs_dir=Path(os.environ.get("SEETOUCH_RUNS_DIR", "runs")),
            # 推理层
            vlm_api_key=api_key,
            vlm_api_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            vlm_model_id=os.environ.get("OPENAI_MODEL_ID", "gpt-4.1-mini"),
            reasoning_effort=_parse_reasoning_effort(
                os.environ.get("OPENAI_REASONING_EFFORT")
                or os.environ.get("SEETOUCH_REASONING_EFFORT")
            ),
            temperature=_parse_float_or_none(os.environ.get("SEETOUCH_TEMPERATURE")),
            top_p=_parse_float_or_none(os.environ.get("SEETOUCH_TOP_P")),
            history_window=int(os.environ.get("SEETOUCH_HISTORY_WINDOW", "8")),
            # 应用索引
            applist_path=os.environ.get("SEETOUCH_APPLIST_PATH") or None,
            # 日志
            log_level=os.environ.get("SEETOUCH_LOG_LEVEL", "INFO"),
        )


def _parse_float_or_none(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_reasoning_effort(s: str | None) -> str | None:
    if not s or s.strip().lower() in {"none", "default"}:
        return None
    return s.strip().lower()
