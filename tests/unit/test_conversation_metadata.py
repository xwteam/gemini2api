"""多轮续接的会话元数据必须是 [cid, rid, rcid] 列表（v1.6.45 规格 B.1 / B.2）。

线上实证（北京 2026-10-26 14:4x，两轮请求带同一个 conversation_id）：
  - data/conversations/<id>.json 里存的是 str(payload[1]) 转出来的 Python repr
    "['c_…', 'r_…']"；
  - 第二轮把这个字符串原样塞进 payload 第 2 格，思考路径（默认档上线后几乎所有请求）干脆
    不带续接参数（DEFAULT_METADATA）；
  - 两轮谷歌返回的 c_ 不一样 —— 每一轮其实都开了新会话、只发了最后一句。

本文件钉住：
  - 解析：JSON 列表 / 旧的 Python repr / 纯 "c_…" 三种都能读，坏值一律视为没有可续接的会话；
  - 抽取：非流式 _parse_output 与真流式（逐帧 + final 事件）都从真实形态的响应里取出
    [cid, rid, rcid]，rcid 是被采用的候选（payload[4][0]）的第 0 格；
  - 编码：两个 payload 编码器的第 2 格放列表（缺的位置 None），绝不再放字符串。
"""

import asyncio
import json
import logging
import urllib.parse

import pytest

from app.core import gemini_client as gc
from app.core.gemini_client import (
    GeminiWebClient,
    encode_conversation_metadata,
    parse_conversation_metadata,
)

CID, RID, RCID = "c_9a1b2c3d4e5f6789", "r_0011223344556677", "rc_8899aabbccddeeff"
TRIPLE = [CID, RID, RCID]
STORED = json.dumps(TRIPLE)


def _payload(text="hello", *, head=None, rcid=RCID, thoughts=None):
    """真实形态的响应 payload：[null, ["c_…","r_…"], null, null, [[rcid, [text], …]]]。"""
    cand = [rcid, [text]]
    if thoughts is not None:
        cand += [None] * (37 - len(cand)) + [[[thoughts]]]
    return [None, [CID, RID] if head is None else head, None, None, [cand]]


def _frame(payload) -> list:
    return ["wrb.fr", None, json.dumps(payload), None, None, None, "generic"]


def _raw(*payloads) -> str:
    return ")]}'\n\n" + "\n".join(json.dumps([_frame(p)]) for p in payloads)


# ---------------------------------------------------------------------------
# 解析（读取统一走 parse_conversation_metadata）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (STORED, TRIPLE),                                         # v1.6.45 起的存储格式
    (json.dumps([CID, RID]), [CID, RID, None]),
    (json.dumps([CID, None, None]), [CID, None, None]),
    (f"['{CID}', '{RID}']", [CID, RID, None]),                # v1.6.44 及以前的 Python repr
    (f"['{CID}']", [CID, None, None]),
    (CID, [CID, None, None]),                                 # 纯 "c_…" 字符串
    (f"  {CID}  ", [CID, None, None]),
    (TRIPLE, TRIPLE),                                         # 已经是列表
    ((CID, RID, RCID), TRIPLE),
    (json.dumps([CID, 5, "garbage"]), [CID, None, None]),     # rid / rcid 不合格的位置填 None
])
def test_parse_reads_all_supported_formats(raw, expected):
    assert parse_conversation_metadata(raw) == expected


@pytest.mark.parametrize("raw", [None, "", [], ()])
def test_parse_empty_means_no_conversation_without_logging(raw, caplog):
    with caplog.at_level(logging.INFO, logger="app.core.gemini_client"):
        assert parse_conversation_metadata(raw) is None
    assert not caplog.records


@pytest.mark.parametrize("raw", [
    "gemini-conv-1", "conv1", "c1", "c_", "c_ has spaces", "r_only",
    "[1, 2]", "{}", '"c_abc"', json.dumps([RID]), json.dumps([None, RID]),
    "['c_abc'", "[" * 600 + "]" * 600, "['c_" + "x" * 2000 + "']",
    123, {"cid": CID}, [None, RID],
])
def test_parse_bad_values_mean_no_resumable_conversation_and_are_logged(raw, caplog):
    with caplog.at_level(logging.INFO, logger="app.core.gemini_client"):
        assert parse_conversation_metadata(raw) is None
    assert any("conversation metadata" in r.getMessage() for r in caplog.records), \
        "坏值要记一行日志，不能悄悄当成新会话"


