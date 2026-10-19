"""Bounded, atomic local storage. Memory is reference data, never executable actions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path


_LOCK = threading.RLock()
_CATEGORIES = {"address", "contact", "platform", "preference", "procedure"}
_SECRETS = re.compile(
    r"sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+|\b\d{12,19}\b|"
    r"(?:密码|验证码|口令|支付信息|银行卡|api[_ -]?key|access[_ -]?token)\s*(?:[:：=]|是|为)?\s*[A-Za-z0-9_-]{4,}",
    re.I,
)
_BYPASS = re.compile(r"(?:无需|不必|绕过|禁用|直接跳过).{0,12}(?:确认|接管|安全|权限)|ignore.{0,20}(?:instructions|rules)", re.I)


def validate_text(name: str, content: str) -> None:
    if not name.strip() or len(name) > 80 or not content.strip() or len(content) > 1800:
        raise ValueError("名称须为 1–80 字，内容须为 1–1800 字")
    if re.search(r"密码|验证码|口令|支付信息|银行卡|api.?key|access.?token", name, re.I) or _SECRETS.search(content):
        raise ValueError("不能保存密码、验证码、密钥或支付凭据")
    if _BYPASS.search(name + " " + content):
        raise ValueError("记忆不能要求绕过任务确认或安全规则")


def _terms(text: str) -> set[str]:
    text = re.sub(r"打开|任务|点击|使用|帮我|完成|请|然后|搜索|输入", " ", text.lower())
    result = set(re.findall(r"[a-z0-9_]{2,}", text))
    for word in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(word[i:i + 2] for i in range(len(word) - 1))
    return result


class MemoryStore:
    """One app-private file; all mutations read the latest revision under a shared lock."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "enabled": True, "learning_enabled": True, "entries": []}
        if self.path.stat().st_size > 4_000_000:
            raise ValueError("记忆文件过大，请检查存储")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("entries"), list):
            raise ValueError("记忆文件格式无效；原文件已保留")
        if len(data["entries"]) > 500 or not isinstance(data.get("enabled"), bool) or not isinstance(data.get("learning_enabled"), bool):
            raise ValueError("记忆文件格式无效；原文件已保留")
        for entry in data["entries"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not re.fullmatch(r"[a-f0-9]{32}", entry["id"]):
                raise ValueError("记忆条目无效；原文件已保留")
            if not isinstance(entry.get("name"), str) or not isinstance(entry.get("content"), str):
                raise ValueError("记忆条目无效；原文件已保留")
            validate_text(entry["name"], entry["content"])
            if (entry.get("category") not in _CATEGORIES or entry.get("kind") not in {"preference", "experience"}
                    or not isinstance(entry.get("enabled"), bool) or not isinstance(entry.get("keywords"), list)
                    or not all(isinstance(w, str) and len(w) <= 40 for w in entry["keywords"])
                    or not isinstance(entry.get("source_tasks"), list) or not isinstance(entry.get("reviews"), dict)
                    or not all(isinstance(v, bool) for v in entry["reviews"].values())):
                raise ValueError("记忆条目无效；原文件已保留")
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pending = self.path.with_suffix(".tmp")
        with pending.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, self.path)

    def snapshot(self) -> dict:
        with _LOCK:
            return self._read()

    def configure(self, *, enabled: bool, learning_enabled: bool) -> dict:
        with _LOCK:
            data = self._read()
            data.update(enabled=bool(enabled), learning_enabled=bool(learning_enabled))
            self._write(data)
            return data

    def remember(self, *, name: str, content: str, category: str = "preference", keywords: list | None = None,
                 entry_id: str | None = None, source: str = "manual", task_id: str = "") -> dict:
        name, content = name.strip(), content.strip()
        validate_text(name, content)
        if category not in _CATEGORIES:
            raise ValueError("不支持的记忆类别")
        if keywords is not None and not isinstance(keywords, list):
            raise ValueError("关联词须为列表")
        words = [str(x).strip() for x in (keywords or []) if isinstance(x, str) and x.strip()][:12]
        if any(len(x) > 40 or _SECRETS.search(x) for x in words):
            raise ValueError("关联词过长或包含敏感凭据")
        kind = "experience" if category == "procedure" else "preference"
        fingerprint = hashlib.sha256(f"{category}|{name}|{content}".encode()).hexdigest()
        with _LOCK:
            data = self._read()
            if source != "manual" and not data["enabled"]:
                raise ValueError("记忆已关闭")
            if source == "learned" and not data["learning_enabled"]:
                raise ValueError("经验积累已关闭")
            existing = next((e for e in data["entries"] if e["id"] == entry_id), None) if entry_id else next(
                (e for e in data["entries"] if e.get("fingerprint") == fingerprint), None)
            if entry_id and existing is None:
                raise ValueError("该条目已删除，请刷新")
            if existing is None:
                if len(data["entries"]) >= 500:
                    raise ValueError("已达 500 条上限，请整理记忆后重试")
                existing = {"id": uuid.uuid4().hex, "created_at": time.time(), "enabled": True,
                            "source_tasks": [], "reviews": {}}
                data["entries"].append(existing)
            existing.update(name=name, content=content, category=category, kind=kind, keywords=words,
                            fingerprint=fingerprint, updated_at=time.time())
            if "source" not in existing or source == "manual":
                existing["source"] = source
            if task_id and task_id not in existing["source_tasks"]:
                existing["source_tasks"] = (existing["source_tasks"] + [task_id])[-30:]
            self._write(data)
            return existing

    def set_entry_enabled(self, entry_id: str, enabled: bool) -> None:
        with _LOCK:
            data = self._read()
            entry = next(e for e in data["entries"] if e["id"] == entry_id)
            entry["enabled"] = bool(enabled)
            if enabled:
                entry["reviews"] = {k: v for k, v in entry.get("reviews", {}).items() if v is True}
            self._write(data)

    def remove(self, entry_id: str | None = None) -> None:
        with _LOCK:
            try:
                data = self._read()
            except (ValueError, KeyError, TypeError):
                if entry_id is not None:
                    raise
                # Only an explicit clear may replace malformed storage; normal reads never do.
                data = {"version": 1, "enabled": False, "learning_enabled": False, "entries": []}
            data["entries"] = [e for e in data["entries"] if entry_id is not None and e["id"] != entry_id]
            self._write(data)

    def retrieve(self, instruction: str, limit: int = 4) -> list[dict]:
        with _LOCK:
            data = self._read()
            if not data["enabled"]:
                return []
            query = _terms(instruction)
            matches = []
            for entry in data["entries"]:
                if not entry["enabled"] or any(v is False for v in entry.get("reviews", {}).values()):
                    continue
                words = " ".join([entry["name"], *entry["keywords"]])
                overlap = len(query & _terms(words))
                alias = entry["kind"] == "preference" and entry["name"] in instruction
                if overlap or alias:
                    score = overlap + 3 * alias + min(2, sum(v is True for v in entry.get("reviews", {}).values()))
                    matches.append((score, entry["updated_at"], entry))
            selected = [e for _, _, e in sorted(matches, key=lambda x: (x[0], x[1]), reverse=True)[:limit]]
            for entry in selected:
                entry["last_used_at"] = time.time()
            if selected:
                self._write(data)
            return selected

    def context(self, identifiers: list[str]) -> str:
        with _LOCK:
            data = self._read()
            if not data["enabled"]:
                return ""
            entries = [{"id": e["id"], "kind": e["kind"], "name": e["name"], "content": e["content"]}
                       for e in data["entries"] if e["id"] in identifiers and e["enabled"]
                       and not any(v is False for v in e.get("reviews", {}).values())][:4]
            while entries and len(json.dumps(entries, ensure_ascii=False)) > 6000:
                for entry in entries:
                    entry["content"] = entry["content"][:max(100, len(entry["content"]) // 2)]
            return json.dumps(entries, ensure_ascii=False) if entries else ""

    def review_task(self, task_id: str, positive: bool, used_ids: list[str]) -> None:
        with _LOCK:
            data = self._read()
            for entry in data["entries"]:
                if entry["kind"] == "experience" and (task_id in entry["source_tasks"] or entry["id"] in used_ids):
                    entry.setdefault("reviews", {})[task_id] = bool(positive)
                    entry["reviews"] = dict(list(entry["reviews"].items())[-100:])
            self._write(data)
