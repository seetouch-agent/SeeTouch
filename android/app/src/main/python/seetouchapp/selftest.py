"""Phase 0 自检:验证 Chaquopy 嵌入的 seetouch 包在设备上完整可用。

分两级:
1. 离线检查 —— seetouch 各层模块可导入、PIL 图像编码链路可用
2. 在线检查(需 api_key)—— OpenAICompatibleReasoner 对假截图做一次真实推理,
   覆盖 openai SDK / HTTPS / 输出解析全链路
"""

from __future__ import annotations

import json
import platform
import sys
import traceback


def run(
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model_id: str = "gpt-4.1-mini",
) -> str:
    """执行自检,返回 JSON 报告字符串。"""
    report: dict = {
        "python": sys.version,
        "platform": platform.platform(),
        "checks": {},
    }
    checks = report["checks"]

    def check(name, fn):
        try:
            checks[name] = {"ok": True, "detail": fn()}
        except Exception:
            checks[name] = {"ok": False, "detail": traceback.format_exc()}

    check("import_core", _check_import_core)
    check("bridge_packages", _check_bridge_packages)
    check("image_pipeline", _check_image_pipeline)
    check("parser", _check_parser)
    if api_key:
        check(
            "openai_compatible_inference",
            lambda: _check_openai_compatible_inference(api_key, base_url, model_id),
        )
    else:
        checks["openai_compatible_inference"] = {
            "ok": None,
            "detail": "skipped (no api_key)",
        }

    report["all_ok"] = all(c["ok"] for c in checks.values() if c["ok"] is not None)
    return json.dumps(report, ensure_ascii=False)


def _check_import_core() -> str:
    from seetouch.core.runner import Runner  # noqa: F401
    from seetouch.core.action import ActionOutput  # noqa: F401
    from seetouch.reasoning.openai_compatible import (  # noqa: F401
        OpenAICompatibleConfig,
        OpenAICompatibleReasoner,
    )
    from seetouch.perception.screen import encode_image_data_url  # noqa: F401
    from seetouch.safety.guard import Guard  # noqa: F401

    return "core/reasoning/perception/safety importable"


def _check_bridge_packages() -> str:
    from com.seetouch.app.bridge import DeviceBridge  # type: ignore[import-not-found]

    pkgs = [str(p) for p in DeviceBridge.installedPackages()]
    return f"count={len(pkgs)} has_settings={'com.android.settings' in pkgs} sample={pkgs[:5]}"


def _check_image_pipeline() -> str:
    from PIL import Image

    from seetouch.perception.screen import encode_image_data_url

    img = Image.new("RGB", (1080, 2400), (32, 32, 32))
    data_url = encode_image_data_url(img)
    assert data_url.startswith("data:image/"), data_url[:40]
    return f"encoded fake 1080x2400 screenshot, data_url len={len(data_url)}"


def _check_parser() -> str:
    from seetouch.reasoning.parser import parse_model_output

    raw = '{"action":"CLICK","parameters":{"point":[500,300]}}'
    action = parse_model_output(raw, (1080, 2400))
    return f"parsed sample output -> {action.type}"


def _check_openai_compatible_inference(
    api_key: str,
    base_url: str,
    model_id: str,
) -> str:
    from PIL import Image

    from seetouch.reasoning.openai_compatible import (
        OpenAICompatibleConfig,
        OpenAICompatibleReasoner,
    )

    reasoner = OpenAICompatibleReasoner(
        OpenAICompatibleConfig(
            api_key=api_key,
            base_url=base_url,
            model_id=model_id,
        )
    )
    screenshot = Image.new("RGB", (1080, 2400), (32, 32, 32))
    output = reasoner.predict("这是一张纯色测试图,请直接输出 COMPLETE 动作", screenshot, [])
    if output.raw_output.startswith("Error:"):
        raise RuntimeError(output.raw_output)
    usage = output.usage or {}
    return (
        f"action={output.action.type} "
        f"tokens={usage.get('input_tokens')}/{usage.get('output_tokens')}"
    )
