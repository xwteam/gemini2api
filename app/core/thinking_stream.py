"""真流式路径上"不回传的思考"怎么处理（四个协议的路由共用）。

按默认档替客户端开的思考只给上游用、不回传（见 gemini_client.ThinkingPlan.show）。
过去各路由是在 iter_with_keepalive **之后**才把 thoughts 事件吞掉的：

    async for kind, evt in iter_with_keepalive(generate_stream(...)):
        if evt["type"] == "thoughts" and not show:
            continue          # 一个字节都不写

iter_with_keepalive 只在"上游静默满一个间隔"时才发保活帧，而思考期间上游每隔几秒
就来一个 thoughts 事件 —— 计时器一次次被重置，保活帧一个都不发，客户端在整段思考
期间（pro 实测 36～65 秒）收到零字节。Gemini 原生流在此之前一个字节都还没发，过不了
EdgeOne 免费版 15 秒的首字节限制；另外三个协议虽然已发过开场帧，也会撞上反代的空闲
读超时。

所以把不回传的 thoughts 事件挪到 iter_with_keepalive **之前**过滤掉：对保活计时器来说
"上游在想、但没有要写给客户端的东西"就等于静默，到点照发保活帧。思考文本照样收进
sink 供按-key 用量记账。不动 app/core/stream.py。
"""

from typing import Any, AsyncIterator


class HiddenThoughts:
    """被过滤掉的思考文本（只进内部记账）。"""

    __slots__ = ("text",)

    def __init__(self) -> None:
        self.text = ""


async def drop_thought_events(agen: AsyncIterator[Any], sink: HiddenThoughts) -> AsyncIterator[Any]:
    """原样转发 agen 的事件，只把 {"type": "thoughts"} 事件吞掉并累加进 sink。

    上游异常原样透传（交给 iter_with_keepalive → 路由既有的 try/except）。
    """
    async for evt in agen:
        if isinstance(evt, dict) and evt.get("type") == "thoughts":
            sink.text += evt.get("text", "") or ""
            continue
        yield evt
