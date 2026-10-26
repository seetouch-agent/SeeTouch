"""模型输出解析:把模型的 JSON / 半结构化文本转成标准 Action。

参考比赛 src/agent.py 的解析能力,但解耦后作为纯函数。
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Tuple

from ..core.action import (
    ACTION_CLICK,
    ACTION_LONG_PRESS,
    ACTION_COMPLETE,
    ACTION_OPEN,
    ACTION_BACK,
    ACTION_SCROLL,
    ACTION_TYPE,
    ACTION_WAIT,
    ACTION_ASK_USER,
    ACTION_TAKE_OVER,
    ACTION_ANSWER,
    VALID_ACTIONS,
    Action,
)
from ..core.exceptions import ParseError


# 模型偶尔会把长按写成这些变体;宽容解析统一归一到标准动作名。
_ACTION_ALIASES = {
    "LONGPRESS": ACTION_LONG_PRESS,
    "LONG_CLICK": ACTION_LONG_PRESS,
    "LONGCLICK": ACTION_LONG_PRESS,
}


def parse_model_output(raw_text: str, image_size: Tuple[int, int]) -> Action:
    """主入口:解析模型输出文本,返回标准 Action。

    image_size 是 PIL Image 的 (width, height),用于把像素坐标转归一化。
    """
    text = (raw_text or "").strip()
    candidates: list[str] = [text]

    fenced = _extract_first_code_block(text)
    if fenced:
        candidates.insert(0, fenced.strip())

    json_fragment = _extract_first_json_object(text)
    if json_fragment:
        candidates.append(json_fragment)

    for cand in candidates:
        parsed = _try_parse_json(cand)
        if parsed is not None:
            action = _normalize_parsed_action(parsed, image_size)
            if action is not None:
                return action
            if isinstance(parsed, dict) and str(parsed.get("action", "")).upper() in VALID_ACTIONS:
                raise ParseError(text, "invalid parameters for structured action")

    simple = _parse_simple_action(text, image_size)
    if simple is not None:
        return simple

    raise ParseError(text, "cannot parse as a supported action")


# ---------------------------- JSON 路径 ----------------------------


def _normalize_parsed_action(
    parsed: Any,
    image_size: Tuple[int, int],
) -> Action | None:
    if not isinstance(parsed, dict):
        return None

    raw_action = parsed.get("action") or parsed.get("Action")
    if not raw_action:
        return None

    action_type = str(raw_action).strip().upper()
    action_type = _ACTION_ALIASES.get(action_type, action_type)
    if action_type not in VALID_ACTIONS:
        return None

    params = parsed.get("parameters")
    if params is None:
        params = parsed.get("params")
    if params is None:
        params = parsed
    if not isinstance(params, dict):
        params = {"value": params}

    if action_type in (ACTION_CLICK, ACTION_LONG_PRESS):
        point = (
            params.get("point")
            or params.get("coordinate")
            or params.get("coordinates")
            or params.get("coord")
            or params.get("position")
            or params.get("value")
        )
        if point is None and ("x" in params or "y" in params):
            point = _point_from_xy(params.get("x"), params.get("y"))
        norm = _normalize_point(point, image_size)
        return Action(type=action_type, parameters={"point": norm}) if norm else None

    if action_type == ACTION_TYPE:
        text = params.get("text")
        if text is None:
            text = params.get("content")
        if text is None:
            text = params.get("value", "")
        return Action(type=ACTION_TYPE, parameters={"text": str(text)})

    if action_type == ACTION_OPEN:
        name = params.get("app_name") or params.get("app") or params.get("value", "")
        return Action(type=ACTION_OPEN, parameters={"app_name": str(name)})

    if action_type == ACTION_SCROLL:
        start = params.get("start_point") or params.get("start") or params.get("from")
        end = params.get("end_point") or params.get("end") or params.get("to")
        points = params.get("points") or params.get("value")
        if (start is None or end is None) and isinstance(points, list) and len(points) >= 2:
            start, end = points[0], points[1]
        start_norm = _normalize_point(start, image_size)
        end_norm = _normalize_point(end, image_size)
        if start_norm and end_norm:
            return Action(
                type=ACTION_SCROLL,
                parameters={"start_point": start_norm, "end_point": end_norm},
            )
        return None

    if action_type in (ACTION_COMPLETE, ACTION_ANSWER):
        final_params = {k: params[k] for k in ("answer", "source_step", "status", "reason", "experience", "memory_suggestions") if k in params}
        if action_type == ACTION_ANSWER and "answer" not in final_params and "text" in params:
            final_params["answer"] = params["text"]
        action = Action(type=action_type, parameters=final_params)
        try:
            action.validate()
        except ValueError:
            return None
        return action

    if action_type in (ACTION_ASK_USER, ACTION_TAKE_OVER):
        action = Action(type=action_type, parameters={
            "question": params.get("question"), "options": params.get("options", []),
        } if action_type == ACTION_ASK_USER else {"reason": params.get("reason")})
        try:
            action.validate()
        except ValueError:
            return None
        return action

    if action_type == ACTION_BACK:
        return Action(type=ACTION_BACK, parameters={})

    if action_type == ACTION_WAIT:
        seconds = params.get("seconds") or params.get("duration")
        if isinstance(seconds, (int, float)) and seconds > 0:
            return Action(type=ACTION_WAIT, parameters={"seconds": float(seconds)})
        return Action(type=ACTION_WAIT, parameters={})

    return None


# ---------------------------- 简单文本路径 ----------------------------


def _parse_simple_action(text: str, image_size: Tuple[int, int]) -> Action | None:
    match = re.search(
        r"\b(LONG_PRESS|LONG_CLICK|LONGPRESS|CLICK|TYPE|OPEN|SCROLL|BACK|WAIT|COMPLETE)\b\s*[:：]\s*(.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None

    action_type = match.group(1).upper()
    action_type = _ACTION_ALIASES.get(action_type, action_type)
    payload_text = match.group(2).strip()
    payload = _try_parse_json(payload_text)
    if payload is None:
        payload = payload_text

    if action_type in (ACTION_CLICK, ACTION_LONG_PRESS):
        point = payload[0] if isinstance(payload, list) and payload else payload
        if isinstance(point, list) and point and isinstance(point[0], list):
            point = point[0]
        norm = _normalize_point(point, image_size)
        return Action(type=action_type, parameters={"point": norm}) if norm else None

    if action_type == ACTION_TYPE:
        text_value = payload[0] if isinstance(payload, list) and payload else payload
        return Action(type=ACTION_TYPE, parameters={"text": str(text_value)})

    if action_type == ACTION_OPEN:
        name = payload[0] if isinstance(payload, list) and payload else payload
        return Action(type=ACTION_OPEN, parameters={"app_name": str(name)})

    if action_type == ACTION_SCROLL:
        if isinstance(payload, list) and len(payload) >= 2:
            start = _normalize_point(payload[0], image_size)
            end = _normalize_point(payload[1], image_size)
            if start and end:
                return Action(
                    type=ACTION_SCROLL,
                    parameters={"start_point": start, "end_point": end},
                )
        return None

    if action_type == ACTION_COMPLETE:
        return Action(type=ACTION_COMPLETE, parameters={})

    if action_type == ACTION_BACK:
        return Action(type=ACTION_BACK, parameters={})

    if action_type == ACTION_WAIT:
        return Action(type=ACTION_WAIT, parameters={})

    return None


def _point_from_xy(x_value: Any, y_value: Any) -> list[float] | None:
    if x_value is None or y_value is None:
        return None
    x = _midpoint_if_range(x_value)
    y = _midpoint_if_range(y_value)
    if x is None or y is None:
        return None
    return [x, y]


def _midpoint_if_range(value: Any) -> float | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return (float(value[0]) + float(value[1])) / 2
        except Exception:
            return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_point(
    value: Any,
    image_size: Tuple[int, int],
) -> list[int] | None:
    if isinstance(value, dict):
        if "point" in value:
            value = value["point"]
        elif "x" in value and "y" in value:
            value = _point_from_xy(value.get("x"), value.get("y"))

    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (list, tuple)):
        value = value[0]

    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None

    try:
        x = float(value[0])
        y = float(value[1])
    except Exception:
        return None

    width, height = image_size
    # 像素坐标兜底:任何一轴超 1000 就按像素换算
    if (x > 1000 or y > 1000) and width > 0 and height > 0:
        x = x / width * 1000
        y = y / height * 1000

    return [_clip_coord(x), _clip_coord(y)]


def _clip_coord(value: float) -> int:
    return int(max(0, min(1000, round(value))))


# ---------------------------- 文本提取 helpers ----------------------------


def _extract_first_code_block(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else None


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    quote = ""
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_string = False
            continue
        if ch in ('"', "'"):
            in_string = True
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_parse_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return None
