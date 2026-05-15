import asyncio
import json
from typing import AsyncGenerator


async def split_into_chunks(text: str, delay: float = 0.03) -> AsyncGenerator[str, None]:
    words = text.split(" ")
    for i, word in enumerate(words):
        chunk = word if i == len(words) - 1 else word + " "
        yield chunk
        await asyncio.sleep(delay)


def format_sse(data: dict | str) -> str:
    if isinstance(data, dict):
        return f"data: {json.dumps(data)}\n\n"
    return f"data: {data}\n\n"
