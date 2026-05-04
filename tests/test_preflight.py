import pytest

from ayvu.cache import CacheKey, TranslationCache
from ayvu.domain import LanguagePair
from ayvu.preflight import PreflightError, run_translation_preflight
from ayvu.translator import TranslatorError


class FakeTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def translate(self, text: str, source: str, target: str) -> str:
        self.calls.append((text, source, target))
        return text


class FailingTranslator:
    def translate(self, _text: str, _source: str, _target: str) -> str:
        raise TranslatorError("language pair is not available")


def raise_bad_epub(_path: object) -> object:
    raise ValueError("bad epub")


def test_preflight_checks_cache_epub_and_translator(monkeypatch, tmp_path):
    translator = FakeTranslator()
    cache_path = tmp_path / "cache.sqlite"
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: translator)
    monkeypatch.setattr("ayvu.preflight.inspect_epub", lambda _path: object())

    result = run_translation_preflight(
        epub_path=tmp_path / "book.epub",
        cache_path=cache_path,
        glossary_path=None,
        translator_name="libretranslate",
        url="http://localhost:5000",
        timeout=1.0,
        retries=0,
        language_pair=LanguagePair(source="en", target="pt"),
        dry_run=False,
    )

    probe_key = CacheKey(
        text="__ayvu_cache_write_check__",
        language_pair=LanguagePair(source="ayvu", target="ayvu"),
    )
    with TranslationCache(cache_path) as cache:
        assert cache.get(probe_key) is None
    assert result.translator is translator
    assert translator.calls == [("Hello world", "en", "pt")]


def test_preflight_dry_run_skips_translator_probe(monkeypatch, tmp_path):
    translator = FakeTranslator()
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: translator)
    monkeypatch.setattr("ayvu.preflight.inspect_epub", lambda _path: object())

    run_translation_preflight(
        epub_path=tmp_path / "book.epub",
        cache_path=tmp_path / "cache.sqlite",
        glossary_path=None,
        translator_name="libretranslate",
        url="http://localhost:5000",
        timeout=1.0,
        retries=0,
        language_pair=LanguagePair(source="en", target="pt"),
        dry_run=True,
    )

    assert translator.calls == []


def test_preflight_rejects_blank_language_pair(tmp_path):
    with pytest.raises(PreflightError) as error:
        run_translation_preflight(
            epub_path=tmp_path / "book.epub",
            cache_path=tmp_path / "cache.sqlite",
            glossary_path=None,
            translator_name="libretranslate",
            url="http://localhost:5000",
            timeout=1.0,
            retries=0,
            language_pair=LanguagePair(source="en", target=" "),
            dry_run=True,
        )

    assert "Language pair check failed" in str(error.value)
    assert "--source and --target" in error.value.next_step


def test_preflight_reports_translator_probe_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: FailingTranslator())
    monkeypatch.setattr("ayvu.preflight.inspect_epub", lambda _path: object())

    with pytest.raises(PreflightError) as error:
        run_translation_preflight(
            epub_path=tmp_path / "book.epub",
            cache_path=tmp_path / "cache.sqlite",
            glossary_path=None,
            translator_name="libretranslate",
            url="http://localhost:5000",
            timeout=1.0,
            retries=0,
            language_pair=LanguagePair(source="en", target="pt"),
            dry_run=False,
        )

    assert "Translator check failed" in str(error.value)
    assert "language pair is available" in error.value.next_step


def test_preflight_reports_epub_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: FakeTranslator())
    monkeypatch.setattr("ayvu.preflight.inspect_epub", raise_bad_epub)

    with pytest.raises(PreflightError) as error:
        run_translation_preflight(
            epub_path=tmp_path / "book.epub",
            cache_path=tmp_path / "cache.sqlite",
            glossary_path=None,
            translator_name="libretranslate",
            url="http://localhost:5000",
            timeout=1.0,
            retries=0,
            language_pair=LanguagePair(source="en", target="pt"),
            dry_run=False,
        )

    assert "EPUB check failed" in str(error.value)
    assert "valid readable EPUB" in error.value.next_step
