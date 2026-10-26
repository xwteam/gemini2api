"""
对话上下文持久化 - 混合模式

优先使用 Gemini 原生 conversation_id 维持多轮对话，
同时本地备份对话历史，会话过期时自动 fallback 到拼接模式。
"""
import os
import re
import json
import time
import hashlib
import asyncio
from collections import OrderedDict
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "data")) / "conversations"
MAX_CONVERSATIONS = 200
MAX_AGE_SECONDS = 3600 * 6

# 仅允许“安全字符集”作为磁盘文件名的对话 id（字母/数字/下划线/连字符/点），
# 且不含 ".." 段。客户端可控的 conversation_id 会被直接当作文件名使用，
# 不做约束会造成路径穿越（写/删 DATA_DIR 之外的 *.json）。其它字符的 id
# 退化为 sha256 摘要，既消除穿越风险又保持稳定映射。
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_file_id(conv_id: str) -> str:
    """把客户端可控的 conversation_id 映射为安全的磁盘文件名（防路径穿越）。"""
    if (
        isinstance(conv_id, str)
        and conv_id
        and ".." not in conv_id
        and "/" not in conv_id
        and "\\" not in conv_id
        and _SAFE_ID_RE.match(conv_id)
    ):
        return conv_id
    # 不安全/异常 id：用 sha256 摘要作为文件名
    return "h_" + hashlib.sha256(str(conv_id).encode("utf-8")).hexdigest()


class Conversation:
    def __init__(self, conv_id: str, gemini_conv_id: str = "", account_id: str = ""):
        self.id = conv_id
        # 续接上游会话的元数据：[cid, rid, rcid] 的 JSON 字符串（v1.6.45 起）。旧文件里可能是
        # Python repr "['c_…', 'r_…']" 或纯 "c_…"，读取统一走 gemini_client.parse_conversation_metadata。
        self.gemini_conv_id = gemini_conv_id
        # 服务这个会话的账号 id。会话 id 是账号私有的：续接必须钉回同一个账号，钉不住就改发完整历史。
        # 旧文件没有这个字段 → ""（= 不知道是哪个账号，下一轮发完整历史、新开会话）。
        self.account_id = account_id
        self.messages: list[dict] = []
        self.model: str = ""
        self.created_at: float = time.time()
        self.updated_at: float = time.time()

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content, "ts": time.time()})
        self.updated_at = time.time()

    def to_dict(self):
        return {
            "id": self.id,
            "gemini_conv_id": self.gemini_conv_id,
            "account_id": self.account_id,
            "model": self.model,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict):
        account_id = data.get("account_id")
        conv = cls(data["id"], data.get("gemini_conv_id", ""),
                   account_id if isinstance(account_id, str) else "")
        conv.messages = data.get("messages", [])
        conv.model = data.get("model", "")
        conv.created_at = data.get("created_at", time.time())
        conv.updated_at = data.get("updated_at", time.time())
        return conv


class ConversationStore:
    def __init__(self):
        self._conversations: OrderedDict[str, Conversation] = OrderedDict()
        self._lock = asyncio.Lock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def _load_from_disk(self):
        index_file = DATA_DIR / "index.json"
        if not index_file.exists():
            return
        try:
            with open(index_file, "r") as f:
                index = json.load(f)
            for entry in index[-MAX_CONVERSATIONS:]:
                conv_file = DATA_DIR / f"{_safe_file_id(entry['id'])}.json"
                if conv_file.exists():
                    with open(conv_file, "r") as f:
                        data = json.load(f)
                    conv = Conversation.from_dict(data)
                    if time.time() - conv.updated_at < MAX_AGE_SECONDS:
                        self._conversations[conv.id] = conv
        except Exception:
            pass

    def _save_conversation(self, conv: Conversation):
        # 防路径穿越：用 conv.id 派生的安全文件名而非原始 id
        conv_file = DATA_DIR / f"{_safe_file_id(conv.id)}.json"
        with open(conv_file, "w") as f:
            json.dump(conv.to_dict(), f, ensure_ascii=False)
        self._save_index()

    def _save_index(self):
        index = [{"id": c.id, "updated_at": c.updated_at} for c in self._conversations.values()]
        with open(DATA_DIR / "index.json", "w") as f:
            json.dump(index, f)

    def _evict_old(self):
        now = time.time()
        expired = [k for k, v in self._conversations.items() if now - v.updated_at > MAX_AGE_SECONDS]
        for k in expired:
            del self._conversations[k]
            (DATA_DIR / f"{_safe_file_id(k)}.json").unlink(missing_ok=True)
        while len(self._conversations) > MAX_CONVERSATIONS:
            oldest_key = next(iter(self._conversations))
            del self._conversations[oldest_key]
            (DATA_DIR / f"{_safe_file_id(oldest_key)}.json").unlink(missing_ok=True)

    async def get(self, conv_id: str) -> Conversation | None:
        async with self._lock:
            return self._conversations.get(conv_id)

    async def create(self, conv_id: str, model: str) -> Conversation:
        async with self._lock:
            self._evict_old()
            conv = Conversation(conv_id)
            conv.model = model
            self._conversations[conv_id] = conv
            return conv

    async def update(self, conv: Conversation):
        async with self._lock:
            self._conversations[conv.id] = conv
            self._conversations.move_to_end(conv.id)
            self._save_conversation(conv)

    async def delete(self, conv_id: str):
        async with self._lock:
            if conv_id in self._conversations:
                del self._conversations[conv_id]
                (DATA_DIR / f"{_safe_file_id(conv_id)}.json").unlink(missing_ok=True)
                self._save_index()

    async def list_all(self) -> list[dict]:
        async with self._lock:
            return [
                {"id": c.id, "model": c.model, "messages": len(c.messages),
                 "created_at": c.created_at, "updated_at": c.updated_at}
                for c in self._conversations.values()
            ]


conversation_store = ConversationStore()
