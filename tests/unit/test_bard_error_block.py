"""Gemini 在 HTTP 200 正文里返回的拒绝块（BardErrorInfo）必须变成明确异常（S4）。

Gemini 拒绝请求时 HTTP 状态码仍然是 200，错误藏在正文的嵌套块里，而那种帧的第 2 格是
null —— 我们的解析器既取不到文本也不报错，整条请求被当成"空响应"：账号不标不健康、
cookie 自愈不触发、健康检查一直绿，用户一直收到空回复。

帧的真实形态（实据：refs/gemini-web-to-api
internal/modules/providers/gemini_service_test.go:125）：
    [["wrb.fr",null,null,null,null,[13,null,
      [["type.googleapis.com/assistant.boq.bard.application.BardErrorInfo",[1152]]]]],["di",2461]]
"""

import asyncio
import json

import pytest

from app.core import gemini_client as gc
from app.core.gemini_client import GeminiRejectionError, classify_error

_TYPE_URL = "type.googleapis.com/assistant.boq.bard.application.BardErrorInfo"


def _error_line(code: int, outer: int = 13) -> str:
    return json.dumps(
        [["wrb.fr", None, None, None, None, [outer, None, [[_TYPE_URL, [code]]]]], ["di", 2461]]
    )


def _text_line(text: str = "hello", conv: str = "c_1") -> str:
    payload = json.dumps([None, [conv], None, None, [[None, [text]]]])
    return json.dumps([["wrb.fr", None, payload, None, None, None, "generic"]])


def _raw(*lines: str) -> str:
    return ")]}'\n\n" + "\n".join(lines)


def _client() -> gc.GeminiWebClient:
    c = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    return c


# ---------------------------------------------------------------------------
# 非流式
# ---------------------------------------------------------------------------

def test_nonstream_rejection_raises_instead_of_returning_empty():
    err = None
    try:
        _client()._parse_output(_raw(_error_line(1152)))
    except GeminiRejectionError as e:
        err = e
    assert err is not None, "拒绝块必须抛异常，不能静默变成空响应"
    # 两个 code 都要带上（外层 13 + BardErrorInfo 的 1152），与参考实现的 "code [13 1152]" 一致
    assert err.codes == (13, 1152)
    assert "BardErrorInfo" in str(err)


def test_normal_response_is_untouched():
    out = _client()._parse_output(_raw(_text_line("hello")))
    assert out["text"] == "hello"
    assert out["conversation_id"] == "['c_1']"


def test_model_talking_about_the_error_type_is_not_a_rejection():
    """假阳性守卫：用户问"BardErrorInfo 是什么"，模型回答里就带这个 type URL。
    回答文本在帧的第 2 格，绝不能被当成拒绝块（两个参考实现用裸子串匹配，都有这个坑）。"""
    answer = f"The marker looks like {_TYPE_URL} and means ..."
    out = _client()._parse_output(_raw(_text_line(answer)))
    assert out["text"] == answer


# ---------------------------------------------------------------------------
# 分类：code→语义由配置提供，认不出走保守口径
# ---------------------------------------------------------------------------

_CODES_CONF = (
    "9001=rate_limit,9002=session_expired,9003=context_too_long,9004=captcha"
)


@pytest.mark.parametrize(
    "code,status",
    [
        (9001, 503),  # 限流：5xx → 冷却该账号 + 换号重试
        (9002, 401),  # 会话过期：标 EXPIRED + 触发 cookie 自愈
        (9003, 400),  # 上下文超长：给客户端明确错误，不重试
        (9004, 403),  # 人机验证：先把账号让出去
    ],
)
def test_configured_codes_map_to_the_right_status(monkeypatch, code, status):
    monkeypatch.setattr(gc.settings, "bard_error_codes", _CODES_CONF, raising=False)
    with pytest.raises(GeminiRejectionError) as ei:
        _client()._parse_output(_raw(_error_line(code, outer=0)))
    err = ei.value
    assert err.status_code == status
    mapped_status, mapped_type, _ = classify_error(err)
    assert mapped_status == status
    # 4xx 一律 invalid_request_error、5xx 一律 api_error（classify_error 的既有口径）
    assert mapped_type == ("api_error" if status >= 500 else "invalid_request_error")


