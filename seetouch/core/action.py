"""标准动作定义,与比赛动作协议对齐。

所有坐标都是 0-1000 的归一化坐标,设备控制层负责到像素的换算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ActionType = Literal["CLICK", "LONG_PRESS", "TYPE", "SCROLL", "OPEN", "BACK", "WAIT", "COMPLETE", "ASK_USER", "TAKE_OVER", "ANSWER"]


ACTION_CLICK: ActionType = "CLICK"
ACTION_LONG_PRESS: ActionType = "LONG_PRESS"
ACTION_TYPE: ActionType = "TYPE"
ACTION_SCROLL: ActionType = "SCROLL"
ACTION_OPEN: ActionType = "OPEN"
ACTION_BACK: ActionType = "BACK"
ACTION_WAIT: ActionType = "WAIT"
ACTION_COMPLETE: ActionType = "COMPLETE"
ACTION_ASK_USER: ActionType = "ASK_USER"
ACTION_TAKE_OVER: ActionType = "TAKE_OVER"
ACTION_ANSWER: ActionType = "ANSWER"

VALID_ACTIONS: frozenset[str] = frozenset(
    {ACTION_CLICK, ACTION_LONG_PRESS, ACTION_TYPE, ACTION_SCROLL, ACTION_OPEN, ACTION_BACK,
     ACTION_WAIT, ACTION_COMPLETE, ACTION_ASK_USER, ACTION_TAKE_OVER, ACTION_ANSWER}
)


@dataclass
class Action:
    """一个标准动作。

    parameters 形状(归一化坐标 0-1000):
        CLICK:    {"point": [x, y]}
        LONG_PRESS: {"point": [x, y]}     # 长按,用于唤出上下文菜单/应用信息等
        TYPE:     {"text": "..."}
        SCROLL:   {"start_point": [x, y], "end_point": [x, y]}
        OPEN:     {"app_name": "..."}    # 中文名 或 Android package
        BACK:     {}                       # 系统返回键:回上一层 / 关弹窗
        WAIT:     {} 或 {"seconds": float}  # 等待界面加载 / 动画 / 弹窗消失
        COMPLETE: {}
    """

    type: ActionType
    parameters: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.type not in VALID_ACTIONS:
            raise ValueError(f"Invalid action type: {self.type!r}")

        if self.type in (ACTION_CLICK, ACTION_LONG_PRESS):
            point = self.parameters.get("point")
            if not (isinstance(point, (list, tuple)) and len(point) == 2):
                raise ValueError(
                    f"{self.type} requires parameters.point [x,y], got {point!r}"
                )
        elif self.type == ACTION_TYPE:
            if not isinstance(self.parameters.get("text"), str):
                raise ValueError("TYPE requires parameters.text (str)")
        elif self.type == ACTION_SCROLL:
            for key in ("start_point", "end_point"):
                pt = self.parameters.get(key)
                if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
                    raise ValueError(f"SCROLL requires parameters.{key} [x,y]")
        elif self.type == ACTION_OPEN:
            if not isinstance(self.parameters.get("app_name"), str):
                raise ValueError("OPEN requires parameters.app_name (str)")
        elif self.type == ACTION_WAIT:
            seconds = self.parameters.get("seconds")
            if seconds is not None and not isinstance(seconds, (int, float)):
                raise ValueError("WAIT.seconds must be number if present")
        elif self.type == ACTION_ASK_USER:
            question = self.parameters.get("question")
            options = self.parameters.get("options", [])
            if not isinstance(question, str) or not question.strip():
                raise ValueError("ASK_USER requires a nonempty question")
            if not isinstance(options, list) or not all(isinstance(x, str) and x.strip() for x in options):
                raise ValueError("ASK_USER.options must be a list of nonempty strings")
        elif self.type == ACTION_TAKE_OVER:
            reason = self.parameters.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("TAKE_OVER requires a nonempty reason")
        elif self.type in (ACTION_COMPLETE, ACTION_ANSWER):
            answer = self.parameters.get("answer", self.parameters.get("text"))
            if self.type == ACTION_ANSWER and (not isinstance(answer, str) or not answer.strip()):
                raise ValueError("ANSWER requires nonempty answer text")
            if answer is not None and not isinstance(answer, str):
                raise ValueError("answer must be text")
            source = self.parameters.get("source_step")
            if source is not None and (type(source) is not int or source < 1):
                raise ValueError("source_step must be a positive step number")
            if self.parameters.get("status", "completed") not in ("completed", "failed"):
                raise ValueError("terminal status must be completed or failed")
            if "reason" in self.parameters and not isinstance(self.parameters["reason"], str):
                raise ValueError("terminal reason must be text")
        # COMPLETE: no params required


@dataclass
class ActionOutput:
    """Reasoner 一次预测的完整输出。

    Attributes:
        action:         解析后的标准动作
        raw_output:     模型原始文本,用于调试和回放
        screen_summary: 模型对当前截图的描述
        action_summary: 模型对本步动作的解释
        usage:          token 使用统计(可选)
        prompt_text:    发给模型的 prompt 文本(不含图片),用于调试
        reasoning_content: 模型思维链文本(thinking 开启时有值),用于调试
    """

    action: Action
    raw_output: str = ""
    screen_summary: str = ""
    action_summary: str = ""
    usage: dict[str, Any] | None = None
    prompt_text: str = ""
    reasoning_content: str = ""
    parse_error: bool = False
