"""Android UI bridge to the same memory store used by Runner; no device/model calls."""

import json
import os

from seetouch.memory import MemoryStore


def command(operation: str, payload: str = "{}") -> str:
    from com.seetouch.app.bridge import DeviceBridge

    try:
        store = MemoryStore(os.path.join(str(DeviceBridge.filesDir()), "agent_memory.json"))
        data = json.loads(payload)
        if operation == "configure":
            store.configure(enabled=data["enabled"], learning_enabled=data["learning_enabled"])
        elif operation == "save":
            store.remember(name=data["name"], content=data["content"], category=data["category"],
                           keywords=data.get("keywords", []), entry_id=data.get("id"),
                           source="manual")
        elif operation == "confirm_suggestion":
            if data["category"] == "procedure":
                raise ValueError("该建议不是偏好记忆")
            store.remember(name=data["name"], content=data["content"], category=data["category"],
                           keywords=data.get("keywords", []), source="suggested", task_id=data.get("task_id", ""))
        elif operation == "enabled":
            store.set_entry_enabled(data["id"], data["enabled"])
        elif operation == "remove":
            store.remove(data["id"])
        elif operation == "clear":
            store.remove()
        elif operation == "review":
            store.review_task(data["task_id"], data["positive"], data.get("used_ids", []))
        elif operation != "list":
            raise ValueError("不支持的记忆操作")
        return json.dumps({"ok": True, **store.snapshot()}, ensure_ascii=False)
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        # Never echo the submitted content or corrupt local data into UI/logcat.
        return json.dumps({"ok": False, "error": "记忆操作失败，请检查内容是否有效、包含凭据，或存储是否可用"}, ensure_ascii=False)
