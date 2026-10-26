from app.core.responses_protocol import parse_responses_input


def test_string_input_becomes_single_user_message():
    msgs = parse_responses_input("hello there")
    assert msgs == [{"role": "user", "content": "hello there"}]


def test_instructions_becomes_leading_system_message():
    msgs = parse_responses_input("hi", instructions="Be concise.")
    assert msgs[0] == {"role": "system", "content": "Be concise."}
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_array_input_message_item_with_input_text_parts():
    msgs = parse_responses_input([
        {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "describe this"},
        ]},
    ])
    assert msgs == [{"role": "user", "content": [{"type": "text", "text": "describe this"}]}]


def test_array_input_message_with_image_part_converted_to_openai_shape():
    msgs = parse_responses_input([
        {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "what is this"},
            {"type": "input_image", "image_url": "https://x.example/a.png"},
        ]},
    ])
    content = msgs[0]["content"]
    assert content[0] == {"type": "text", "text": "what is this"}
    assert content[1] == {"type": "image_url", "image_url": {"url": "https://x.example/a.png"}}


def test_bare_object_input_treated_as_single_item_list():
    msgs = parse_responses_input({"type": "message", "role": "user", "content": "hi"})
    assert msgs == [{"role": "user", "content": "hi"}]


def test_function_call_history_item_becomes_assistant_message():
    msgs = parse_responses_input([
        {"type": "function_call", "call_id": "call_abc", "name": "run_shell",
         "arguments": '{"cmd": "ls"}'},
    ])
    assert msgs == [{"role": "assistant",
                     "content": '(called tool run_shell with arguments {"cmd": "ls"})'}]


def test_function_call_output_item_becomes_tool_message():
    msgs = parse_responses_input([
        {"type": "function_call_output", "call_id": "call_abc", "output": "file1.txt\nfile2.txt"},
    ])
    assert msgs == [{"role": "tool", "content": "file1.txt\nfile2.txt"}]


def test_output_text_content_part_maps_to_text():
    msgs = parse_responses_input([
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "previous reply"},
        ]},
    ])
    assert msgs == [{"role": "assistant", "content": [{"type": "text", "text": "previous reply"}]}]


from app.core.responses_protocol import build_responses_object, new_response_id


def test_new_response_id_has_resp_prefix():
    rid = new_response_id()
    assert rid.startswith("resp_") and len(rid) > len("resp_")


