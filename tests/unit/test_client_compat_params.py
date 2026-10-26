"""v1.6.49：客户端兼容性三件事。

1. Gemini 路径不再丢 developer 消息（Codex / OpenAI 新版 SDK 用它代替 system），旧版 function 角色当工具结果；
2. 常用采样 / 格式参数（top_p、stop、response_format……）转给第三方模型与兜底，过去被 pydantic 直接丢弃；
   developer 转 system；Anthropic 上游合并全部 system、带 temperature / top_p / stop_sequences；
3. 多账号文件默认放进挂载卷 data/，旧默认位置有文件时启动复制过来；容器里配置在 data/ 外时告警。
"""
import asyncio
import json
import logging

import httpx

import app.core.account_pool as ap
import app.core.api_forwarder as fwd
from app.core.responses_protocol import parse_responses_input
from app.models.openai import ChatMessage, ChatRequest
from app.utils.prompt import build_prompt_from_messages


# ---------------------------------------------------------------------------
# 1. developer / function 角色
# ---------------------------------------------------------------------------

def test_developer_messages_reach_the_gemini_prompt():
    prompt = build_prompt_from_messages([{"role": "developer", "content": "只用中文回答"},
                                         {"role": "user", "content": "hi"}])
    assert prompt == "System: 只用中文回答\n\nHuman: hi"


def test_codex_developer_items_survive_the_responses_gemini_path():
    msgs = parse_responses_input([
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "沙箱规则"}]},
        {"type": "message", "role": "user", "content": "hi"},
    ])
    assert "System: 沙箱规则" in build_prompt_from_messages(msgs)


def test_legacy_function_role_is_a_tool_result():
    prompt = build_prompt_from_messages([{"role": "user", "content": "q"},
                                         {"role": "function", "name": "f", "content": "42"}])
    assert prompt.endswith("Tool result: 42")


# ---------------------------------------------------------------------------
# 2. 第三方参数透传
# ---------------------------------------------------------------------------

class _Entry:
    id = "e"
    provider = "custom"
    model = "deepseek-chat"
    api_key = "sk"
    base_url = "https://up.example/v1"
    reasoning_effort = None


def _no_ssrf(monkeypatch):
    monkeypatch.setattr(fwd, "_build_safe_target_url", lambda entry, suffix: entry.base_url.rstrip("/") + suffix)


def _req(**kw):
    return ChatRequest(model="deepseek-chat", messages=[ChatMessage(role="user", content="hi")], **kw)


def test_chat_request_keeps_the_sampling_params():
    req = _req(top_p=0.9, stop=["END"], seed=7, presence_penalty=0.1, frequency_penalty=0.2,
               response_format={"type": "json_object"}, max_completion_tokens=99,
               stream_options={"include_usage": True}, parallel_tool_calls=False)
    assert (req.top_p, req.stop, req.seed, req.max_completion_tokens) == (0.9, ["END"], 7, 99)


def test_openai_payload_forwards_the_params(monkeypatch):
    _no_ssrf(monkeypatch)
    req = _req(stream=True, top_p=0.9, stop="END", seed=7, response_format={"type": "json_object"},
               max_completion_tokens=99, stream_options={"include_usage": True}, parallel_tool_calls=False)
    _, _, payload = fwd._build_openai_request(_Entry(), [{"role": "developer", "content": "规则"},
                                                         {"role": "user", "content": "hi"}], req)
    assert payload["top_p"] == 0.9 and payload["stop"] == "END" and payload["seed"] == 7
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_completion_tokens"] == 99 and payload["parallel_tool_calls"] is False
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["messages"][0]["role"] == "system", "developer 转 system"
    assert "presence_penalty" not in payload, "没给的参数不带"


def test_stream_options_never_go_out_on_a_non_stream_request(monkeypatch):
    """兜底探测强制非流式：OpenAI 规定 stream_options 只能和 stream=true 一起出现，带上会 400。"""
    _no_ssrf(monkeypatch)
    req = _req(stream=True, stream_options={"include_usage": True}).model_copy(update={"stream": False})
    _, _, payload = fwd._build_openai_request(_Entry(), [{"role": "user", "content": "hi"}], req)
    assert "stream_options" not in payload


