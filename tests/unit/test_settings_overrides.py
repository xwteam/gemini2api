"""面板改动必须跨重启存活（data/settings-overrides.json）。

背景缺陷：docker-compose 用 `env_file: .env` 把宿主机 .env 注入成**真实环境变量**，
pydantic-settings 里 os.environ 优先级高于 dotenv 文件；且 compose 只挂载 ./data 和
./api，宿主机 .env 在容器里不可见，_update_env_file 写的是容器内临时的 /app/.env。
结果：面板上把 LOG_BODIES_ENABLED 关掉、弹"保存成功"，`docker compose restart` 之后
又变回开着，继续记录用户完整提示词，且全程无任何提示。

这里覆盖：环境变量场景下的回放优先级、坏文件不 brick 启动、白名单收口、
以及路由 POST 确实写了持久化文件。
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings, settings
from app.core import settings_overrides as so
import app.routers.settings as sr

_AUTH = {"Authorization": "Bearer sk-test-key"}


@pytest.fixture
def overrides_path(tmp_path, monkeypatch):
    path = tmp_path / "settings-overrides.json"
    monkeypatch.setattr(so, "OVERRIDES_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _restore_settings():
    """settings 是模块级单例，POST 会直接 setattr 且不还原。"""
    keys = ("log_bodies_enabled", "chat_cleanup_keep_hours", "max_retries")
    old = {k: getattr(settings, k) for k in keys}
    yield
    for k, v in old.items():
        object.__setattr__(settings, k, v)


@pytest.fixture
def _no_env_write(monkeypatch):
    captured = {}
    monkeypatch.setattr(sr, "_update_env_file", lambda updates: captured.update(updates))
    return captured


# --------------------------------------------------------------------------
# 核心回归：环境变量说 true，面板持久化的 false 必须赢
# --------------------------------------------------------------------------

def test_override_beats_real_environment_variable(overrides_path, monkeypatch):
    """还原 docker-compose 场景：宿主机 .env 经 env_file 变成真实环境变量。

    没有 overrides 层时 Settings() 只能读到环境变量的 True —— 这正是"面板关了、
    重启后又打开"的根因。
    """
    monkeypatch.setenv("LOG_BODIES_ENABLED", "true")

    fresh = Settings()
    assert fresh.log_bodies_enabled is True, "前提不成立：环境变量本应压过 .env"

    overrides_path.write_text(json.dumps({"log_bodies_enabled": False}), encoding="utf-8")
    applied = so.apply_overrides(fresh, overrides_path)

    assert applied == {"log_bodies_enabled": False}
    assert fresh.log_bodies_enabled is False


def test_override_survives_a_simulated_restart(overrides_path, monkeypatch):
    """保存 -> 重启（重建 Settings 并回放）-> 值还在。"""
    monkeypatch.setenv("LOG_BODIES_ENABLED", "true")

    so.save_overrides({"log_bodies_enabled": False}, overrides_path)

    for _ in range(3):  # 反复"重启"都必须稳定
        rebooted = Settings()
        so.apply_overrides(rebooted, overrides_path)
        assert rebooted.log_bodies_enabled is False


def test_apply_returns_empty_when_no_file(tmp_path):
    fresh = Settings()
    assert so.apply_overrides(fresh, tmp_path / "nope.json") == {}


# --------------------------------------------------------------------------
# 坏文件绝不能 brick 启动
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content",
    ["{ not json", "[]", '"a string"', "null"],
)
def test_corrupt_file_is_ignored_not_fatal(overrides_path, content):
    overrides_path.write_text(content, encoding="utf-8")
    assert so.load_overrides(overrides_path) == {}
    assert so.apply_overrides(Settings(), overrides_path) == {}


@pytest.mark.parametrize(
    "bad",
    [
        {"rotation_strategy": "garbage"},          # 会让 RotationStrategy() 抛异常
        {"max_concurrent_per_account": 0},         # 并发上限 0 = 永远拿不到账号
        {"refresh_interval": -5},                  # 负间隔
        {"log_bodies_enabled": "yes"},             # 类型不对
    ],
)
def test_domain_invalid_values_are_dropped(overrides_path, bad):
    overrides_path.write_text(json.dumps(bad), encoding="utf-8")
    assert so.apply_overrides(Settings(), overrides_path) == {}


def test_non_editable_keys_are_never_loaded_or_saved(overrides_path):
    """持久化文件不是万能后门：只有面板白名单里的字段能被写入/回放。"""
    overrides_path.write_text(
        json.dumps({"api_key": "sk-attacker", "log_bodies_enabled": True}), encoding="utf-8"
    )
    assert so.load_overrides(overrides_path) == {"log_bodies_enabled": True}

    fresh = Settings()
    before = fresh.api_key
    so.apply_overrides(fresh, overrides_path)
    assert fresh.api_key == before

    so.save_overrides({"api_key": "sk-attacker2", "max_retries": 7}, overrides_path)
    assert json.loads(overrides_path.read_text(encoding="utf-8")) == {
        "log_bodies_enabled": True,
        "max_retries": 7,
    }


def test_save_merges_instead_of_replacing(overrides_path):
    so.save_overrides({"max_retries": 7}, overrides_path)
    so.save_overrides({"log_bodies_enabled": True}, overrides_path)
    assert json.loads(overrides_path.read_text(encoding="utf-8")) == {
        "max_retries": 7,
        "log_bodies_enabled": True,
    }


def test_save_creates_missing_parent_directory(tmp_path):
    """容器里 data/ 可能还不存在（首次启动、或空卷）。"""
    target = tmp_path / "data" / "settings-overrides.json"
    so.save_overrides({"log_bodies_enabled": True}, target)
    assert json.loads(target.read_text(encoding="utf-8")) == {"log_bodies_enabled": True}


def test_overrides_live_under_the_bind_mounted_data_dir():
    """默认路径必须在 data/ 下 —— 只有它在 docker-compose 里是 bind mount，重启不丢。

    读源码而不是读模块属性：tests/conftest.py 会把运行时的 OVERRIDES_PATH 重定向到
    临时目录，防止测试改动开发者/CI 的真实文件。
    """
    src = Path(so.__file__).read_text(encoding="utf-8")
    assert 'OVERRIDES_PATH = Path("data/settings-overrides.json")' in src

    compose = Path(so.__file__).resolve().parents[2] / "docker-compose.yml"
    assert "./data:/app/data" in compose.read_text(encoding="utf-8"), (
        "data/ 不再是 bind mount 的话，这套持久化就又不跨重启了"
    )


# --------------------------------------------------------------------------
# 白名单/类型表的一致性守卫
# --------------------------------------------------------------------------

def test_tables_agree_with_each_other_and_with_settings_model():
    # 能持久化的 = 设置页可编辑的 + 各有自己面板入口的（如 API 管理页的兜底开关）
    assert so.PERSISTED_FIELDS == so.EDITABLE_FIELDS | so.EXTRA_PERSISTED_FIELDS
    assert not (so.EDITABLE_FIELDS & so.EXTRA_PERSISTED_FIELDS)
    assert set(so.FIELD_TYPES) == so.PERSISTED_FIELDS
    unknown = so.PERSISTED_FIELDS - set(Settings.model_fields)
    assert not unknown, f"这些字段不在 Settings 上，回放时会被丢弃: {sorted(unknown)}"


def test_router_reexports_the_single_source_of_truth():
    assert sr.EDITABLE_FIELDS is so.EDITABLE_FIELDS
    assert sr.FIELD_TYPES is so.FIELD_TYPES


def test_rotation_strategy_whitelist_matches_the_enum():
    """settings_overrides 不能 import account_pool（循环），故硬编码了枚举取值。

    枚举一旦新增成员而这里没跟上，面板存得进去、回放却会被静默丢弃。
    """
    from app.core.account_pool import RotationStrategy

    assert so.ROTATION_STRATEGIES == {s.value for s in RotationStrategy}


# --------------------------------------------------------------------------
# 路由层：POST 必须真的落到持久化文件
# --------------------------------------------------------------------------

def test_post_persists_to_overrides_file(client, overrides_path, _no_env_write):
    object.__setattr__(settings, "log_bodies_enabled", False)

    resp = client.post(
        "/admin/settings",
        json={"settings": {"log_bodies_enabled": True}},
        headers=_AUTH,
    )
    assert resp.status_code == 200
    assert json.loads(overrides_path.read_text(encoding="utf-8")) == {"log_bodies_enabled": True}

    # 关回去也必须落盘，否则"关掉"只在内存里、重启又开着
    resp = client.post(
        "/admin/settings",
        json={"settings": {"log_bodies_enabled": False}},
        headers=_AUTH,
    )
    assert resp.status_code == 200
    assert json.loads(overrides_path.read_text(encoding="utf-8")) == {"log_bodies_enabled": False}


def test_rejected_post_persists_nothing(client, overrides_path, _no_env_write):
    resp = client.post(
        "/admin/settings",
        json={"settings": {"log_bodies_enabled": "yes"}},
        headers=_AUTH,
    )
    assert resp.status_code == 400
    assert not overrides_path.exists()


def test_config_replays_overrides_at_import_time(tmp_path):
    """真·端到端：起一个干净的 Python 进程，模拟 docker-compose 的部署形态。

    - data/settings-overrides.json 里是面板关掉的 False（data/ 是 bind mount，重启还在）
    - LOG_BODIES_ENABLED=true 是 env_file 注入的真实环境变量（宿主机 .env 那份）

    只 import app.config 就必须看到 False。不在 import 期回放（比如挪到 lifespan、
    或者干脆没接上）的话，account_pool 这些在 import 期读 settings 的模块拿到的还是旧值。
    """
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "settings-overrides.json").write_text(
        json.dumps({"log_bodies_enabled": False, "max_retries": 7}), encoding="utf-8"
    )

    repo_root = Path(so.__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    env["LOG_BODIES_ENABLED"] = "true"
    env["MAX_RETRIES"] = "3"
    env["API_KEY"] = "sk-subprocess-test"

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.config as c;"
            "print(c.settings.log_bodies_enabled, c.settings.max_retries,"
            " sorted(c.APPLIED_OVERRIDES))",
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False 7 ['log_bodies_enabled', 'max_retries']", proc.stdout


def test_env_var_and_override_do_not_interfere_with_other_fields(overrides_path, monkeypatch):
    """回放只动被覆盖的字段，其它字段仍然由环境变量说了算。"""
    monkeypatch.setenv("MAX_RETRIES", "9")
    overrides_path.write_text(json.dumps({"log_bodies_enabled": True}), encoding="utf-8")

    fresh = Settings()
    so.apply_overrides(fresh, overrides_path)
    assert fresh.max_retries == 9
    assert fresh.log_bodies_enabled is True


def test_does_not_touch_process_environment(overrides_path):
    """回放只改内存对象，不污染 os.environ（子进程/refresher 不该被牵连）。"""
    before = dict(os.environ)
    so.save_overrides({"log_bodies_enabled": True}, overrides_path)
    so.apply_overrides(Settings(), overrides_path)
    assert dict(os.environ) == before


# --------------------------------------------------------------------------
# 非有限浮点：NaN / ±Infinity 必须挡在持久化之外
#
# 缺陷：NaN/inf 都是合法 Python float，而 `nan < 0` / `inf < 0` 都是 False，会绕过
# 全部取值域比较；json 模块两端都认这些非 RFC-8259 字面量，于是它们能原样写进
# settings-overrides.json 并在每次启动被回放（还压过环境变量）。
# chat_cleanup_interval_hours=inf → main.py 的 asyncio.sleep(max(1, inf)*3600)
# 永不唤醒，Gemini 会话清理循环从此静默停摆，且改环境变量也救不回来。
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_check_domain_rejects_non_finite_floats(bad):
    reason = so.check_domain("chat_cleanup_interval_hours", bad)
    assert reason is not None, f"{bad!r} 被判为合法取值，会被持久化并每次启动回放"
    assert "finite" in reason


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_apply_overrides_ignores_non_finite_values_in_a_hand_edited_file(
    overrides_path, literal
):
    """手改坏的文件必须被逐条忽略，而不是把 inf 灌进运行时。"""
    overrides_path.write_text(
        '{"chat_cleanup_interval_hours": %s}' % literal, encoding="utf-8"
    )
    fresh = Settings()
    baseline = fresh.chat_cleanup_interval_hours

    applied = so.apply_overrides(fresh, overrides_path)

    assert applied == {}
    assert fresh.chat_cleanup_interval_hours == baseline


@pytest.mark.parametrize("literal", ["NaN", "Infinity"])
def test_post_rejects_non_finite_floats_and_persists_nothing(
    client, overrides_path, _no_env_write, literal
):
    resp = client.post(
        "/admin/settings",
        content=('{"settings": {"chat_cleanup_keep_hours": %s}}' % literal).encode(),
        headers={**_AUTH, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400, resp.text
    assert not overrides_path.exists()


# --------------------------------------------------------------------------
# 写盘失败必须回滚内存
#
# 缺陷：save_overrides / _update_env_file 抛异常时返回 500，但内存里的值已经改了。
# 管理员看到"保存失败"，实际 log_bodies_enabled 已经生效，重启后又悄悄弹回去 ——
# 对隐私开关来说，"以为关掉了、其实还在记录"和反过来都不可接受。
# 触发条件：自定 compose `user:`、rootless podman uid 映射、只读卷等 data/ 不可写的部署。
# --------------------------------------------------------------------------

def test_memory_is_rolled_back_when_persistence_fails(client, overrides_path, monkeypatch):
    object.__setattr__(settings, "log_bodies_enabled", True)

    def _boom(_updates, _path=None):
        raise PermissionError(13, "Permission denied", str(overrides_path))

    monkeypatch.setattr(sr, "save_overrides", _boom)

    resp = client.post(
        "/admin/settings",
        json={"settings": {"log_bodies_enabled": False}},
        headers=_AUTH,
    )
    assert resp.status_code == 500
    assert settings.log_bodies_enabled is True, (
        "返回了 500 却把内存改掉了：面板说保存失败，隐私开关其实已经生效"
    )
    assert not overrides_path.exists()


def test_memory_is_rolled_back_when_env_write_fails(client, overrides_path, monkeypatch):
    object.__setattr__(settings, "max_retries", 3)
    monkeypatch.setattr(
        sr, "_update_env_file", lambda updates: (_ for _ in ()).throw(PermissionError(".env"))
    )

    resp = client.post(
        "/admin/settings",
        json={"settings": {"max_retries": 9}},
        headers=_AUTH,
    )
    assert resp.status_code == 500
    assert settings.max_retries == 3


def test_failure_detail_does_not_leak_filesystem_paths(client, overrides_path, monkeypatch):
    """500 的 detail 不该把容器内绝对路径 / 原子写临时文件名回给浏览器。"""
    secret_path = "/app/data/settings-overrides.json.abc123.tmp"

    def _boom(_updates, _path=None):
        raise PermissionError(13, "Permission denied", secret_path)

    monkeypatch.setattr(sr, "save_overrides", _boom)

    resp = client.post(
        "/admin/settings",
        json={"settings": {"log_bodies_enabled": False}},
        headers=_AUTH,
    )
    assert resp.status_code == 500
    assert secret_path not in resp.text
    assert ".tmp" not in resp.text


# --------------------------------------------------------------------------
# 三层存储必须全有或全无
#
# 缺陷：写盘顺序是「覆盖文件 → .env」，但失败时只回滚内存。.env 只读（0400、只读卷、
# rootless podman uid 映射）时，save_overrides 已经把值写进了**优先级最高**的
# data/settings-overrides.json，随后 _update_env_file 抛异常 → 500 → 内存被回滚。
# 管理员看到"保存失败"，以为什么都没发生；容器下次重启时覆盖文件生效，
# log_bodies_enabled 被静默打开，用户的完整提示词从此进日志 —— 恰好把这次要提供的
# 隐私保证反了过来。
#
# 下面用真实文件权限复现，不打桩：打桩测不出"写盘顺序"这个根因。
# --------------------------------------------------------------------------

@pytest.fixture
def disk_layers(tmp_path, monkeypatch):
    """把两层落盘目标都指到 tmp_path，用真实文件 + 真实权限位驱动。

    ``.env`` 由 ``app.routers.settings.ENV_PATH``（相对路径）在打开时相对 CWD 解析，
    所以直接 chdir 过去；覆盖文件走 ``so.OVERRIDES_PATH``。
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    overrides = data_dir / "settings-overrides.json"
    monkeypatch.setattr(so, "OVERRIDES_PATH", overrides)
    monkeypatch.chdir(tmp_path)
    layers = SimpleNamespace(env=tmp_path / ".env", overrides=overrides, data_dir=data_dir)
    try:
        yield layers
    finally:
        # 只读目录/文件会让 tmp_path 的清理失败，收尾一律恢复可写。
        for p in (data_dir, layers.env):
            if p.exists():
                p.chmod(0o700 if p.is_dir() else 0o600)


