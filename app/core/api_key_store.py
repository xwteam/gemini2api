"""
Thread-safe API key storage pool with JSON persistence.
"""

import json
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


PROVIDER_CATALOG = {
    "openai": {
        "display_name": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1", "o1-mini", "o1-pro"]
    },
    "anthropic": {
        "display_name": "Anthropic",
        "default_base_url": "https://api.anthropic.com",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]
    },
    "gemini": {
        "display_name": "Google Gemini",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": ["gemini-2.5-flash-preview-05-20", "gemini-2.5-pro-preview-05-06", "gemini-2.0-flash"]
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "default_base_url": "https://openrouter.ai/api/v1",
        "models": []
    },
    "custom": {
        "display_name": "自定义",
        "default_base_url": "",
        "models": []
    }
}


@dataclass
class ApiKeyEntry:
    id: str
    provider: str
    model: str
    api_key: str
    base_url: str
    label: Optional[str]
    status: str
    added_at: str
    last_used_at: Optional[str]


class ApiKeyPool:
    def __init__(self, file_path: str = "data/api-keys.json"):
        self.file_path = Path(file_path)
        self.lock = threading.Lock()
        self.entries: dict[str, ApiKeyEntry] = {}
        self._load()

    def add(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str,
        label: Optional[str] = None
    ) -> ApiKeyEntry:
        with self.lock:
            entry_id = uuid.uuid4().hex[:12]
            entry = ApiKeyEntry(
                id=entry_id,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                label=label,
                status="active",
                added_at=datetime.utcnow().isoformat(),
                last_used_at=None
            )
            self.entries[entry_id] = entry
            self._save()
            return entry

    def remove(self, id: str) -> bool:
        with self.lock:
            if id in self.entries:
                del self.entries[id]
                self._save()
                return True
            return False

    def list_all(self, mask: bool = True) -> list[dict]:
        with self.lock:
            result = []
            for entry in self.entries.values():
                entry_dict = asdict(entry)
                if mask and entry_dict["api_key"]:
                    key = entry_dict["api_key"]
                    if len(key) > 8:
                        entry_dict["api_key"] = f"{key[:4]}****{key[-4:]}"
                    else:
                        entry_dict["api_key"] = "****"
                result.append(entry_dict)
            return result

    def get(self, id: str) -> Optional[ApiKeyEntry]:
        with self.lock:
            return self.entries.get(id)

    def get_key_for_model(self, model: str) -> Optional[ApiKeyEntry]:
        with self.lock:
            for entry in self.entries.values():
                if entry.model == model and entry.status == "active":
                    return entry
            return None

    def delete(self, id: str) -> bool:
        return self.remove(id)

    def list_keys(self, masked: bool = True) -> list[dict]:
        return self.list_all(mask=masked)

    def update_status(self, id: str, status: str) -> bool:
        with self.lock:
            if id in self.entries:
                self.entries[id].status = status
                self._save()
                return True
            return False

    def update_label(self, id: str, label: str) -> bool:
        with self.lock:
            if id in self.entries:
                self.entries[id].label = label
                self._save()
                return True
            return False

    def update_last_used(self, id: str) -> bool:
        with self.lock:
            if id in self.entries:
                self.entries[id].last_used_at = datetime.utcnow().isoformat()
                self._save()
                return True
            return False

    def _save(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            entry_id: asdict(entry)
            for entry_id, entry in self.entries.items()
        }
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load(self):
        if not self.file_path.exists():
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = {
                entry_id: ApiKeyEntry(**entry_data)
                for entry_id, entry_data in data.items()
            }
        except (json.JSONDecodeError, TypeError, KeyError):
            self.entries = {}
