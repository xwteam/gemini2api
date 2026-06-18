"""Unit tests for ``app.core.model_mapping.ModelMapping`` (stdlib-only).

Uses a temp file so the real ``data/model-mapping.json`` is never touched.
"""

from app.core.model_mapping import ModelMapping


def _new(tmp_path):
    return ModelMapping(path=str(tmp_path / "model-mapping.json"))


def test_resolve_unknown_returns_input(tmp_path):
    mm = _new(tmp_path)
    assert mm.resolve("gpt-4") == "gpt-4"


def test_set_then_resolve(tmp_path):
    mm = _new(tmp_path)
    mm.set("alias", "gemini-3-pro")
    assert mm.resolve("alias") == "gemini-3-pro"


def test_get_all_is_a_copy(tmp_path):
    mm = _new(tmp_path)
    mm.set("a", "b")
    snapshot = mm.get_all()
    snapshot["a"] = "tampered"
    assert mm.resolve("a") == "b"  # internal state unaffected


def test_delete(tmp_path):
    mm = _new(tmp_path)
    mm.set("a", "b")
    assert mm.delete("a") is True
    assert mm.resolve("a") == "a"
    assert mm.delete("missing") is False


def test_persistence_across_instances(tmp_path):
    path = str(tmp_path / "model-mapping.json")
    ModelMapping(path=path).set("x", "y")
    reloaded = ModelMapping(path=path)
    assert reloaded.resolve("x") == "y"
