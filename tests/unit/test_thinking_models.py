from app.core.gemini_client import GEMINI_MODELS, _model_number

def test_flash_lite_base_id_is_free_tier():
    assert GEMINI_MODELS["gemini-3-flash-lite"]["id"] == "cf41b0e0dd7d53e5"
    # paid tiers keep the paid id
    assert GEMINI_MODELS["gemini-3-flash-lite-advanced"]["id"] == "8c46e95b1a07cecc"
    assert GEMINI_MODELS["gemini-3-flash-lite-plus"]["id"] == "8c46e95b1a07cecc"

def test_model_numbers():
    assert GEMINI_MODELS["gemini-3-pro"]["model_number"] == 3
    assert GEMINI_MODELS["gemini-3-flash"]["model_number"] == 1
    assert GEMINI_MODELS["gemini-3-flash-lite"]["model_number"] == 6
    # flash-thinking 的内部条目已删（只剩隐藏别名），别名解析到 flash，编号也随之是 flash 的
    assert "gemini-3-flash-thinking" not in GEMINI_MODELS
    assert _model_number("gemini-3-flash-thinking") == 1

def test_model_number_helper_resolves_public_names():
    # public names resolve via _FAMILY_DEFAULT
    assert _model_number("gemini-pro") == 3
    assert _model_number("gemini-flash") == 1
    assert _model_number("gemini-flash-lite") == 6
    assert _model_number("unknown-model") == 1  # safe default


import json
from app.core.gemini_client import GeminiWebClient, _build_model_header_thinking, MODEL_HEADER_KEY

def test_thinking_header_17_elements():
    h = _build_model_header_thinking("gemini-flash", "SESSION-UUID-1")
    arr = json.loads(h[MODEL_HEADER_KEY])
    assert len(arr) == 17
    assert arr[4] == "56fdd199312815e2" or arr[4] == "fbb127bbb056c959"  # flash id (family)
    assert arr[8] == [4, 5, 6, 8]
    assert arr[14] == 1            # model_number for flash
    assert arr[15] == 2            # extended-thinking flag
    assert arr[16] == "SESSION-UUID-1"

def test_thinking_payload_81_elements_and_flags():
    c = GeminiWebClient.__new__(GeminiWebClient)
    c._session_uuid = "SESSION-UUID-2"
    encoded, uuid_val = c._encode_payload_thinking("hello", "gemini-flash", "", None, None)
    outer = json.loads(encoded)
    inner = json.loads(outer[1])
    assert len(inner) == 81
    assert inner[0] == ["hello", 0, None, None, None, None, 0]
    assert inner[7] == 1           # STREAMING_FLAG_INDEX
    assert inner[79] == 1          # model_number (flash)
    assert inner[80] == 2          # extended thinking
    assert inner[59] == uuid_val   # per-request uuid echoed
    assert isinstance(uuid_val, str) and len(uuid_val) > 10

def test_normal_encoders_unchanged():
    # regression guard: the ORIGINAL encoders are byte-identical to before
    c = GeminiWebClient.__new__(GeminiWebClient)
    out = c._encode_payload("hello", "gemini-pro", "", None)
    assert out == json.dumps([None, json.dumps([["hello"], None, None, "gemini-pro"])])


def test_parse_output_extracts_thoughts():
    c = GeminiWebClient.__new__(GeminiWebClient)
    # payload[4][0] = candidate; [1][0]=answer, [37][0][0]=thoughts
    cand = [None]*38
    cand[1] = ["the answer"]
    cand[37] = [["my chain of thought"]]
    payload = [None, "conv-1", None, None, [cand]]
    raw = ")]}'\n" + json.dumps([["wrb.fr", None, json.dumps(payload)]])
    out = c._parse_output(raw)
    assert out["text"] == "the answer"
    assert out["thoughts"] == "my chain of thought"

def test_parse_output_no_thoughts_empty():
    c = GeminiWebClient.__new__(GeminiWebClient)
    cand = [None]*2
    cand[1] = ["answer only"]
    payload = [None, "c", None, None, [cand]]
    raw = ")]}'\n" + json.dumps([["wrb.fr", None, json.dumps(payload)]])
    out = c._parse_output(raw)
    assert out["thoughts"] == ""