def test_encode_is_json_and_round_trips():
    assert encode_conversation_metadata(TRIPLE) == STORED
    assert parse_conversation_metadata(encode_conversation_metadata(TRIPLE)) == TRIPLE
    assert encode_conversation_metadata([CID, None, None]) == json.dumps([CID, None, None])
    assert encode_conversation_metadata(None) == ""
    assert encode_conversation_metadata(["bad"]) == ""


# ---------------------------------------------------------------------------
# 抽取：非流式
# ---------------------------------------------------------------------------

def _client() -> GeminiWebClient:
    return GeminiWebClient.__new__(GeminiWebClient)


def test_parse_output_extracts_the_triple_as_json():
    out = _client()._parse_output(_raw(_payload("answer")))
    assert out["text"] == "answer"
    assert out["conversation_id"] == STORED


def test_parse_output_takes_the_last_frame():
    first = _payload("ans", head=["c_aaaaaaaaaaaaaaaa", "r_aaaaaaaaaaaaaaaa"], rcid="rc_aaaaaaaaaaaaaaaa")
    out = _client()._parse_output(_raw(first, _payload("answer")))
    assert json.loads(out["conversation_id"]) == TRIPLE


def test_parse_output_accepts_a_bare_cid_head_and_a_missing_rcid():
    out = _client()._parse_output(_raw(_payload("answer", head=CID, rcid=None)))
    assert json.loads(out["conversation_id"]) == [CID, None, None]


def test_parse_output_without_a_cid_has_no_conversation():
    out = _client()._parse_output(_raw(_payload("answer", head=[None, RID])))
    assert out["conversation_id"] == ""


# ---------------------------------------------------------------------------
# 抽取：真流式
# ---------------------------------------------------------------------------

def test_stream_frame_extraction_matches_the_nonstream_format():
    text, conv, _ = gc._extract_text_from_wrb(_frame(_payload("partial")))
    assert text == "partial"
    assert conv == STORED
    assert conv == _client()._parse_output(_raw(_payload("partial")))["conversation_id"]


class _StreamHarness:
    """喂原始响应流给真的 generate_stream，并记下发出去的表单。"""

    def __init__(self, monkeypatch, raw: str, *, chunk_size: int = 29):
        data = raw.encode()
        chunks = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]
        self.sent: list[dict] = []
        sent = self.sent

        class _Resp:
            status_code = 200
            cookies: dict = {}
            headers: dict = {}

            def aiter_content(self):
                async def gen():
                    for c in chunks:
                        yield c

                return gen()

        class _CM:
            async def __aenter__(self):
                return _Resp()

            async def __aexit__(self, *a):
                return False

        class _Session:
            def __init__(self, *a, **kw):
                pass

            def stream(self, method, url, data=None, **kw):
                sent.append(dict(data or {}))
                return _CM()

            async def close(self):
                return None

        async def _noop(*a, **kw):
            return None

        monkeypatch.setattr(gc, "AsyncSession", _Session)
        monkeypatch.setattr(gc, "apply_jitter", _noop)

        client = GeminiWebClient.__new__(GeminiWebClient)
        client._healthy = True
        client._session_token = "TOKEN"
        client._current_target = "chrome120"
        client._family_model = {}
        client._session_uuid = "SESSION-UUID"
        client._push_id = ""

        class _Jar:
            def update_from_response(self, resp):
                return None

        client._cookie_jar = _Jar()
        monkeypatch.setattr(client, "_ensure_session_current", _noop)
        monkeypatch.setattr(client, "_get_cookies", lambda: {})
        monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})
        self.client = client

    def run(self, conversation_id="", extended_thinking=False):
        async def go():
            return [e async for e in self.client.generate_stream(
                "hi", "gemini-flash", conversation_id, extended_thinking=extended_thinking)]

        return asyncio.run(go())

    def sent_inner(self) -> list:
        outer = json.loads(self.sent[-1]["f.req"])
        return json.loads(outer[1])


def test_stream_final_event_carries_the_triple(monkeypatch):
    raw = _raw(_payload("hel"), _payload("hello"), _payload("hello world"))
    events = _StreamHarness(monkeypatch, raw).run()
    final = [e for e in events if e["type"] == "final"][-1]
    assert final["text"] == "hello world"
    assert final["conversation_id"] == STORED


