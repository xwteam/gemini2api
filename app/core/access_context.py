"""本次请求命中的访问密钥（AccessKey）的请求级上下文。

为什么用 ContextVar 而不是把 `allowed_account_ids` 一路透传给 generate/generate_stream：
那两个方法在 5 个协议路由里有 30+ 个调用点，其中 research.py 的几处连 FastAPI 的
Request 对象都拿不到（参数名被 Pydantic 模型遮蔽）。ContextVar 在 verify_api_key
（全局依赖）里设置一次，同一个 asyncio 任务里的端点函数、它 create_task 出来的子任务、
以及 StreamingResponse 的生成器迭代都能读到，且天然按请求隔离——每个请求在自己的
任务里跑，contextvars 在任务创建时复制，互不串写。

没有访问密钥（env API_KEY 直连，或一把访问密钥都没签发）时，取值恒为 None，
所有下游判断都是一次 `is None` 短路，零开销、零行为变化。
"""

import logging
from contextvars import ContextVar
from typing import Optional

from fastapi import HTTPException

from app.core.access_key_store import AccessKey

logger = logging.getLogger(__name__)

_current_access_key: ContextVar[Optional[AccessKey]] = ContextVar(
    "current_access_key", default=None
)


def set_current_access_key(entry: Optional[AccessKey]) -> None:
    _current_access_key.set(entry)


def get_current_access_key() -> Optional[AccessKey]:
    return _current_access_key.get()


# 本次请求是否已经记过用量。11 个落账点每一个都是它所在那条分支的终点，不可能同一个
# 请求里有两个"真正交付了答案"的点；这道幂等守卫把 fallback / 工具重试 / 异常回落导致的
# 重复计数一次性堵死，省掉逐点推演。
_usage_recorded: ContextVar[bool] = ContextVar("access_key_usage_recorded", default=False)


def record_token_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    """把本次请求的**估算** token 记到命中的访问密钥上（只统计、不限额）。

    为什么不在中间件里收口：log_capture_middleware 是 `await call_next(request)` 之后
    立刻记日志，而对 StreamingResponse 来说 call_next 返回时生成器**一个字节都还没
    迭代**，所以流式路径算出来的 token 中间件永远看不到（仓里自己就把流式响应体标成
    _STREAMING_NOT_CAPTURED）。ContextVar 在 verify_api_key 里设一次，端点函数、它
    create_task 出来的子任务、以及 StreamingResponse 的生成器迭代都能读到 —— 这就是
    "中间件拿得到 key、路由层才算得出 token"之间现成的桥，不需要动 request.state、
    不需要改任何函数签名。

    ⚠️ 调用点必须留在生成器自己的函数体里，**不能挪进 asyncio.create_task 的协程**：
    ContextVar 在建任务时是**复制**上下文，子任务里读 key 没问题，但 _usage_recorded
    的写不会回到父上下文，幂等守卫会失效 → 可能双计。

    没有访问密钥（.env API_KEY 直连 / 一把都没签发）时是一次 `is None` 短路，
    零开销、零行为变化。
    """
    entry = _current_access_key.get()
    if entry is None or _usage_recorded.get():
        return
    _usage_recorded.set(True)
    try:
        from app.core.access_key_store import access_key_store
        from app.core.token_pricing import price_table_name
        # 归一到价格表的键（公开名）：价格表是按那几个稳定公开名配的。用 gemini-2.5-pro
        # （旧别名）或 gemini-3-pro（内部名，直接调也能通）调同一个模型，不该在面板上
        # 单开一行、还因为"没配价"把那段用量算成 0 美元。认不出的名字（第三方中转的
        # 模型）原样留着，由面板显示成未计价。
        name = price_table_name(model) or model
        access_key_store.add_token_usage(entry.id, name, input_tokens, output_tokens)
    except Exception:          # 统计绝不能让一个已经成功的回答失败
        logger.debug("record_token_usage failed", exc_info=True)


def current_bound_account_ids() -> Optional[set]:
    """本次请求允许使用的账号 id 集合；None = 不限制。"""
    entry = _current_access_key.get()
    if entry is None:
        return None
    return entry.bound_account_set()


def current_allowed_models() -> Optional[set]:
    """本次请求允许使用的模型名集合；None = 不限制。"""
    entry = _current_access_key.get()
    if entry is None:
        return None
    return entry.allowed_model_set()


def scoped_conversation_id(conv_id: str) -> str:
    """把客户端给的 conversation_id 收进「本次访问密钥」自己的命名空间。

    conversation_store 的 key 完全由客户端提供（`conversation_id: "1"` 这种一撞就撞），
    而本功能的用途正是把密钥分发给不同的人：不加命名空间，乙方只要用同一个
    conversation_id 就能接着甲方的上游 Gemini 会话往下聊（"把上面的内容重复一遍"
    就能读到甲方的对话），短 id 还能被枚举。

    没有访问密钥（.env API_KEY 直连 / 一把都没签发）时原样返回，这条路径逐字节不变。
    id 是纯数字、分隔符用 '.'，所以前缀映射是单射的（ak1.「1.x」≠ ak11.「x」）。
    """
    entry = _current_access_key.get()
    if entry is None:
        return conv_id
    return f"ak{entry.id}.{conv_id}"


def _strip_models_prefix(name: str) -> str:
    return name[7:] if name.startswith("models/") else name


def ensure_model_allowed(*names: str) -> None:
    """访问密钥限定了模型时，本次请求的模型必须命中其中之一，否则 403。

    传入「客户端原样请求的模型名」和「别名/Gem 解析后的模型名」，任一命中即放行：
    管理员在面板上勾的是模型列表里的名字，而客户端可能用别名调用同一个模型。
    """
    allowed = current_allowed_models()
    if allowed is None:
        return
    candidates = {_strip_models_prefix(str(n)) for n in names if n}
    if candidates & allowed:
        return
    requested = next((str(n) for n in names if n), "")
    raise HTTPException(
        status_code=403,
        detail={
            "error": {
                "message": f"Model '{requested}' is not allowed for this access key.",
                "type": "access_key_model_denied",
            }
        },
    )


def filter_models_for_access_key(models) -> list:
    """按访问密钥的 allowed_models 过滤模型列表（在 MODEL_WHITELIST 之后再叠一层）。"""
    allowed = current_allowed_models()
    if allowed is None:
        return list(models)
    return [m for m in models if _strip_models_prefix(str(m)) in allowed]


def with_retired_models_for_access_key(models) -> list:
    """Gemini 模型列表 + 当前访问密钥**明确勾选过**的已下线公开名（如 gemini-flash-thinking）。

    gemini-flash-thinking 下线后作为隐藏别名照常能调，但不再出现在任何列表里。对一把
    allowed_models 里只有它的旧密钥来说，三个协议的模型列表会一下子变成空的 —— 客户端
    （Cherry Studio / Open WebUI 这类"先拉列表再选"的）就会显示"无可用模型"，用户以为
    密钥坏了。所以：密钥自己勾过的已下线名照旧列给这把密钥（与 v1.6.42 一致），没勾过的
    密钥、以及不限模型 / 没有访问密钥的请求，列表一个字都不变。
    """
    models = list(models)
    allowed = current_allowed_models()
    if allowed is None:
        return models
    from app.core.gemini_client import _RETIRED_PUBLIC_MODELS   # 延迟导入，避免循环依赖
    return models + [m for m in _RETIRED_PUBLIC_MODELS if m in allowed and m not in models]
