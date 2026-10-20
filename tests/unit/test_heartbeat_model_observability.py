"""心跳里被丢弃的模型条目必须留日志（S5），以及健康检查不再依赖那条死正则（S6）。

S5：_parse_models_from_status 认不出 model id 就静默 continue —— 账号心跳明明已经返回了
    某个新模型的 id，只因为不在写死的 GEMINI_MODELS 表里就被丢掉，日志里一个字都没有。
    "某个新模型用不了"的排查因此只能靠读源码。本轮只加日志、不改模型表。
S6：check_account 用 `gemini-\\d+\\.\\d+...` 正则从 HTML 抓模型名，而当代名字是
    gemini-3-pro 这种"数字-单词"形态，这条正则恒为空，兜不住任何东西。
"""

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone

import pytest

from app.core import gemini_client as gc
from app.core.gemini_client import GEMINI_MODELS, PUBLIC_MODELS

_KNOWN_NAME = "gemini-3-flash"
_KNOWN_ID = GEMINI_MODELS[_KNOWN_NAME]["id"]


def _entry(model_id: str, display: str, number, field4) -> list:
    e = [None] * 20
    e[0] = model_id
    e[4] = field4
    e[11] = display
    e[17] = number
    return e


def _status_raw(*entries: list) -> str:
    body = [None] * 16
    body[15] = list(entries)
    return "[[" + json.dumps(["wrb.fr", "otAQ7b", json.dumps(body)])[1:-1] + "]]"


def _client() -> gc.GeminiWebClient:
    c = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    c._family_model = {}
    c._available_models = []
    return c


# ---------------------------------------------------------------------------
# S5
# ---------------------------------------------------------------------------

def test_unknown_model_entry_is_logged_with_its_fields(caplog):
    caplog.set_level(logging.WARNING, logger=gc.logger.name)
    client = _client()
    raw = _status_raw(
        _entry("ffffffffffffffff", "Gemini 3.5 Argon", 7, 4),
        _entry(_KNOWN_ID, "Gemini 3 Flash", 1, 1),
    )

    client._parse_models_from_status(raw)

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    hits = [m for m in warnings if "ffffffffffffffff" in m]
    assert len(hits) == 1, f"被丢弃的条目必须恰好留一条 WARNING，实际: {warnings}"
    msg = hits[0]
    assert "Gemini 3.5 Argon" in msg, "要带上显示名（字段 11），否则日志里认不出是哪个模型"
    assert "model_number=7" in msg, "要带上编号（字段 17）"
    assert "field4=4" in msg, "要带上字段 4"


def test_known_entries_still_resolve(caplog):
    """零回归：认得的条目照常解析，不因为加日志而改变映射结果。"""
    caplog.set_level(logging.WARNING, logger=gc.logger.name)
    client = _client()

    client._parse_models_from_status(_status_raw(_entry(_KNOWN_ID, "Gemini 3 Flash", 1, 1)))

    assert client._family_model["flash"] == _KNOWN_NAME
    assert client._available_models == list(PUBLIC_MODELS)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_unknown_entry_does_not_block_the_known_one(caplog):
    caplog.set_level(logging.WARNING, logger=gc.logger.name)
    client = _client()

    client._parse_models_from_status(_status_raw(
        _entry("ffffffffffffffff", "Gemini 3.5 Argon", 7, 4),
        _entry(_KNOWN_ID, "Gemini 3 Flash", 1, 1),
    ))

    assert client._family_model["flash"] == _KNOWN_NAME


def test_entry_field_is_crash_proof():
    """日志取字段绝不能自己抛（心跳结构随 Google 变，缺格/短数组都要容得下）。"""
    assert gc._entry_field([1, 2, 3], 11) is None
    assert gc._entry_field("not-a-list", 11) is None
    assert gc._entry_field([], 0) is None
    assert gc._entry_field([None] * 20, 11) is None


# ---------------------------------------------------------------------------
# S6
# ---------------------------------------------------------------------------

def test_dead_html_model_regex_is_gone():
    assert not hasattr(gc, "MODEL_VALID_PATTERN")
    assert not hasattr(gc, "_filter_valid_models")


class _Resp:
    def __init__(self, body: str, status: int = 200):
        self.status_code = status
        self.text = body
        self.cookies = {}
        self.headers = {}


def _check_account_client(monkeypatch, body: str, *, models_after_heartbeat):
    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    client._available_models = []
    client._healthy = False
    client._session_token = ""
    client._push_id = ""
    client._check_history = deque(maxlen=20)
    client._last_check_result = None

    class _Http:
        async def get(self, *a, **kw):
            return _Resp(body)

    client._http = _Http()

    class _Jar:
        def update_from_response(self, resp):
            return None

    client._cookie_jar = _Jar()

    async def _noop(*a, **kw):
        return None

    async def _heartbeat():
        client._available_models = list(models_after_heartbeat)
        return True

    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_clear_session_cookies", lambda: None)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})
    monkeypatch.setattr(client, "_send_heartbeat", _heartbeat)
    return client


_MODERN_BODY = (
    '<html>' + "x" * 2000 + '"SNlM0e":"TOKEN-VALUE"'
    # 当代模型名是"数字-单词"形态，老正则（要求 数字.数字）一个都抓不到
    ' {"model":"gemini-3-pro"} {"model":"gemini-3-flash"} ' + '</html>'
)


def test_check_account_counts_models_from_the_rpc(monkeypatch):
    """真实账号形态（页面里只有 gemini-3-* 这种名字）：models_count 必须是 RPC 的结果。"""
    client = _check_account_client(monkeypatch, _MODERN_BODY,
                                  models_after_heartbeat=PUBLIC_MODELS)
    result = asyncio.run(client.check_account())

    assert result["valid"] is True
    assert result["has_token"] is True
    assert result["models_count"] == len(PUBLIC_MODELS)
    datetime.fromisoformat(result["checked_at"]).astimezone(timezone.utc)


def test_check_account_without_token_is_invalid(monkeypatch):
    client = _check_account_client(monkeypatch, "<html>" + "x" * 2000 + "</html>",
                                  models_after_heartbeat=PUBLIC_MODELS)
    result = asyncio.run(client.check_account())

    assert result["valid"] is False
    assert result["models_count"] == 0


def test_check_account_does_not_invent_models_from_html(monkeypatch):
    """页面里即便出现 gemini-2.5-pro 这种老式名字，也不能算进 models_count
    （RPC 没给模型 = 账号确实选不到模型，这个 0 是真相，不该被 HTML 抓来的脏数据掩盖）。"""
    body = ('<html>' + "x" * 2000 + '"SNlM0e":"TOKEN-VALUE"'
            ' gemini-2.5-pro-preview-05-06 gemini-1.5-flash-002 </html>')
    client = _check_account_client(monkeypatch, body, models_after_heartbeat=[])
    result = asyncio.run(client.check_account())

    assert result["valid"] is True
    assert result["models_count"] == 0