def test_readonly_env_leaves_the_overrides_file_byte_identical(client, disk_layers):
    """.env 不可写 → 500，且优先级最高的覆盖文件必须逐字节没变。

    这是隐私反转的正面复现：不回滚覆盖文件的话，这里断言的字节会变成 true。
    """
    object.__setattr__(settings, "log_bodies_enabled", False)
    disk_layers.overrides.write_text('{\n  "log_bodies_enabled": false\n}', encoding="utf-8")
    overrides_before = disk_layers.overrides.read_bytes()
    disk_layers.env.write_text("LOG_BODIES_ENABLED=false\n", encoding="utf-8")
    env_before = disk_layers.env.read_bytes()
    disk_layers.env.chmod(0o400)

    resp = client.post(
        "/admin/settings",
        json={"settings": {"log_bodies_enabled": True}},
        headers=_AUTH,
    )

    assert resp.status_code == 500, resp.text
    assert disk_layers.overrides.read_bytes() == overrides_before, (
        "返回了 500，覆盖文件却已经写进了新值：它优先级高于环境变量，"
        "下次重启会静默打开完整提示词日志，而管理员以为什么都没发生"
    )
    assert disk_layers.env.read_bytes() == env_before
    assert settings.log_bodies_enabled is False
    assert so.load_overrides(disk_layers.overrides)["log_bodies_enabled"] is False, (
        "重启回放拿到的仍必须是请求前的值"
    )


