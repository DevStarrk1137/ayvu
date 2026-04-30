import pytest

from ayvu.glossary import Glossary, GlossaryError, apply_glossary, load_glossary


def test_apply_glossary_replaces_terms():
    glossary = Glossary({"Game Loop": "loop de jogo", "Object Pool": "pool de objetos"})
    assert apply_glossary("A Game Loop can use an Object Pool.", glossary) == (
        "A loop de jogo can use an pool de objetos."
    )


def test_apply_glossary_preserves_all_caps():
    assert apply_glossary("OBSERVER", {"Observer": "Observer"}) == "OBSERVER"


def test_apply_glossary_prefers_longer_terms():
    glossary = Glossary({"Pattern": "padrão", "Design Pattern": "padrão de projeto"})
    assert apply_glossary("Design Pattern", glossary) == "padrão de projeto"


def test_load_glossary_returns_glossary_object(tmp_path):
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text('{"Observer": "Observer"}', encoding="utf-8")

    glossary = load_glossary(glossary_path)

    assert isinstance(glossary, Glossary)
    assert glossary.apply("OBSERVER") == "OBSERVER"


def test_load_glossary_missing_file_has_clear_error(tmp_path):
    with pytest.raises(GlossaryError, match="Glossary file not found"):
        load_glossary(tmp_path / "missing.json")