def test_anthropic_merges_system_messages_and_maps_sampling(monkeypatch):
    _no_ssrf(monkeypatch)
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}],
                                         "stop_reason": "end_turn", "usage": {}})

    monkeypatch.setattr(fwd, "_make_async_client",
                        lambda timeout=300.0: httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                                timeout=timeout))

    class _AEntry(_Entry):
        provider = "anthropic"
        base_url = "https://up.example"

    req = _req(temperature=0.3, top_p=0.8, stop="END", max_completion_tokens=512)
    messages = [{"role": "system", "content": "说明一"},
                {"role": "developer", "content": [{"type": "text", "text": "说明二"}]},
                {"role": "user", "content": "hi"}]
    asyncio.run(fwd._forward_anthropic(_AEntry(), messages, req))
    body = captured["body"]
    assert body["system"] == "说明一\n\n说明二", "过去只留最后一条 system，developer 还会被当成普通消息发出去"
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert (body["temperature"], body["top_p"], body["stop_sequences"]) == (0.3, 0.8, ["END"])
    assert body["max_tokens"] == 512


def test_responses_text_format_and_top_p_reach_the_third_party():
    import app.core.responses_thirdparty as rt

    params = rt._sampling_params({
        "top_p": 0.5, "max_output_tokens": 64, "parallel_tool_calls": False,
        "text": {"format": {"type": "json_schema", "name": "r", "schema": {"type": "object"}, "strict": True}},
    })
    assert params["top_p"] == 0.5 and params["max_tokens"] == 64 and params["parallel_tool_calls"] is False
    assert params["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "r", "schema": {"type": "object"}, "strict": True}}
    assert rt._response_format({"text": {"format": {"type": "text"}}}) is None
    assert rt._response_format({"text": {"format": {"type": "json_object"}}}) == {"type": "json_object"}


# ---------------------------------------------------------------------------
# 3. 多账号文件的默认位置
# ---------------------------------------------------------------------------

def test_default_accounts_file_lives_in_the_data_volume():
    from app.config import Settings

    assert Settings.model_fields["accounts_file"].default == "data/accounts.json"


def test_legacy_accounts_file_is_copied_to_the_new_default(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ap, "_DOCKERENV", tmp_path / "no-dockerenv")
    monkeypatch.setattr(ap.settings, "accounts_file", "data/accounts.json")
    (tmp_path / "accounts.json").write_text('{"accounts": [{"id": "account-0", "psid": "p"}]}')

    with caplog.at_level(logging.WARNING):
        path = ap._prepare_accounts_file()

    assert path == tmp_path.joinpath("data/accounts.json").relative_to(tmp_path)
    assert json.loads((tmp_path / "data/accounts.json").read_text())["accounts"][0]["psid"] == "p"
    assert (tmp_path / "accounts.json").exists(), "旧文件保留"
    assert any("moved to the new default" in r.getMessage() for r in caplog.records)


def test_an_existing_new_file_is_never_overwritten(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ap, "_DOCKERENV", tmp_path / "no-dockerenv")
    monkeypatch.setattr(ap.settings, "accounts_file", "data/accounts.json")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/accounts.json").write_text("NEW")
    (tmp_path / "accounts.json").write_text("OLD")
    ap._prepare_accounts_file()
    assert (tmp_path / "data/accounts.json").read_text() == "NEW"


def test_an_explicit_path_is_respected_and_warned_about_in_a_container(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    dockerenv = tmp_path / ".dockerenv"
    dockerenv.write_text("")
    monkeypatch.setattr(ap, "_DOCKERENV", dockerenv)
    monkeypatch.setattr(ap.settings, "accounts_file", "accounts.json")
    (tmp_path / "accounts.json").write_text("{}")

    with caplog.at_level(logging.WARNING):
        path = ap._prepare_accounts_file()

    assert str(path) == "accounts.json"
    assert not (tmp_path / "data/accounts.json").exists(), "显式配置不搬"
    assert any("not under the mounted data/ volume" in r.getMessage() for r in caplog.records)


def test_no_warning_for_the_default_path_in_a_container(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    dockerenv = tmp_path / ".dockerenv"
    dockerenv.write_text("")
    monkeypatch.setattr(ap, "_DOCKERENV", dockerenv)
    monkeypatch.setattr(ap.settings, "accounts_file", "data/accounts.json")
    with caplog.at_level(logging.WARNING):
        ap._prepare_accounts_file()
    assert not any("not under the mounted" in r.getMessage() for r in caplog.records)
