"""v1.6.33 发版说明公开声称：三条 keepalive 循环在客户端断开时都会 cancel 掉后台
generate task。此前只有 claude 侧一条测试覆盖（test_claude_buffered_cancels_gen_task_on_client_disconnect）；
openai.py::_stream_response_buffered 里的另外两条循环（主 gen_task、retry_task）完全没测。
本文件补上这两条，写法照抄 claude 那条：直接驱动 async generator（__anext__ 拉到 ping，
再 aclose() 模拟断开），再断言后台 task 被 cancel。用 asyncio.run（项目无 pytest-asyncio，
不加 @pytest.mark.asyncio）。"""
import asyncio
import contextlib


def test_stream_response_buffered_cancels_gen_task_on_client_disconnect(monkeypatch):
    """主循环：generate() 慢，客户端在只收到 role 首帧 + 一个 keepalive ping 后断开
    （aclose 该 async generator），后台 gen_task 必须被显式 cancel。"""
    import app.routers.openai as oai
    from app.core import stream as stream_mod

    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    async def slow_generate(prompt, model, conversation_id="", attachments=None,
                            gem_id=None, account_id=None, extended_thinking=False):
        await asyncio.sleep(5)   # long enough that aclose() always arrives first
        return {"text": "done", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(oai.gemini_client, "generate", slow_generate)

    async def run():
        tasks_before = asyncio.all_tasks()
        agen = oai._stream_response_buffered(
            "prompt", "gemini-pro", False, "", None, None,
            "gemini-pro", "chatcmpl-test-A", None, "", None, None, None, None,
        )
        first = await agen.__anext__()           # role frame, emitted before gen_task exists
        assert '"role":"assistant"' in first or '"role": "assistant"' in first

        ping = await agen.__anext__()             # first keepalive frame from the gen_task loop
        assert ": ping" in ping

        new_tasks = asyncio.all_tasks() - tasks_before
        assert len(new_tasks) == 1                # exactly the gen_task created inside
        gen_task = next(iter(new_tasks))
        assert not gen_task.done()

        await agen.aclose()                       # simulate client disconnect
        with contextlib.suppress(asyncio.CancelledError):
            await gen_task
        assert gen_task.cancelled()                # slot-releasing cancellation actually landed

    asyncio.run(run())


def test_stream_response_buffered_cancels_retry_task_on_client_disconnect(monkeypatch):
    """retry_task 循环: 第一次 generate() 立刻失败（有 gemini_conv_id + messages_raw ->
    走会话续接重试分支），重试用的第二次 generate() 很慢，客户端在只收到重试分支压出的
    一个 keepalive ping 后断开，后台 retry_task 必须被显式 cancel。

    进入 retry 分支的条件（读 app/routers/openai.py::_stream_response_buffered 确认）：
    gen_task.result() 抛异常，且 gemini_conv_id 和 messages_raw 都为真值。重试调用固定传
    conversation_id=""，用这个区分两次 generate() 调用该走哪条路径。"""
    import app.routers.openai as oai
    from app.core import stream as stream_mod

    monkeypatch.setattr(stream_mod, "SSE_KEEPALIVE_INTERVAL", 0.05)

    async def flaky_generate(prompt, model, conversation_id="", attachments=None,
                             gem_id=None, account_id=None, extended_thinking=False):
        if conversation_id:
            # first attempt (uses the original gemini_conv_id) fails fast -> triggers retry
            raise RuntimeError("boom")
        # retry attempt (conversation_id == "") is slow enough to observe its keepalive ping
        await asyncio.sleep(5)
        return {"text": "done", "conversation_id": "", "images": [], "thoughts": ""}

    monkeypatch.setattr(oai.gemini_client, "generate", flaky_generate)

    async def run():
        tasks_before = asyncio.all_tasks()
        agen = oai._stream_response_buffered(
            "prompt", "gemini-pro", False, "gconv-1", None,
            [{"role": "user", "content": "hi"}],
            "gemini-pro", "chatcmpl-test-B", None, "", None, None, None, None,
        )
        first = await agen.__anext__()            # role frame
        assert '"role":"assistant"' in first or '"role": "assistant"' in first

        ping = await agen.__anext__()              # first attempt fails fast (no ping from it),
        assert ": ping" in ping                    # this is the retry_task loop's keepalive ping

        new_tasks = asyncio.all_tasks() - tasks_before
        assert len(new_tasks) == 1                 # gen_task already done & swept; only retry_task left
        retry_task = next(iter(new_tasks))
        assert not retry_task.done()

        await agen.aclose()                        # simulate client disconnect
        with contextlib.suppress(asyncio.CancelledError):
            await retry_task
        assert retry_task.cancelled()               # slot-releasing cancellation actually landed

    asyncio.run(run())