def test_rollback_deletes_an_overrides_file_that_did_not_exist_before(client, disk_layers):
    """覆盖文件原本不存在 + 后续写盘失败 → 回滚后它必须仍然不存在。

    留下半成品文件同样是隐私反转：全新部署第一次改设置就撞上只读 .env 时，
    磁盘上会凭空多出一份没人知道、却压过环境变量的配置。
    """
    object.__setattr__(settings, "log_bodies_enabled", False)
    assert not disk_layers.overrides.exists(), "前提变了：覆盖文件本应不存在"
    disk_layers.env.write_text("LOG_BODIES_ENABLED=false\n", encoding="utf-8")
    disk_layers.env.chmod(0o400)

    resp = client.post(
        "/admin/settings",
        json={"settings": {"log_bodies_enabled": True}},
        headers=_AUTH,
    )

    assert resp.status_code == 500, resp.text
    assert not disk_layers.overrides.exists(), (
        "回滚后留下了半成品覆盖文件，重启时会生效"
    )
    assert settings.log_bodies_enabled is False


def test_readonly_data_dir_leaves_env_and_memory_untouched(client, disk_layers):
    """data/ 不可写 → 500，.env 与内存都回到请求前。"""
    object.__setattr__(settings, "max_retries", 3)
    disk_layers.env.write_text("MAX_RETRIES=3\n", encoding="utf-8")
    env_before = disk_layers.env.read_bytes()
    disk_layers.data_dir.chmod(0o500)

    resp = client.post(
        "/admin/settings",
        json={"settings": {"max_retries": 9}},
        headers=_AUTH,
    )

    assert resp.status_code == 500, resp.text
    assert disk_layers.env.read_bytes() == env_before
    assert settings.max_retries == 3
    assert not disk_layers.overrides.exists()


def test_happy_path_still_writes_all_three_layers(client, disk_layers):
    """三层都可写时行为不变：内存 / 覆盖文件 / .env 全部落到新值。"""
    object.__setattr__(settings, "log_bodies_enabled", False)
    disk_layers.env.write_text("LOG_BODIES_ENABLED=false\n", encoding="utf-8")

    resp = client.post(
        "/admin/settings",
        json={"settings": {"log_bodies_enabled": True}},
        headers=_AUTH,
    )

    assert resp.status_code == 200, resp.text
    assert settings.log_bodies_enabled is True
    assert json.loads(disk_layers.overrides.read_text(encoding="utf-8"))["log_bodies_enabled"] is True
    assert "LOG_BODIES_ENABLED=True" in disk_layers.env.read_text(encoding="utf-8")
