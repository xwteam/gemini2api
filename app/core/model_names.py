"""心跳给过的真实模型名的「改名历史」：``data/model-names.json``（v1.6.54 规格 R2 / R7）。

对外模型名现在就是网页上的真实名字（``4 Neon`` → ``gemini-4-neon``），谷歌一改名，下一次心跳
列表就跟着换。可客户端里配好的旧名字不能因此 400：凡是心跳**曾经**给过的真实名字，都在这里记下
「名字 → (model id, family)」，进程重启后仍在。谷歌把 ``4 Neon`` 改成 ``4.1 Neon``（id 不变）时，
``gemini-4-neon`` 照样解析到那个 id，再按路由规则发给「当前列表里有这个 id 的账号」。

只用于**解析**，不用于列出：列表永远是各账号此刻心跳报的名字（见 GeminiWebClient._available_models）。

为什么一个名字可以挂多个 id：同一个名字在不同账号上可以是不同的模型（Pro 账号的 ``Auto`` 是
8c46…，免费账号的 ``Auto`` 是 cf41…）。只记一个的话，两个账号轮流心跳会让它来回翻、每轮都写盘；
解析时又只能认其中一个，另一个账号上明明有、却被判成没有。

防撑爆：名字 / id / family 都按心跳发现同一套口径校验（不合格的不记），整张表封顶 MAX_NAMES 条，
满了按「最久没在心跳里见过」淘汰 —— 当前还在用的名字每天至少被刷新一次，淘汰不到它们。
seen 只按天刷新，所以同样的心跳反复跑不会每轮都写盘。

一个名字只属于一个族：同一个名字换了族（一轮异常心跳把 Hydrogen 的 id 报成「4 Carbon」），整条
记录换掉，不把两个族的 id 并在一起 —— 并在一起的话，异常过去以后这条脏映射还永远留在盘上，
没有 Carbon 的账号会把 gemini-4-carbon 发成 Hydrogen（悄悄换模型）。

读：文件缺失 / 损坏 / 结构不对 / 解析出错一律当空（= 没有历史），逐条校验，不合格的条目丢掉。
这张表在请求路径上（「是不是 Gemini 模型」的闸门、计价），读坏了绝不能抛。
写：持锁；落盘走同目录临时文件 + ``os.replace``（``app.utils.atomic_io``），失败只记日志。

本模块只依赖标准库和 ``app.utils.atomic_io``，tests/conftest.py 会在每个测试前把它指到临时文件。
"""

import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Iterable, Optional, Union

from app.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# data/ 在 docker-compose 里是 bind mount（./data:/app/data），重启/升级都不丢。
NAMES_PATH = Path("data/model-names.json")

# 真实账号一共 4 个模型、每次改名多 1 条；64 条够记十几轮改名，到这个数只能说明心跳被污染了。
MAX_NAMES = 64
# 同一个名字最多挂几个 id（不同账号同名不同模型，见模块说明）。
MAX_IDS_PER_NAME = 4
# seen 按天刷新：只为淘汰排序用，不需要更细。
SEEN_REFRESH_SECONDS = 24 * 3600

# 与 gemini_client 的 _DISCOVER_NAME_RE / _DISCOVER_ID_RE / _DISCOVER_FAMILY_RE 同口径
# （这里不 import gemini_client：它是个很重的模块，而这张表在它导入期就要用）。
NAME_RE = re.compile(r"^gemini-[a-z0-9][a-z0-9.\-]{0,39}$")
_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_FAMILY_RE = re.compile(r"^[a-z][a-z0-9.\-]{0,31}$")

_PathLike = Optional[Union[str, Path]]


def _valid(name, model_id, family) -> bool:
    return (isinstance(name, str) and bool(NAME_RE.match(name))
            and isinstance(model_id, str) and bool(_ID_RE.match(model_id))
            and isinstance(family, str) and bool(_FAMILY_RE.match(family)))


