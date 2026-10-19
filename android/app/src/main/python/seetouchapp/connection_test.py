"""ACC-05: exercise the selected vision API without capturing or operating a device."""

from __future__ import annotations

import json
import time

from PIL import Image, ImageDraw

from seetouch.core.exceptions import ParseError
from seetouch.reasoning.parser import parse_model_output
from .task_entry import _create_reasoner

TEST_QUESTION = (
    "这是连接测试，图片为内置示例，不是真实手机截图。"
    "请描述图中按钮文字，并输出一个合法的 COMPLETE JSON 动作。不要执行任何操作。"
)


def _classify(exc: Exception, request_started: bool = False) -> tuple[str, str]:
    chain = []
    current = exc
    while current is not None and len(chain) < 10:
        chain.append(current)
        current = current.__cause__ or current.__context__
    if any(isinstance(e, ParseError) for e in chain) or (request_started and any(
        isinstance(e, (ValueError, AttributeError, IndexError, TypeError)) or
        type(e).__name__ == "APIResponseValidationError" for e in chain
    )):
        return "unparsable", "已收到响应，但无法解析为 SeeTouch 动作；请检查模型是否支持图片和结构化输出"
    for error in chain:
        status = getattr(error, "status_code", None)
        body = getattr(error, "body", None)
        code = str(getattr(error, "code", "") or "").lower()
        if isinstance(body, dict):
            detail = body.get("error", body)
            if isinstance(detail, dict):
                code += " " + str(detail.get("code", "")) + " " + str(detail.get("type", ""))
        code = code.lower()
        if status in (401, 403):
            return "authentication", "鉴权或权限失败：请检查 API Key 和模型访问权限"
        if status == 404 or "model_not_found" in code:
            return "model_not_found", "模型或接口不存在：请检查模型 ID、基础地址和接口协议"
        if status == 402 or any(x in code for x in (
            "quota", "balance", "billing", "credit", "spend", "arrear", "overdue",
        )):
            return "quota", "额度不足或计费受限：请检查服务商余额与配额"
        if status == 429:
            return "rate_limit", "请求被限流：请稍后重试或降低请求频率"
        if status is not None and status >= 500:
            return "server", "服务暂时异常：请稍后重试"
        if isinstance(error, (ConnectionError, TimeoutError)) or any(
            x in type(error).__name__.lower() for x in ("connection", "timeout", "connecterror")
        ):
            return "network", "网络连接失败或超时：请检查网络、基础地址和超时设置"
    if isinstance(exc, (ValueError, KeyError)):
        return "configuration", "连接配置无效，请检查服务、地址、模型与超时设置"
    return "request", "连接测试失败：请检查所选协议、模型的图片输入能力及服务商状态"


def test_connection(config_json: str) -> str:
    started = time.perf_counter()
    reasoner = None
    request_started = False
    try:
        config = json.loads(config_json)
        reasoner = _create_reasoner(config)
        image = Image.new("RGB", (360, 640), "#f1f4f8")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((70, 270, 290, 340), radius=12, fill="#237c69")
        draw.text((155, 298), "TEST", fill="white")
        request_started = True
        output = reasoner.predict(TEST_QUESTION, image, [])
        # Reasoners can fall back to WAIT on malformed text; a probe must expose that failure.
        parse_model_output(output.raw_output, image.size).validate()
        result = {"success": True, "category": "ok", "message": "连接成功，图片请求已收到可解析响应"}
    except Exception as exc:
        category, message = _classify(exc, request_started)
        result = {"success": False, "category": category, "message": message}
    finally:
        client = getattr(reasoner, "_client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    return json.dumps(result, ensure_ascii=False)
