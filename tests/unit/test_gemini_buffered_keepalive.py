"""原生 Gemini streamGenerateContent 的 buffered 分支（has_tools/attachments）此前 await
generate 期间零字节——比 SSE 端点更糟：这不是空闲读超时，是首字节超时，60s 首字节限制的
代理会直接杀连接（GAP ⑤）。NDJSON 流不能用 SSE 注释帧保活，必须是裸换行。"""
import asyncio
import contextlib

_AUTH = {"Authorization": "Bearer sk-test-key"}
_TOOLS = [{"function_declarations": [
    {"name": "run", "description": "run cmd", "parameters": {"type": "object"}}]}]


def _body(text="run the tests"):
    return {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "tools": _TOOLS,
    }


def test_gemini_buffered_emits_blankline_keepalive_before_first_payload(gem_client, monkeypatch):
    import app.routers.gemini as gm
    from app.core import stream as stream_mod
    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    async def slow_generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                            account_id=None, extended_thinking=False):
        await asyncio.sleep(0.25)
        return {"text": "85", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(gm.gemini_client, "generate", slow_generate)
    with gem_client.stream("POST", "/v1beta/models/gemini-flash:streamGenerateContent",
                           json=_body(), headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert ": ping" not in body               # SSE 注释帧绝不能混进 NDJSON 流
    assert "\n\n" in body                      # 空行心跳出现（正常逐行输出不会有连续换行）
    assert '{"candidates"' in body             # 答案照常
    assert body.index("\n\n") < body.index('{"candidates"')   # 心跳先于首个真实 payload（此前零字节）


def test_gemini_buffered_error_path_unchanged(gem_client, monkeypatch):
    """generate 抛错时仍走原有 error 行，不被保活吞掉。"""
    import app.routers.gemini as gm

    async def boom(prompt, model, conversation_id="", attachments=None, gem_id=None, account_id=None, extended_thinking=False):
        raise RuntimeError("boom")

    monkeypatch.setattr(gm.gemini_client, "generate", boom)
    with gem_client.stream("POST", "/v1beta/models/gemini-flash:streamGenerateContent",
                           json=_body(), headers=_AUTH) as r:
        body = "".join(r.iter_text())
    assert "boom" in body
    assert '"type": "api_error"' in body


def test_gemini_buffered_cancels_gen_task_on_client_disconnect(monkeypatch):
    """客户端提前断开（生成器被 aclose，即 GeneratorExit）时，后台 generate task 必须被显式
    cancel，不能留成脱缰 task 继续跑完并占着账号槽位。stream_generate_content 里的 buffered
    逻辑是路由函数内部的闭包生成器，非独立顶层函数——用 functools.wraps 保留的 __wrapped__
    拿到限流装饰器包裹前的原始协程函数（绕开 slowapi，无需构造真实 Request/app.state），
    拿到 StreamingResponse 后驱动它的 body_iterator（项目里 test_open_stream.py 同款手法）。
    用 asyncio.run，不用 pytest-asyncio（项目约定）。"""
    import app.routers.gemini as gm
    from app.core import stream as stream_mod
    from app.models.gemini import GeminiRequest, GeminiContent, GeminiPart, GeminiToolDef, GeminiFunctionDecl

    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    async def slow_generate(prompt, model, conversation_id="", attachments=None, gem_id=None,
                            account_id=None, extended_thinking=False):
        await asyncio.sleep(5)   # long enough that aclose() always arrives first
        return {"text": "done", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(gm.gemini_client, "generate", slow_generate)

    class _FakeState:
        pass

    class _FakeApp:
        state = _FakeState()

    class _FakeRequest:
        app = _FakeApp()

    req = GeminiRequest(
        contents=[GeminiContent(role="user", parts=[GeminiPart(text="run the tests")])],
        tools=[GeminiToolDef(function_declarations=[
            GeminiFunctionDecl(name="run", description="run cmd", parameters={"type": "object"}),
        ])],
    )

    async def run():
        tasks_before = asyncio.all_tasks()
        resp = await gm.stream_generate_content.__wrapped__("gemini-pro", req, _FakeRequest())
        agen = resp.body_iterator

        first = await agen.__anext__()          # pull exactly the first (keepalive) frame
        assert first == "\n"

        new_tasks = asyncio.all_tasks() - tasks_before
        assert len(new_tasks) == 1               # exactly the gen_task created inside
        gen_task = next(iter(new_tasks))
        assert not gen_task.done()

        await agen.aclose()                      # simulate client disconnect
        with contextlib.suppress(asyncio.CancelledError):
            await gen_task
        assert gen_task.cancelled()               # slot-releasing cancellation actually landed

    asyncio.run(run())