def _parse(data) -> dict:
    """文件内容 → {名字: {"ids": [...], "family": str, "seen": int}}，不合格的条目逐条丢掉。"""
    names = data.get("names") if isinstance(data, dict) else None
    if not isinstance(names, dict):
        return {}
    out: dict = {}
    for name, rec in names.items():
        if not isinstance(rec, dict):
            continue
        family = rec.get("family")
        ids = rec.get("ids")
        if not isinstance(ids, list):
            continue
        ids = [i for i in ids if isinstance(i, str) and _ID_RE.match(i)][-MAX_IDS_PER_NAME:]
        if not ids or not _valid(name, ids[0], family):
            continue
        seen = rec.get("seen")
        # json 把 1e999 / Infinity 读成 inf、NaN 读成 nan，int() 会抛：不是有限数就当 0（最先被淘汰）
        seen = (int(seen) if isinstance(seen, (int, float)) and not isinstance(seen, bool)
                and math.isfinite(seen) else 0)
        out[name] = {"ids": list(dict.fromkeys(ids)), "family": family, "seen": seen}
    if len(out) > MAX_NAMES:
        keep = sorted(out, key=lambda n: out[n]["seen"], reverse=True)[:MAX_NAMES]
        out = {n: out[n] for n in out if n in keep}
    return out


class ModelNameHistory:
    def __init__(self, path: _PathLike = None):
        self._path = path
        self._names: Optional[dict] = None     # None = 还没读盘（懒加载）
        self._lock = threading.Lock()

    def _file(self) -> Path:
        # 每次现取模块变量：conftest 在导入后才把 NAMES_PATH 指到临时目录
        return Path(self._path) if self._path is not None else NAMES_PATH

    def _load_locked(self) -> dict:
        if self._names is not None:
            return self._names
        path = self._file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        # ValueError：坏 JSON / 不是 UTF-8；RecursionError：嵌套太深的 JSON
        except (OSError, ValueError, RecursionError) as e:
            logger.warning(f"Ignoring unreadable model name history {path}: {e}")
            data = {}
        try:
            self._names = _parse(data)
        except Exception as e:   # 兜底：解析出错也当空，绝不让每次 lookup 都重新读盘再抛一次
            logger.warning(f"Ignoring malformed model name history {path}: {e}")
            self._names = {}
        return self._names

    def reset(self, path: _PathLike = None) -> None:
        """丢掉内存里的那份（下次用时重新读盘），可顺便换文件。测试用来模拟「进程重启」。"""
        with self._lock:
            self._path = path
            self._names = None

    def lookup(self, name: str) -> Optional[dict]:
        """名字 → {"ids": [...], "family": str}；没记过 → None。"""
        if not isinstance(name, str):
            return None
        with self._lock:
            rec = self._load_locked().get(name)
            return {"ids": list(rec["ids"]), "family": rec["family"]} if rec else None

    def items(self) -> list[tuple[str, str]]:
        """[(名字, family)]，按记录顺序（给"不带版本号的别名"推导用）。"""
        with self._lock:
            return [(n, r["family"]) for n, r in self._load_locked().items()]

    def record(self, entries: Iterable[tuple], now: Optional[float] = None) -> None:
        """记下一轮心跳里的 (真实名字, model id, family)。有变化才落盘；不合格的条目跳过。"""
        now = int(time.time() if now is None else now)
        with self._lock:
            names = self._load_locked()
            changed = False
            for item in entries:
                try:
                    name, model_id, family = item
                except (TypeError, ValueError):
                    continue
                if not _valid(name, model_id, family):
                    continue
                rec = names.get(name)
                if rec is None:
                    names[name] = {"ids": [model_id], "family": family, "seen": now}
                    changed = True
                    continue
                touched = False
                if rec["family"] != family:
                    # 换了族：整条换掉（见模块说明），旧族的 id 一个都不留
                    logger.info(
                        "Model name %s now belongs to family %s (was %s, ids %s); "
                        "replacing its history record", name, family, rec["family"], rec["ids"],
                    )
                    rec["ids"] = [model_id]
                    rec["family"] = family
                    touched = True
                elif model_id not in rec["ids"]:
                    rec["ids"] = (rec["ids"] + [model_id])[-MAX_IDS_PER_NAME:]
                    touched = True
                if touched or now - rec["seen"] >= SEEN_REFRESH_SECONDS:
                    rec["seen"] = now
                    changed = True
            if len(names) > MAX_NAMES:
                drop = sorted(names, key=lambda n: names[n]["seen"])[:len(names) - MAX_NAMES]
                logger.warning(
                    "Model name history is full (%d names); forgetting the least recently seen: %s",
                    MAX_NAMES, drop,
                )
                for n in drop:
                    names.pop(n, None)
                changed = True
            if not changed:
                return
            path = self._file()
            try:
                atomic_write_json(path, {"version": 1, "names": names}, indent=2)
            except OSError as e:
                logger.warning(f"Could not persist model name history to {path}: {e}")


history = ModelNameHistory()
