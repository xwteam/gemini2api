from app.core.gem_mapping import GemMapping


def _new(tmp_path):
    return GemMapping(path=str(tmp_path / "gem-mapping.json"))


def test_set_then_resolve(tmp_path):
    gm = _new(tmp_path)
    gm.set("my-gem", {"gem_id": "g1", "base_model": "gemini-pro", "account_id": "account-0"})
    assert gm.resolve("my-gem") == {"gem_id": "g1", "base_model": "gemini-pro", "account_id": "account-0"}


def test_resolve_unknown_returns_none(tmp_path):
    gm = _new(tmp_path)
    assert gm.resolve("nope") is None


def test_persist_across_instances(tmp_path):
    p = str(tmp_path / "gem-mapping.json")
    GemMapping(path=p).set("g", {"gem_id": "x", "base_model": "gemini-flash", "account_id": "a"})
    assert GemMapping(path=p).resolve("g")["gem_id"] == "x"


def test_delete(tmp_path):
    gm = _new(tmp_path)
    gm.set("g", {"gem_id": "x", "base_model": "gemini-pro", "account_id": "a"})
    assert gm.delete("g") is True
    assert gm.resolve("g") is None
    assert gm.delete("g") is False


def test_get_all_is_a_copy(tmp_path):
    gm = _new(tmp_path)
    gm.set("g", {"gem_id": "x", "base_model": "gemini-pro", "account_id": "a"})
    snap = gm.get_all()
    snap["g"]["gem_id"] = "tampered"
    assert gm.resolve("g")["gem_id"] == "x"
