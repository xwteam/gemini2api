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


def estimate_cost_usd(tokens_by_model: dict | None,
                      prices: dict[str, tuple[float, float]] | None = None) -> float | None:
    """按模型明细算出**估算**美元。一条都算不出来时返回 None（面板显示 "—"）。

    返回 None 而不是 0.0 是故意的：「这把密钥没花钱」和「我们不知道这个模型多少钱」
    是两件完全不同的事，显示成同一个 0 会让人以为账是对的。
    """
    if not isinstance(tokens_by_model, dict) or not tokens_by_model:
        return None
    table = prices if prices is not None else current_token_prices()
    total = 0.0
    priced = False
    for model, counts in tokens_by_model.items():
        price = table.get(str(model))
        if price is None or not isinstance(counts, dict):
            continue
        try:
            tokens_in = int(counts.get("in") or 0)
            tokens_out = int(counts.get("out") or 0)
        except (TypeError, ValueError):
            continue
        total += (tokens_in * price[0] + tokens_out * price[1]) / _PER_MILLION
        priced = True
    return total if priced else None