def test_unknown_code_is_conservative(monkeypatch):
    """认不出的 code → 429：给客户端明确的"稍后再试"，但既不冷却账号也不跨账号 failover
    （一个系统性的未知拒绝若按 5xx 处理，会把整池账号一起拖进冷却）。"""
    monkeypatch.setattr(gc.settings, "bard_error_codes", _CODES_CONF, raising=False)
    with pytest.raises(GeminiRejectionError) as ei:
        _client()._parse_output(_raw(_error_line(123456, outer=0)))
    assert ei.value.category == gc.BARD_CATEGORY_UNKNOWN
    assert classify_error(ei.value) == (429, "rate_limit_error", None)


def test_broken_config_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setattr(
        gc.settings, "bard_error_codes", "abc=rate_limit,9001=nonsense,9002=captcha",
        raising=False,
    )
    assert gc._bard_error_code_map() == {9002: gc.BARD_CATEGORY_CAPTCHA}


# ---------------------------------------------------------------------------
# 流式：同一条识别路径，必须同样抛错
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, chunks, status=200):
        self.status_code = status
        self._chunks = chunks
        self.cookies = {}
        self.headers = {}

    def aiter_content(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()

    async def atext(self):
        return b"".join(self._chunks).decode()


class _FakeCM:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


def _stream_client(monkeypatch, raw: str, *, chunk_size: int = 17):
    data = raw.encode()
    chunks = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]
    resp = _FakeResp(chunks)

    class _Session:
        def __init__(self, *a, **kw):
            pass

        def stream(self, *a, **kw):
            return _FakeCM(resp)

        async def close(self):
            return None

    monkeypatch.setattr(gc, "AsyncSession", _Session)

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(gc, "apply_jitter", _noop)

    client = gc.GeminiWebClient.__new__(gc.GeminiWebClient)
    client._healthy = True
    client._session_token = "TOKEN"
    client._current_target = "chrome120"
    client._family_model = {}
    client._session_uuid = "SESSION-UUID"

    class _Jar:
        def update_from_response(self, resp):
            return None

    client._cookie_jar = _Jar()
    monkeypatch.setattr(client, "_ensure_session_current", _noop)
    monkeypatch.setattr(client, "_get_cookies", lambda: {})
    monkeypatch.setattr(client, "_get_headers", lambda *a, **kw: {})
    return client


def _drain(client):
    async def run():
        out = []
        async for evt in client.generate_stream("hi", "gemini-flash"):
            out.append(evt)
        return out

    return asyncio.run(run())


def test_stream_rejection_raises(monkeypatch):
    client = _stream_client(monkeypatch, _raw(_error_line(1152)))
    with pytest.raises(GeminiRejectionError) as ei:
        _drain(client)
    assert ei.value.codes == (13, 1152)


def test_stream_rejection_classifies_like_the_nonstream_path(monkeypatch):
    monkeypatch.setattr(gc.settings, "bard_error_codes", _CODES_CONF, raising=False)
    for code, status in ((9001, 503), (9002, 401), (9003, 400), (9004, 403)):
        client = _stream_client(monkeypatch, _raw(_error_line(code, outer=0)))
        with pytest.raises(GeminiRejectionError) as ei:
            _drain(client)
        assert ei.value.status_code == status, f"code {code}"


def test_stream_normal_answer_still_streams(monkeypatch):
    client = _stream_client(monkeypatch, _raw(_text_line("hello world")))
    events = _drain(client)
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "hello world"
    assert events[-1]["type"] == "final"
    assert events[-1]["text"] == "hello world"


def test_stream_answer_mentioning_the_error_type_still_streams(monkeypatch):
    answer = f"see {_TYPE_URL} for details"
    client = _stream_client(monkeypatch, _raw(_text_line(answer)))
    events = _drain(client)
    assert events[-1]["text"] == answer
