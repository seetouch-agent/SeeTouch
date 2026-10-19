"""Responses transport compatible with the SDK bundled in Android."""

from __future__ import annotations

from types import SimpleNamespace


def create_response(client, **payload):
    """Use the SDK resource when available, otherwise its authenticated HTTP transport.

    Android pins openai 1.30 to avoid unsupported native dependencies. Its public
    post method still provides the same base URL, authentication, timeout and retry
    handling; only decoding the newer Responses JSON needs a small adapter.
    """
    resource = getattr(client, "responses", None)
    if callable(getattr(resource, "create", None)):
        return resource.create(**payload)

    # SDK 1.30's decoder requires key/value types for mapping responses.
    body = client.post("/responses", cast_to=dict[str, object], body=payload)
    if not isinstance(body, dict):
        raise ValueError("Responses returned an invalid JSON object")
    if body.get("status") != "completed" or body.get("error"):
        # Do not execute even valid-looking action text from a failed/partial response.
        raise ValueError(f"Responses request did not complete: {body.get('status')}")
    output = body.get("output")
    if not isinstance(output, list):
        raise ValueError("Responses returned an invalid output list")
    texts = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        if item.get("role") != "assistant":
            continue
        if item.get("status") not in (None, "completed"):
            raise ValueError("Responses returned an incomplete assistant message")
        contents = item.get("content")
        if not isinstance(contents, list):
            raise ValueError("Responses returned invalid message content")
        for content in contents:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    texts.append(text)
    usage = body.get("usage")
    return SimpleNamespace(
        status=body.get("status"),
        output_text="".join(texts),
        usage=SimpleNamespace(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ) if isinstance(usage, dict) else None,
    )
