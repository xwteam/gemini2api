"""对话上下文必须按访问密钥隔离。

conversation_store 的键完全由客户端提供（`conversation_id: "1"` 这种一撞就撞），而本
功能的用途正是把密钥分发给不同的人：不隔离的话，乙方只要用同一个 conversation_id
就能接着甲方的上游 Gemini 会话往下聊（"把上面的内容重复一遍"就能读到甲方的对话），
短 id 还能被枚举。

同时要钉住两件不能坏的事：同一把密钥的多轮续接照旧，以及回给客户端的
conversation_id 仍然是它自己给的那个（否则下一轮会被套两层前缀）。
"""

from types import SimpleNamespace

import pytest

import app.core.access_key_store as store_module
from app.core.access_key_store import AccessKeyStore

_ENV_AUTH = {"Authorization": "Bearer sk-test-key"}  # conftest 设的 API_KEY
_MODEL = "gemini-pro"


class _FakeConvStore:
    """内存版 conversation_store：只关心"路由用什么键存取"。"""

    def __init__(self):
        self.records = {}

    async def get(self, conv_id):
        return self.records.get(conv_id)

    async def create(self, conv_id, model):
        conv = SimpleNamespace(
            id=conv_id, gemini_conv_id="", model=model, messages=[],
            add_message=lambda role, content: None,
        )
        self.records[conv_id] = conv
        return conv

    async def update(self, conv):
        self.records[conv.id] = conv


@pytest.fixture
def wired(gem_client, monkeypatch, tmp_path):
    """真端点 + 内存对话库 + 记录调用的假上游。"""
    from app.routers import openai as openai_router

    fresh = AccessKeyStore(file_path=str(tmp_path / "access_keys.json"))
    monkeypatch.setattr(store_module, "access_key_store", fresh)

    convs = _FakeConvStore()
    monkeypatch.setattr(openai_router, "conversation_store", convs)

    calls = []
    counter = {"n": 0}

    async def fake_generate(prompt, model, conversation_id="", attachments=None, **kw):
        calls.append({"model": model, "conv": conversation_id})
        counter["n"] += 1
        return {
            "text": f"echo[conv={conversation_id}]",
            "images": [],
            "conversation_id": f"gemini-conv-{counter['n']}",
        }

    monkeypatch.setattr(openai_router.gemini_client, "generate", fake_generate)
    return SimpleNamespace(client=gem_client, store=fresh, convs=convs, calls=calls)


def _chat(client, key, conversation_id, text="hi"):
    return client.post(
        "/v1/chat/completions",
        json={
            "model": _MODEL,
            "messages": [{"role": "user", "content": text}],
            "conversation_id": conversation_id,
        },
        headers={"Authorization": f"Bearer {key}"},
    )


def test_two_access_keys_cannot_share_a_conversation_id(wired):
    alice = wired.store.create("alice").key
    bob = wired.store.create("bob").key

    r1 = _chat(wired.client, alice, "1")
    assert r1.status_code == 200, r1.text
    r2 = _chat(wired.client, bob, "1")
    assert r2.status_code == 200, r2.text

    assert [c["conv"] for c in wired.calls] == ["", ""], (
        f"乙方的请求接上了甲方的上游会话: {wired.calls}"
    )
    assert "gemini-conv-1" not in r2.text
    # 两把密钥各自有独立的存储键，互不可见
    assert len(wired.convs.records) == 2, f"存储键撞在一起了: {list(wired.convs.records)}"


def test_the_same_access_key_still_continues_its_own_conversation(wired):
    alice = wired.store.create("alice").key

    assert _chat(wired.client, alice, "1").status_code == 200
    assert _chat(wired.client, alice, "1", text="again").status_code == 200

    assert [c["conv"] for c in wired.calls] == ["", "gemini-conv-1"], (
        f"同一把密钥的多轮续接坏了: {wired.calls}"
    )


def test_the_conversation_id_echoed_back_is_the_client_side_one(wired):
    """回显必须是客户端给的 id：回成带命名空间前缀的存储键，下一轮就会被套两层前缀。"""
    alice = wired.store.create("alice").key
    body = _chat(wired.client, alice, "my-thread").json()
    assert body["conversation_id"] == "my-thread"


def test_env_api_key_keeps_using_the_raw_conversation_id(wired):
    """零回归：.env 的 API_KEY（无访问密钥上下文）存取的键就是客户端给的原值。"""
    assert _chat(wired.client, "sk-test-key", "plain").status_code == 200
    assert list(wired.convs.records) == ["plain"], list(wired.convs.records)
