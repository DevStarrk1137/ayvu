import pytest

from ayvu.cache import CacheKey, TranslationCache
from ayvu.domain import LanguagePair
from ayvu.preflight import PreflightError, run_translation_preflight
from ayvu.translator import RoutedTranslator, TranslatorError, TranslatorLanguage


class FakeTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def translate(self, text: str, source: str, target: str) -> str:
        self.calls.append((text, source, target))
        return text


class FailingTranslator:
    def translate(self, _text: str, _source: str, _target: str) -> str:
        raise TranslatorError("language pair is not available")


class TranslatorWithLanguages:
    def __init__(self, languages: tuple[TranslatorLanguage, ...]) -> None:
        self._languages = languages
        self.translate_calls: list[tuple[str, str, str]] = []
        self.list_calls = 0

    def translate(self, text: str, source: str, target: str) -> str:
        self.translate_calls.append((text, source, target))
        return text

    def list_languages(self) -> tuple[TranslatorLanguage, ...]:
        self.list_calls += 1
        return self._languages


class TranslatorWithFailingLanguages:
    def translate(self, text: str, _source: str, _target: str) -> str:
        return text

    def list_languages(self) -> tuple[TranslatorLanguage, ...]:
        raise TranslatorError("connection refused")


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
    assert result.route is not None and result.route.is_direct


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


def test_preflight_passes_execution_controls_to_translator_factory(monkeypatch, tmp_path):
    translator = FakeTranslator()
    calls: dict[str, object] = {}

    def fake_create_translator(*args: object, **kwargs: object) -> FakeTranslator:
        calls["args"] = args
        calls["kwargs"] = kwargs
        return translator

    monkeypatch.setattr("ayvu.preflight.create_translator", fake_create_translator)
    monkeypatch.setattr("ayvu.preflight.inspect_epub", lambda _path: object())

    run_translation_preflight(
        epub_path=tmp_path / "book.epub",
        cache_path=tmp_path / "cache.sqlite",
        glossary_path=None,
        translator_name="libretranslate",
        url="http://localhost:5000",
        timeout=1.0,
        retries=0,
        requests_per_second=3.5,
        retry_backoff=0.25,
        retry_backoff_max=2.0,
        language_pair=LanguagePair(source="en", target="pt"),
        dry_run=True,
    )

    assert calls["args"] == ("libretranslate",)
    assert calls["kwargs"] == {
        "url": "http://localhost:5000",
        "timeout": 1.0,
        "retries": 0,
        "requests_per_second": 3.5,
        "retry_backoff": 0.25,
        "retry_backoff_max": 2.0,
    }


def test_preflight_cache_only_skips_route_resolution(monkeypatch, tmp_path):
    translator = TranslatorWithLanguages(
        (TranslatorLanguage(code="en", name="English", targets=("pt",)),)
    )
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: translator)
    monkeypatch.setattr("ayvu.preflight.inspect_epub", lambda _path: object())

    result = run_translation_preflight(
        epub_path=tmp_path / "book.epub",
        cache_path=tmp_path / "cache.sqlite",
        glossary_path=None,
        translator_name="libretranslate",
        url="http://localhost:5000",
        timeout=1.0,
        retries=0,
        language_pair=LanguagePair(source="en", target="pt"),
        dry_run=False,
        cache_only=True,
    )

    assert result.route is None
    assert result.translator is translator
    assert translator.translate_calls == []
    assert translator.list_calls == 0


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

    assert error.value.summary == "O par de idiomas informado não é válido."
    assert "--source e --target" in error.value.next_step


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

    assert error.value.summary == "O tradutor não respondeu."
    assert "language pair is not available" in error.value.detail
    assert "par de idiomas está disponível" in error.value.next_step


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

    assert error.value.summary == "Não foi possível ler o EPUB informado."
    assert "bad epub" in error.value.detail
    assert "EPUB válido e legível" in error.value.next_step


def test_preflight_uses_languages_to_resolve_direct_route(monkeypatch, tmp_path):
    languages = (
        TranslatorLanguage(code="en", name="English", targets=("pt",)),
        TranslatorLanguage(code="pt", name="Portuguese", targets=("en",)),
    )
    translator = TranslatorWithLanguages(languages)
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: translator)
    monkeypatch.setattr("ayvu.preflight.inspect_epub", lambda _path: object())

    result = run_translation_preflight(
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

    assert translator.list_calls == 1
    assert translator.translate_calls == []
    assert result.route is not None and result.route.is_direct
    assert result.translator is translator


def test_preflight_wraps_translator_when_intermediate_route_is_needed(monkeypatch, tmp_path):
    languages = (
        TranslatorLanguage(code="fr", name="French", targets=("en",)),
        TranslatorLanguage(code="en", name="English", targets=("pt",)),
        TranslatorLanguage(code="pt", name="Portuguese", targets=("en",)),
    )
    translator = TranslatorWithLanguages(languages)
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: translator)
    monkeypatch.setattr("ayvu.preflight.inspect_epub", lambda _path: object())

    result = run_translation_preflight(
        epub_path=tmp_path / "book.epub",
        cache_path=tmp_path / "cache.sqlite",
        glossary_path=None,
        translator_name="libretranslate",
        url="http://localhost:5000",
        timeout=1.0,
        retries=0,
        language_pair=LanguagePair(source="fr", target="pt"),
        dry_run=False,
    )

    assert isinstance(result.translator, RoutedTranslator)
    assert result.route is not None
    assert result.route.intermediate == "en"


def test_preflight_reports_missing_route_with_clear_message(monkeypatch, tmp_path):
    languages = (
        TranslatorLanguage(code="fr", name="French", targets=("de",)),
        TranslatorLanguage(code="pt", name="Portuguese", targets=()),
    )
    translator = TranslatorWithLanguages(languages)
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: translator)
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
            language_pair=LanguagePair(source="fr", target="pt"),
            dry_run=False,
        )

    assert error.value.summary == "O par de idiomas não está disponível no tradutor."
    assert "ayvu languages" in error.value.next_step


def test_preflight_reports_translator_unreachable_when_list_languages_fails(monkeypatch, tmp_path):
    translator = TranslatorWithFailingLanguages()
    monkeypatch.setattr("ayvu.preflight.create_translator", lambda *_args, **_kwargs: translator)
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

    assert error.value.summary == "O tradutor não respondeu."
    assert "connection refused" in error.value.detail
