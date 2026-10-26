"""Stable result codes; raw provider/device errors stay out of user-facing notifications."""

from __future__ import annotations


def failure_code(reason: str | None) -> str | None:
    if not reason:
        return None
    text = reason.lower()
    if text.startswith("reasoning_failed: "):
        category = text.split(": ", 2)[1]
        if category in (
            "quota", "permission_missing", "rate_limit", "server_error",
            "network_error", "timeout", "model_error",
        ):
            return category
    groups = (
        ("quota", ("quota", "balance", "billing", "insufficient_credit", "overdue")),
        ("permission_missing", ("permission", "accessibility", "unauthorized", "401", "403")),
        ("rate_limit", ("rate_limit", "429", "too many requests")),
        ("server_error", ("server_error", "502", "503", "504")),
        ("network_error", ("connection", "network", "dns", "unavailable")),
        ("timeout", ("timeout", "timed out")),
        ("max_steps", ("max_steps",)),
        ("stuck_loop", ("stuck_loop", "dead_loop")),
        ("app_not_installed", ("app_not_installed", "app not found", "openappnotfound")),
        ("blacklisted_app", ("blacklist", "blocked_app")),
        ("model_unable", ("model_unable", "interaction_unavailable")),
        ("user_denied", ("user_denied", "confirmation_timeout")),
        ("user_stopped", ("user_stopped",)),
        ("model_error", ("reasoning_failed", "vlm api", "model_error")),
        ("device_error", ("device", "screenshot", "consecutive_failures")),
    )
    return next((code for code, terms in groups if any(term in text for term in terms)), "device_error")


def api_failure_code(error: Exception) -> str:
    current: BaseException | None = error
    for _ in range(10):
        if current is None:
            break
        status = getattr(current, "status_code", None)
        body = getattr(current, "body", None)
        detail = body.get("error", body) if isinstance(body, dict) else {}
        code = str(detail.get("code") or detail.get("type") or "").lower() if isinstance(detail, dict) else ""
        if status == 402 or any(x in code for x in ("quota", "balance", "billing", "overdue", "insufficient_credit")):
            return "quota"
        if status in (401, 403):
            return "permission_missing"
        if status == 429:
            return "rate_limit"
        if isinstance(status, int) and 500 <= status <= 599:
            return "server_error"
        if isinstance(current, TimeoutError) or "timeout" in type(current).__name__.lower():
            return "timeout"
        name = type(current).__name__.lower()
        if "connection" in name or "network" in name:
            return "network_error"
        current = current.__cause__ or current.__context__
    return "model_error"


RETRYABLE_API_ERRORS = frozenset({"rate_limit", "server_error", "network_error", "timeout"})