def test_build_responses_object_basic_shape():
    output = [{"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "hi", "annotations": []}]}]
    obj = build_responses_object(
        model="gemini-pro", status="completed", output=output,
        request_params={"tools": [], "tool_choice": "auto", "store": True},
        usage={"input_tokens": 3, "output_tokens": 2},
    )
    assert obj["object"] == "response"
    assert obj["id"].startswith("resp_")
    assert obj["status"] == "completed"
    assert obj["model"] == "gemini-pro"
    assert obj["output"] == output
    assert obj["tools"] == []
    assert obj["tool_choice"] == "auto"
    assert obj["store"] is True
    assert obj["usage"]["input_tokens"] == 3
    assert obj["usage"]["input_tokens_details"] == {"cached_tokens": 0}
    assert obj["usage"]["output_tokens_details"] == {"reasoning_tokens": 0}
    assert obj["usage"]["total_tokens"] == 5
    assert obj["error"] is None
    assert "created_at" in obj


def test_build_responses_object_omits_unset_request_params():
    obj = build_responses_object(model="gemini-pro", status="completed", output=[],
                                 request_params={}, usage={"input_tokens": 0, "output_tokens": 0})
    assert "tools" not in obj
    assert "tool_choice" not in obj


import json
from app.core.responses_protocol import ResponsesStreamEncoder


def _parse_frame(frame: str) -> tuple[str, dict]:
    lines = frame.strip("\n").split("\n")
    event_line = next(l for l in lines if l.startswith("event:"))
    data_line = next(l for l in lines if l.startswith("data:"))
    return event_line[len("event:"):].strip(), json.loads(data_line[len("data:"):].strip())


def test_sequence_number_increments_across_calls():
    enc = ResponsesStreamEncoder("resp_1", "gemini-pro", {})
    _, d1 = _parse_frame(enc.created())
    _, d2 = _parse_frame(enc.in_progress())
    assert d1["sequence_number"] == 0
    assert d2["sequence_number"] == 1


def test_text_message_flow_emits_done_events_in_order():
    enc = ResponsesStreamEncoder("resp_1", "gemini-pro", {})
    frames = []
    frames += enc.text_message_start("msg_1", 0)
    frames.append(enc.text_delta("msg_1", 0, "Hel"))
    frames.append(enc.text_delta("msg_1", 0, "lo"))
    frames += enc.text_message_end("msg_1", 0, "Hello")
    events = [_parse_frame(f)[0] for f in frames]
    assert events == [
        "response.output_item.added", "response.content_part.added",
        "response.output_text.delta", "response.output_text.delta",
        "response.output_text.done", "response.content_part.done", "response.output_item.done",
    ]
    done_evt = _parse_frame(frames[-3])[1]
    assert done_evt["type"] == "response.output_text.done"
    assert done_evt["text"] == "Hello"
    assert done_evt["item_id"] == "msg_1"


def test_function_call_flow_emits_arguments_done_event():
    enc = ResponsesStreamEncoder("resp_1", "gemini-pro", {})
    frames = enc.function_call("fc_1", 0, "call_abc", "run_shell", '{"cmd":"ls"}')
    events = [_parse_frame(f)[0] for f in frames]
    assert events == [
        "response.output_item.added", "response.function_call_arguments.delta",
        "response.function_call_arguments.done", "response.output_item.done",
    ]
    done_evt = _parse_frame(frames[2])[1]
    assert done_evt["type"] == "response.function_call_arguments.done"
    assert done_evt["arguments"] == '{"cmd":"ls"}'
    assert done_evt["item_id"] == "fc_1"


def test_no_done_sentinel_anywhere():
    enc = ResponsesStreamEncoder("resp_1", "gemini-pro", {})
    frame = enc.completed(output=[], usage={"input_tokens": 1, "output_tokens": 1})
    assert "[DONE]" not in frame
    assert not hasattr(enc, "done_sentinel")


def test_no_done_sentinel_in_any_encoder_output():
    enc = ResponsesStreamEncoder("resp_1", "gemini-pro", {})
    frames = []
    frames.append(enc.created())
    frames.append(enc.in_progress())
    frames += enc.text_message_start("msg_1", 0)
    frames.append(enc.text_delta("msg_1", 0, "hi"))
    frames += enc.text_message_end("msg_1", 0, "hi")
    frames += enc.function_call("fc_1", 1, "call_1", "tool", "{}")
    frames.append(enc.completed(output=[], usage={"input_tokens": 0, "output_tokens": 0}))
    frames.append(enc.failed("boom"))
    for frame in frames:
        assert "[DONE]" not in frame


def test_send_type_field_cannot_be_overridden_by_payload():
    enc = ResponsesStreamEncoder("resp_1", "gemini-pro", {})
    frame = enc._send("response.created", {"type": "some.other.type", "response": {}})
    _, data = _parse_frame(frame)
    assert data["type"] == "response.created"


# ---------------------------------------------------------------------------
# 第三方路径（native_tool_calls=True）：OpenAI chat 原生的 tool_calls / tool_call_id
# ---------------------------------------------------------------------------

def test_native_tool_loop_uses_tool_calls_and_tool_call_id():
    msgs = parse_responses_input([
        {"type": "message", "role": "user", "content": "列一下目录"},
        {"type": "function_call", "call_id": "call_abc", "name": "run_shell",
         "arguments": '{"cmd": "ls"}'},
        {"type": "function_call_output", "call_id": "call_abc", "output": "a.txt"},
    ], native_tool_calls=True)
    assert msgs == [
        {"role": "user", "content": "列一下目录"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_abc", "type": "function",
             "function": {"name": "run_shell", "arguments": '{"cmd": "ls"}'}}]},
        {"role": "tool", "tool_call_id": "call_abc", "content": "a.txt"},
    ]


def test_native_parallel_calls_share_one_assistant_message():
    msgs = parse_responses_input([
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "function_call", "call_id": "c1", "name": "a", "arguments": "{}"},
        {"type": "function_call", "call_id": "c2", "name": "b", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "x"},
        {"type": "function_call_output", "call_id": "c2", "output": "y"},
    ], native_tool_calls=True)
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "tool"]
    assert [c["id"] for c in msgs[1]["tool_calls"]] == ["c1", "c2"]
    assert [m["tool_call_id"] for m in msgs[2:]] == ["c1", "c2"]


def test_native_call_right_after_assistant_text_joins_that_message():
    msgs = parse_responses_input([
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "我先看一下目录"}]},
        {"type": "function_call", "call_id": "c1", "name": "run_shell", "arguments": {"cmd": "ls"}},
        {"type": "function_call_output", "call_id": "c1",
         "output": [{"type": "input_text", "text": "a.txt"}, {"type": "input_text", "text": "b.txt"}]},
    ], native_tool_calls=True)
    assert msgs[1] == {"role": "assistant", "content": "我先看一下目录", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "run_shell", "arguments": '{"cmd": "ls"}'}}]}
    assert msgs[2] == {"role": "tool", "tool_call_id": "c1", "content": "a.txt\nb.txt"}


def test_gemini_path_keeps_the_text_rendering():
    items = [
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "function_call", "call_id": "c1", "name": "run_shell", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "a.txt"},
    ]
    assert parse_responses_input(items)[1:] == [
        {"role": "assistant", "content": "(called tool run_shell with arguments {})"},
        {"role": "tool", "content": "a.txt"},
    ]

