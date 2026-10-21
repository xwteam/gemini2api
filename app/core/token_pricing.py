"""访问密钥用量的**美元估算**价格表。

⚠️ 这里算出来的钱**不是账单**，是「同样的内容若走官方 Gemini API 大约要多少钱」的
参考值。两重近似，面板与文档都必须照实说：
  1. 本服务走的是 Gemini **网页版**，本身不产生任何费用；
  2. token 数来自 app/utils/tools.py 的 estimate_tokens（`len(text)//4`），不是真正的
     分词器 —— 对中文会明显低估（1 个汉字常常就是 1 个 token，这里只算 0.25 个）。

这张表**不参与任何限额判定**。额度限制只有 AccessKey.request_limit（计次）那一条，
token 与美元只统计、不拦人。

内置默认值来源：https://ai.google.dev/gemini-api/docs/pricing
（2026-10-21 北京时间抓取，标准付费档，单位 USD / 百万 token）。
刻意做了三处简化，改价时要连带想到：
  - 官方对 pro 有 >200k 的长上下文阶梯（$4.00/$18.00），这里按 ≤200k 档拍平；
  - 官方有**按日期跳价**，这里不实现时间轴、取当前档：
      gemini-4-argon   2026-12-01 起 输入 $2.00→$4.00、输出 $10.00→$20.00
      gemini-3.8-flash 2027-01-01 起 输入 $0.75→$1.50、输出 $3.75→$7.50
    这两个日期一到，内置默认值就会静默偏低，届时要么改这里、要么用 TOKEN_PRICES 覆盖。
  - gemini-flash-thinking 是本仓自造的公开名，官方没有对应 SKU（thinking 是模式不是
    模型），借用 flash 的价。
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)

# 公开模型名 -> (输入价, 输出价)，单位 USD / 百万 token
DEFAULT_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "gemini-pro": (2.00, 12.00),            # 官方 SKU: gemini-3.1-pro-preview（≤200k 档）
    "gemini-flash": (0.75, 3.75),           # 官方 SKU: gemini-3.8-flash
    "gemini-flash-thinking": (0.75, 3.75),  # 官方无对应 SKU，借用 flash 价
    "gemini-flash-lite": (0.30, 2.50),      # 官方 SKU: gemini-3.5-flash-lite
    "gemini-argon": (2.00, 10.00),          # 官方 SKU: gemini-4-argon
}

_PER_MILLION = 1_000_000.0


def parse_token_prices(raw: str) -> dict[str, tuple[float, float]]:
    """解析 TOKEN_PRICES（形如 "gemini-pro=2.0/12.0,gemini-flash=0.75/3.75"）。

    容错纪律与 _parse_generate_timeouts 完全一致：写错的条目**静默忽略、绝不抛**。
    一个配错的价格表不该让整个面板 500。
    """
    out: dict[str, tuple[float, float]] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, _, value = item.partition("=")
        name = name.strip()
        if not name or "/" not in value:
            continue
        in_raw, _, out_raw = value.partition("/")
        try:
            price_in = float(in_raw.strip())
            price_out = float(out_raw.strip())
        except ValueError:
            continue
        if price_in < 0 or price_out < 0:
            continue
        out[name] = (price_in, price_out)
    return out


def current_token_prices() -> dict[str, tuple[float, float]]:
    """当前生效的价格表：TOKEN_PRICES 配了就用它，否则用内置默认值。

    配置是**整表替换**而不是逐条覆盖：运维显式写了一张表，就该完全按那张表算，
    否则"我把 pro 的价删了"会变成"悄悄回落到内置价"。
    """
    configured = parse_token_prices(getattr(settings, "token_prices", "") or "")
    return configured or dict(DEFAULT_TOKEN_PRICES)


def price_table_name(model: str) -> str:
    """把一个落账用的模型名归一到**价格表的键**（公开名）。

    价格表只按那几个稳定公开名配，但内部模型名是可以直接调的（`gemini-3-pro` 在
    GEMINI_MODELS 里，请求会正常成功），旧别名也还在。不做这层归一的话，一把密钥
    用 gemini-pro 调一次、再用 gemini-3-pro 跑 1 亿 token，面板会显示一个精确得
    不得了的 "≈ $14.00" —— 那 1 亿 token 贡献了 0 —— 正是 M2 红线要防的
    "看着精确其实不准"。

    归一链：原名命中价格表 → 旧别名 → 内部模型名的 family → 找不到就原样返回
    （第三方中转的模型名就该原样留着、显示为未计价）。
    """
    name = str(model or "").strip()
    if not name:
        return name
    # 延迟导入：这个模块只依赖 app.config，不该在导入期把 gemini_client 整条链拉进来。
    try:
        from app.core.gemini_client import GEMINI_MODELS, MODEL_ALIASES, _FAMILY_PUBLIC
    except Exception:          # pragma: no cover - 只在导入环境异常时
        return name
    if name in MODEL_ALIASES:
        return MODEL_ALIASES[name]
    info = GEMINI_MODELS.get(name)
    if info:
        # _FAMILY_PUBLIC 已经是 family -> 公开名
        return _FAMILY_PUBLIC.get(info.get("family")) or name
    return name


def estimate_cost_breakdown(tokens_by_model: dict | None,
                            prices: dict[str, tuple[float, float]] | None = None
                            ) -> tuple[float | None, list[str]]:
    """返回 (估算美元, 算不出价的模型名列表)。

    为什么要第二个返回值：只返回一个 float 的话，"有一部分模型没配价"和"全都配了价"
    长得一模一样 —— 面板会显示一个精确的 "≈ $14.00"，而其中某个模型的 1 亿 token
    贡献了 0。既然"算不出来显示 —"的全部用意就是不让「没花钱」和「不知道价」长得一样，
    那"算出来一半"也不能冒充"算全了"。
    """
    if not isinstance(tokens_by_model, dict) or not tokens_by_model:
        return None, []
    table = prices if prices is not None else current_token_prices()
    total = 0.0
    priced = False
    unpriced: list[str] = []
    for model, counts in tokens_by_model.items():
        if not isinstance(counts, dict):
            continue
        try:
            tokens_in = int(counts.get("in") or 0)
            tokens_out = int(counts.get("out") or 0)
        except (TypeError, ValueError):
            continue
        if not tokens_in and not tokens_out:
            continue
        price = table.get(str(model)) or table.get(price_table_name(model))
        if price is None:
            if str(model) not in unpriced:
                unpriced.append(str(model))
            continue
        total += (tokens_in * price[0] + tokens_out * price[1]) / _PER_MILLION
        priced = True
    return (total if priced else None), unpriced


def estimate_cost_usd(tokens_by_model: dict | None,
                      prices: dict[str, tuple[float, float]] | None = None) -> float | None:
    """按模型明细算出**估算**美元。一条都算不出来时返回 None（面板显示 "—"）。

    返回 None 而不是 0.0 是故意的：「这把密钥没花钱」和「我们不知道这个模型多少钱」
    是两件完全不同的事，显示成同一个 0 会让人以为账是对的。

    一部分模型算不出价时这里仍然返回部分合计 —— 调用方要用 estimate_cost_breakdown
    拿到那张未计价清单并在界面上标出来（见 app/routers/access_keys.py）。
    """
    return estimate_cost_breakdown(tokens_by_model, prices)[0]
