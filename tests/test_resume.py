import json
from pathlib import Path

import pytest

from ayvu.domain import LanguagePair, TranslationOptions
from ayvu.resume import (
    COMPLETED_STATUS,
    RESUME_STATE_VERSION,
    RUNNING_STATUS,
    ResumeStateError,
    ResumeStateStore,
    TranslationResumeState,
)


def make_state(tmp_path: Path) -> TranslationResumeState:
    return TranslationResumeState.create(
        input_path=tmp_path / "Original" / "book.epub",
        output_path=tmp_path / "Traduzidos" / "book-pt.epub",
        cache_path=tmp_path / "cache.sqlite",
        translator_name="libretranslate",
        url="http://localhost:5000",
        glossary_path=tmp_path / "glossary.json",
        options=TranslationOptions(
            language_pair=LanguagePair(source="en", target="pt"),
            dry_run=False,
            fail_fast=True,
            chunk_limit=1200,
        ),
        overwrite=True,
        timeout=9.5,
        retries=3,
    )


def test_resume_state_round_trip(tmp_path):
    store = ResumeStateStore(tmp_path / "Processando")
    state = make_state(tmp_path)

    path = store.save(state)
    loaded = store.load(path)

    assert path.name == "book-pt.ayvu-state.json"
    assert loaded == state
    assert loaded.status == RUNNING_STATUS
    assert loaded.version == RESUME_STATE_VERSION
    assert loaded.source == "en"
    assert loaded.target == "pt"
    assert loaded.fail_fast
    assert loaded.overwrite
    assert loaded.chunk_limit == 1200
    assert loaded.timeout == 9.5
    assert loaded.retries == 3


def test_resume_state_can_be_marked_completed(tmp_path):
    state = make_state(tmp_path)

    completed = state.mark_completed()

    assert state.status == RUNNING_STATUS
    assert completed.status == COMPLETED_STATUS
    assert completed.created_at == state.created_at


def test_resume_state_load_reports_invalid_json(tmp_path):
    path = tmp_path / "bad.ayvu-state.json"
    path.write_text("{bad", encoding="utf-8")
    store = ResumeStateStore(tmp_path)

    with pytest.raises(ResumeStateError) as error:
        store.load(path)

    assert "Resume state file is not valid JSON" in str(error.value)
    assert str(path) in str(error.value)


def test_resume_state_load_reports_missing_required_field(tmp_path):
    path = tmp_path / "missing.ayvu-state.json"
    data = make_state(tmp_path).to_dict()
    data.pop("cache_path")
    path.write_text(json.dumps(data), encoding="utf-8")
    store = ResumeStateStore(tmp_path)

    with pytest.raises(ResumeStateError) as error:
        store.load(path)

    assert "Invalid resume state file" in str(error.value)
    assert "cache_path is required" in str(error.value)