@pytest.mark.parametrize("thinking", [False, 1], ids=["normal-path", "thinking-path"])
def test_stream_request_puts_the_list_in_slot_2(monkeypatch, thinking):
    harness = _StreamHarness(monkeypatch, _raw(_payload("ok")))
    harness.run(conversation_id=STORED, extended_thinking=thinking)
    assert harness.sent_inner()[2] == TRIPLE


# ---------------------------------------------------------------------------
# 编码：payload 第 2 格
# ---------------------------------------------------------------------------

def _inner(encoded: str) -> list:
    return json.loads(json.loads(encoded)[1])


@pytest.mark.parametrize("stored,expected", [
    (STORED, TRIPLE),
    (f"['{CID}', '{RID}']", [CID, RID, None]),
    (CID, [CID, None, None]),
])
def test_normal_payload_slot_2_is_a_list(stored, expected):
    inner = _inner(_client()._encode_payload("hi", "gemini-pro", stored, None))
    assert inner[2] == expected


@pytest.mark.parametrize("stored", ["", "conv1", "['broken'"])
def test_normal_payload_without_a_valid_conversation_starts_fresh(stored):
    inner = _inner(_client()._encode_payload("hi", "gemini-pro", stored, None))
    assert inner[2] is None
    # 新会话的 payload 与改动前逐字节一致
    assert _client()._encode_payload("hi", "gemini-pro", stored, None) == \
        json.dumps([None, json.dumps([["hi"], None, None, "gemini-pro"])])


def test_normal_payload_never_puts_a_string_in_slot_2():
    for stored in (STORED, f"['{CID}', '{RID}']", CID, "conv1", "garbage", ""):
        inner = _inner(_client()._encode_payload("hi", "gemini-pro", stored, [("fid", "f.png")],
                                                  gem_id="g1"))
        assert not isinstance(inner[2], str), (stored, inner[2])


def _thinking_client() -> GeminiWebClient:
    c = _client()
    c._session_uuid = "SESSION-UUID"
    return c


def test_thinking_payload_resumes_with_the_list_in_slot_2():
    encoded, _ = _thinking_client()._encode_payload_thinking("hi", "gemini-flash", STORED, None, None, 1)
    assert _inner(encoded)[2] == TRIPLE


@pytest.mark.parametrize("stored", ["", "conv1"])
def test_thinking_payload_new_conversation_keeps_the_default_metadata(stored):
    encoded, _ = _thinking_client()._encode_payload_thinking("hi", "gemini-flash", stored, None, None, 1)
    assert _inner(encoded)[2] == ["", "", "", None, None, None, None, None, None, ""]


def test_nonstream_request_puts_the_list_in_slot_2(monkeypatch):
    """_send_request 发出去的表单（非流式）第 2 格同样是列表。"""
    client = GeminiWebClient.__new__(GeminiWebClient)
    client._healthy = True
    client._session_token = "TOKEN"
    client._family_model = {}
    client._session_uuid = "SESSION-UUID"
    client._push_id = ""
    sent = []

    class _Resp:
        status_code = 200
        text = _raw(_payload("ok"))
        cookies: dict = {}
        headers: dict = {}

    class _Http:
        async def post(self, url, data=None, **kw):
            sent.append(dict(data or {}))
            return _Resp()

    class _Jar:
        def update_from_response(self, resp):
            return None

    async def _noop(*a, **kw):
        return None

    client._http = _Http()
    client._cookie_jar = _Jar()
    monkeypatch.setattr(gc, "apply_jitter", _noop)
    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_clear_session_cookies", lambda: None)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})

    for thinking in (False, 1):
        out = asyncio.run(client._send_request("hi", "gemini-flash", STORED, None, None, thinking))
        inner = json.loads(json.loads(sent[-1]["f.req"])[1])
        assert inner[2] == TRIPLE, thinking
        assert out["conversation_id"] == STORED


def test_form_encoding_survives_urlencoding():
    """防呆：f.req 经表单编码后再解回来，第 2 格仍是列表（不是被二次 JSON 编码的字符串）。"""
    encoded = _client()._encode_payload("hi", "gemini-pro", STORED, None)
    round_trip = urllib.parse.parse_qs(urllib.parse.urlencode({"f.req": encoded}))["f.req"][0]
    assert _inner(round_trip)[2] == TRIPLE
