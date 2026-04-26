import pytest

from ayvu.glossary import GlossaryError, apply_glossary, load_glossary


def test_apply_glossary_replaces_terms():
    glossary = {"Game Loop": "loop de jogo", "Object Pool": "pool de objetos"}
    assert apply_glossary("A Game Loop can use an Object Pool.", glossary) == (
        "A loop de jogo can use an pool de objetos."
    )


def test_apply_glossary_preserves_all_caps():
    assert apply_glossary("OBSERVER", {"Observer": "Observer"}) == "OBSERVER"


def test_apply_glossary_prefers_longer_terms():
    glossary = {"Pattern": "padrão", "Design Pattern": "padrão de projeto"}
    assert apply_glossary("Design Pattern", glossary) == "padrão de projeto"


def test_load_glossary_missing_file_has_clear_error(tmp_path):
    with pytest.raises(GlossaryError, match="Glossary file not found"):
        load_glossary(tmp_path / "missing.json")
