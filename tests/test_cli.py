from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from ayvu.cli import (
    DEFAULT_PREVIEW_DOCUMENT_LIMIT,
    _offer_markdown_report,
    _render_markdown_report,
    _save_markdown_report,
    app,
)
from ayvu.domain import LanguagePair, OutputPlan, TranslationOptions, UserMode
from ayvu.epub_io import TranslationReport
from ayvu.preflight import PreflightError
from ayvu.resume import COMPLETED_STATUS, ResumeStateStore, TranslationResumeState
from ayvu.translator import TranslatorError, TranslatorLanguage
from ayvu.validation import ValidationResult


runner = CliRunner()


def test_output_plan_keeps_explicit_output():
    output = Path("traduzidos/livro-final.epub")
    language_pair = LanguagePair(source="en", target="pt")

    plan = OutputPlan.for_translation(Path("livro.epub"), output, language_pair)

    assert plan.path == output
    assert plan.explicit_output


def test_output_plan_uses_target_suffix_in_default_output_dir():
    language_pair = LanguagePair(source="en", target="pt-BR")
    default_dir = Path("Documentos/Livros/Traduzidos")

    plan = OutputPlan.for_translation(
        Path("books/livro.epub"),
        None,
        language_pair,
        default_dir=default_dir,
    )

    assert plan.path == Path("Documentos/Livros/Traduzidos/livro-pt-BR.epub")
    assert not plan.explicit_output


def test_output_plan_uses_translated_suffix_when_target_is_blank():
    language_pair = LanguagePair(source="en", target=" ")
    default_dir = Path("Documentos/Livros/Traduzidos")

    plan = OutputPlan.for_translation(
        Path("books/livro.epub"),
        None,
        language_pair,
        default_dir=default_dir,
    )

    assert plan.path == Path("Documentos/Livros/Traduzidos/livro-translated.epub")


def test_output_plan_dry_run_does_not_block_existing_output(tmp_path):
    output = tmp_path / "livro-pt.epub"
    output.write_text("already here", encoding="utf-8")

    plan = OutputPlan(path=output, dry_run=True)

    assert not plan.blocks_existing_file(overwrite=False)


def test_output_plan_uses_preview_suffix_in_default_preview_dir():
    default_dir = Path("Documentos/Livros/Preview")

    plan = OutputPlan.for_preview(Path("books/livro.epub"), default_dir=default_dir)

    assert plan.path == Path("Documentos/Livros/Preview/livro-preview.epub")
    assert not plan.explicit_output


def test_translation_options_exposes_language_pair_values():
    language_pair = LanguagePair(source="en", target="pt")

    options = TranslationOptions(language_pair=language_pair)

    assert options.source == "en"
    assert options.target == "pt"


def test_translate_command_has_clear_error_for_unknown_translator(tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"not a real epub")

    result = runner.invoke(app, ["translate", str(epub_path), "--translator", "unknown", "--dry-run"])

    assert result.exit_code == 1
    assert "Environment check failed:" in result.output
    assert "Translator check failed:" in result.output
    assert "Unsupported translator:" in result.output
    assert "unknown" in result.output
    assert "Use --translator libretranslate." in result.output
    assert "Traceback" not in result.output


def test_languages_command_lists_translator_languages(monkeypatch):
    calls: dict[str, object] = {}

    class FakeLanguageTranslator:
        def __init__(self, url: str, timeout: float, retries: int) -> None:
            calls["url"] = url
            calls["timeout"] = timeout
            calls["retries"] = retries

        def list_languages(self) -> tuple[TranslatorLanguage, ...]:
            return (
                TranslatorLanguage(code="pt", name="Portuguese", targets=("en", "es")),
                TranslatorLanguage(code="en", name="English", targets=("pt",)),
            )

    monkeypatch.setattr("ayvu.cli.LibreTranslateTranslator", FakeLanguageTranslator)

    result = runner.invoke(app, ["languages", "--url", "http://localhost:5000", "--timeout", "2", "--retries", "0"])

    assert result.exit_code == 0
    assert calls == {"url": "http://localhost:5000", "timeout": 2.0, "retries": 0}
    assert "LibreTranslate languages" in result.output
    assert "Portuguese" in result.output
    assert "pt" in result.output
    assert "installed" in result.output
    assert "en, es" in result.output


def test_languages_command_reports_failure_without_traceback(monkeypatch):
    class FailingLanguageTranslator:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def list_languages(self) -> tuple[TranslatorLanguage, ...]:
            raise TranslatorError("server unavailable")

    monkeypatch.setattr("ayvu.cli.LibreTranslateTranslator", FailingLanguageTranslator)

    result = runner.invoke(app, ["languages"])

    assert result.exit_code == 1
    assert "Language list failed:" in result.output
    assert "server unavailable" in result.output
    assert "Start LibreTranslate" in result.output
    assert "Traceback" not in result.output


def test_root_command_shows_processing_translation_state(tmp_path, monkeypatch):
    processing_dir = tmp_path / "Processando"
    state = _resume_state(tmp_path)
    ResumeStateStore(processing_dir).save(state)
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)

    result = runner.invoke(app, [], input="n\n0\n")

    assert result.exit_code == 0
    assert "Translations in progress were found." in result.output
    assert "Processing translations" in result.output
    assert "book.epub" in result.output
    assert "book-pt.epub" in result.output
    assert "cache.sqlite" in result.output
    assert "Continue detected translation?" in result.output
    assert "Detected translation was not resumed." in result.output
    assert "Choose an option" in result.output
    assert "Generate preview" in result.output
    assert "Canceled." in result.output


def test_root_command_in_developer_mode_skips_guided_prompts(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake")
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: tmp_path / "missing")

    result = runner.invoke(app, ["--mode", "developer", "--preview", str(epub_path)])

    assert "Generate a translation preview?" not in result.output
    assert "Environment check failed:" in result.output


def test_translate_command_in_developer_mode_skips_confirmations(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake")
    monkeypatch.setattr("ayvu.cli.default_translated_books_dir", lambda: tmp_path / "Traduzidos")

    monkeypatch.setattr(
        "ayvu.cli.run_translation_preflight",
        lambda **_kwargs: (_ for _ in ()).throw(PreflightError("failed", "next")),
    )

    result = runner.invoke(app, ["translate", str(epub_path)])

    assert result.exit_code == 1
    assert "Default output folder:" not in result.output
    assert "Keep this output location?" not in result.output
    assert "Environment check failed:" in result.output


def test_root_command_resumes_detected_translation_when_confirmed(tmp_path, monkeypatch):
    processing_dir = tmp_path / "Processando"
    state = _resume_state(tmp_path)
    report = TranslationReport(
        chapters_processed=1,
        texts_translated=2,
        output_path=state.output_path,
        input_path=state.input_path,
        detected_language=state.source,
        target_language=state.target,
    )
    calls: dict[str, object] = {}
    ResumeStateStore(processing_dir).save(state)

    def fake_preflight(**kwargs: object) -> object:
        calls["preflight"] = kwargs
        return SimpleNamespace(translator=object(), glossary=None)

    def fake_translate(*_args: object, **kwargs: object) -> TranslationReport:
        calls["translation_options"] = kwargs["options"]
        return report

    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)
    monkeypatch.setattr("ayvu.cli.run_translation_preflight", fake_preflight)
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", fake_translate)
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path, on_progress=None: ValidationResult(ok=True, document_count=1))
    monkeypatch.setattr("ayvu.cli._offer_markdown_report", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, [], input="y\n")

    preflight = calls["preflight"]
    options = calls["translation_options"]
    saved_state = ResumeStateStore(processing_dir).load(processing_dir / "book-pt.ayvu-state.json")
    assert result.exit_code == 0
    assert "Continue detected translation?" in result.output
    assert "Resuming translation:" in result.output
    assert "Translation report" in result.output
    assert "Usage:" not in result.output
    assert preflight["epub_path"] == state.input_path
    assert preflight["cache_path"] == state.cache_path
    assert preflight["glossary_path"] == state.glossary_path
    assert preflight["translator_name"] == state.translator_name
    assert preflight["url"] == state.url
    assert preflight["timeout"] == state.timeout
    assert preflight["retries"] == state.retries
    assert options.source == state.source
    assert options.target == state.target
    assert options.chunk_limit == state.chunk_limit
    assert saved_state.status == COMPLETED_STATUS


def test_root_command_reports_resume_failure_without_traceback(tmp_path, monkeypatch):
    processing_dir = tmp_path / "Processando"
    ResumeStateStore(processing_dir).save(_resume_state(tmp_path))
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)
    monkeypatch.setattr(
        "ayvu.cli.run_translation_preflight",
        lambda **_kwargs: (_ for _ in ()).throw(
            PreflightError("EPUB check failed: missing file", "Choose a valid EPUB.")
        ),
    )

    result = runner.invoke(app, [], input="y\n")

    assert result.exit_code == 1
    assert "Continue detected translation?" in result.output
    assert "Environment check failed:" in result.output
    assert "EPUB check failed: missing file" in result.output
    assert "Could not resume detected translation." in result.output
    assert "Traceback" not in result.output


def test_root_command_reports_invalid_processing_state(tmp_path, monkeypatch):
    processing_dir = tmp_path / "Processando"
    processing_dir.mkdir()
    (processing_dir / "bad.ayvu-state.json").write_text("{bad", encoding="utf-8")
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)

    result = runner.invoke(app, [], input="n\n")

    assert result.exit_code == 0
    assert "Invalid processing state files were found." in result.output
    assert "bad.ayvu-state.json" in result.output
    assert "not valid JSON" in result.output
    assert "Restart the translation" in result.output
    assert "Choose an option" in result.output
    assert "Generate preview" in result.output
    assert "Usage:" in result.output


def test_root_command_without_processing_state_has_no_processing_noise(tmp_path, monkeypatch):
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: tmp_path / "missing")

    result = runner.invoke(app, [], input="0\n")

    assert result.exit_code == 0
    assert "Choose an option" in result.output
    assert "Generate preview" in result.output
    assert "Canceled." in result.output
    assert "Translations in progress were found." not in result.output
    assert "Invalid processing state files were found." not in result.output


def test_root_command_generates_guided_preview_when_confirmed(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    preview_dir = tmp_path / "Preview"
    epub_path.write_bytes(b"fake epub")
    calls: dict[str, object] = {}

    def fake_translate(input_path: Path, output_path: Path, **kwargs: object) -> TranslationReport:
        calls["input_path"] = input_path
        calls["output_path"] = output_path
        calls["options"] = kwargs["options"]
        return TranslationReport(output_path=output_path, input_path=input_path, target_language="pt")

    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: tmp_path / "missing")
    monkeypatch.setattr("ayvu.cli.default_preview_books_dir", lambda: preview_dir)
    monkeypatch.setattr(
        "ayvu.cli.run_translation_preflight",
        lambda **_kwargs: SimpleNamespace(translator=object(), glossary=None),
    )
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", fake_translate)
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path, on_progress=None: ValidationResult(ok=True, document_count=1))

    result = runner.invoke(app, [], input=f"2\n{epub_path}\ny\n")

    options = calls["options"]
    assert result.exit_code == 0
    assert "Choose an option" in result.output
    assert "Generate preview" in result.output
    assert "EPUB path" in result.output
    assert "Default target language:" in result.output
    assert "Use default target language?" in result.output
    assert "Preview output folder:" in result.output
    assert "Preview EPUB name:" in result.output
    assert "Preview salvo em:" in result.output
    assert calls["input_path"] == epub_path
    assert calls["output_path"] == preview_dir / "book-preview.epub"
    assert options.max_documents == DEFAULT_PREVIEW_DOCUMENT_LIMIT
    assert "Usage:" not in result.output


def test_root_command_allows_guided_preview_target_from_languages(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    preview_dir = tmp_path / "Preview"
    epub_path.write_bytes(b"fake epub")
    calls: dict[str, object] = {}

    class FakeLanguageTranslator:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def list_languages(self) -> tuple[TranslatorLanguage, ...]:
            return (
                TranslatorLanguage(code="pt", name="Portuguese", targets=("en",)),
                TranslatorLanguage(code="es", name="Spanish", targets=("en",)),
            )

    def fake_preflight(**kwargs: object) -> object:
        calls["target"] = kwargs["language_pair"].target
        return SimpleNamespace(translator=object(), glossary=None)

    def fake_translate(_input_path: Path, _output_path: Path, **kwargs: object) -> TranslationReport:
        calls["options"] = kwargs["options"]
        return TranslationReport(output_path=_output_path, input_path=_input_path, target_language="es")

    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: tmp_path / "missing")
    monkeypatch.setattr("ayvu.cli.default_preview_books_dir", lambda: preview_dir)
    monkeypatch.setattr("ayvu.cli.LibreTranslateTranslator", FakeLanguageTranslator)
    monkeypatch.setattr("ayvu.cli.run_translation_preflight", fake_preflight)
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", fake_translate)
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path, on_progress=None: ValidationResult(ok=True, document_count=1))

    result = runner.invoke(app, [], input=f"2\n{epub_path}\nn\nes\n")

    options = calls["options"]
    assert result.exit_code == 0
    assert "Default target language:" in result.output
    assert "LibreTranslate languages" in result.output
    assert "Portuguese" in result.output
    assert "Spanish" in result.output
    assert "Target language code" in result.output
    assert calls["target"] == "es"
    assert options.target == "es"


def test_root_command_starts_guided_translation(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    output_dir = tmp_path / "Traduzidos"
    processing_dir = tmp_path / "Processando"
    epub_path.write_bytes(b"fake epub")
    calls: dict[str, object] = {}

    def fake_translate(input_path: Path, output_path: Path, **kwargs: object) -> TranslationReport:
        calls["input_path"] = input_path
        calls["output_path"] = output_path
        calls["options"] = kwargs["options"]
        return TranslationReport(output_path=output_path, input_path=input_path, target_language="pt")

    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)
    monkeypatch.setattr("ayvu.cli.default_translated_books_dir", lambda: output_dir)
    monkeypatch.setattr(
        "ayvu.cli.run_translation_preflight",
        lambda **_kwargs: SimpleNamespace(translator=object(), glossary=None),
    )
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", fake_translate)
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path, on_progress=None: ValidationResult(ok=True, document_count=1))
    monkeypatch.setattr("ayvu.cli._offer_markdown_report", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, [], input=f"1\n{epub_path}\ny\ny\n")

    options = calls["options"]
    assert result.exit_code == 0
    assert "Translate a book" in result.output
    assert "EPUB path" in result.output
    assert "Default target language:" in result.output
    assert "Default output folder:" in result.output
    assert calls["input_path"] == epub_path
    assert calls["output_path"] == output_dir / "book-pt.epub"
    assert options.target == "pt"


def test_root_command_shows_guided_library_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: tmp_path / "missing")

    result = runner.invoke(app, [], input="3\n")

    assert result.exit_code == 0
    assert "Open library" in result.output
    assert "Library is not available yet." in result.output
    assert "Use the command help" in result.output


def test_root_command_shows_guided_settings_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: tmp_path / "missing")

    result = runner.invoke(app, [], input="4\n")

    assert result.exit_code == 0
    assert "Settings" in result.output
    assert "Settings menu is not available yet." in result.output
    assert "Use the command help" in result.output


def test_root_command_can_show_help_from_guided_menu(tmp_path, monkeypatch):
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: tmp_path / "missing")

    result = runner.invoke(app, [], input="5\n")

    assert result.exit_code == 0
    assert "Show command help" in result.output
    assert "Usage:" in result.output
    assert "translate" in result.output


def test_preview_option_generates_preview_with_default_settings(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    preview_dir = tmp_path / "Preview"
    epub_path.write_bytes(b"fake epub")
    calls: dict[str, object] = {}

    def fake_preflight(**kwargs: object) -> object:
        calls["preflight"] = kwargs
        return SimpleNamespace(translator=object(), glossary=None)

    def fake_translate(input_path: Path, output_path: Path, **kwargs: object) -> TranslationReport:
        calls["input_path"] = input_path
        calls["output_path"] = output_path
        calls["options"] = kwargs["options"]
        return TranslationReport(output_path=output_path, input_path=input_path, target_language="pt")

    monkeypatch.setattr("ayvu.cli.default_preview_books_dir", lambda: preview_dir)
    monkeypatch.setattr("ayvu.cli.run_translation_preflight", fake_preflight)
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", fake_translate)
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path, on_progress=None: ValidationResult(ok=True, document_count=1))

    result = runner.invoke(app, ["--preview", str(epub_path)])

    preflight = calls["preflight"]
    options = calls["options"]
    assert result.exit_code == 0
    assert "Preview output folder:" in result.output
    assert str(preview_dir) in result.output
    assert "book-preview.epub" in result.output
    assert "Preview salvo em:" in result.output
    assert calls["input_path"] == epub_path
    assert calls["output_path"] == preview_dir / "book-preview.epub"
    assert preflight["epub_path"] == epub_path
    assert preflight["cache_path"] == Path(".cache/traducoes.sqlite")
    assert preflight["translator_name"] == "libretranslate"
    assert preflight["url"] == "http://localhost:5000"
    assert options.source == "en"
    assert options.target == "pt"
    assert options.max_documents == DEFAULT_PREVIEW_DOCUMENT_LIMIT


def test_translate_command_stops_when_preflight_fails(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake epub")
    monkeypatch.setattr("ayvu.cli.default_translated_books_dir", lambda: tmp_path / "Traduzidos")

    def fail_preflight(**_kwargs: object) -> object:
        raise PreflightError("Cache check failed: no write permission", "Choose a writable cache path.")

    def fail_translate(*_args: object, **_kwargs: object) -> TranslationReport:
        raise AssertionError("translation should not start when preflight fails")

    monkeypatch.setattr("ayvu.cli.run_translation_preflight", fail_preflight)
    monkeypatch.setattr("ayvu.cli.translate_epub", fail_translate)

    result = runner.invoke(app, ["--mode", "common", "translate", str(epub_path)], input="y\n")

    assert result.exit_code == 1
    assert "Default output folder:" in result.output
    assert "Keep this output location?" in result.output
    assert "Environment check failed:" in result.output
    assert "Cache check failed: no write permission" in result.output
    assert "Choose a writable cache path." in result.output
    assert "Traceback" not in result.output


def test_translate_command_confirms_default_output_location(tmp_path, monkeypatch):
    original_dir = tmp_path / "Original"
    epub_path = original_dir / "book.epub"
    output_dir = tmp_path / "Traduzidos"
    processing_dir = tmp_path / "Processando"
    epub_path.parent.mkdir()
    epub_path.write_bytes(b"fake epub")
    calls: dict[str, Path] = {}

    def fake_translate(input_path: Path, output_path: Path, **_kwargs: object) -> TranslationReport:
        calls["input_path"] = input_path
        calls["output_path"] = output_path
        return TranslationReport(
            output_path=output_path,
            input_path=input_path,
            detected_language="en",
            target_language="pt",
        )

    monkeypatch.setattr("ayvu.cli.default_translated_books_dir", lambda: output_dir)
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)
    monkeypatch.setattr(
        "ayvu.cli.run_translation_preflight",
        lambda **_kwargs: SimpleNamespace(translator=object(), glossary=None),
    )
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", fake_translate)
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path, on_progress=None: ValidationResult(ok=True, document_count=1))
    monkeypatch.setattr("ayvu.cli._offer_markdown_report", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["--mode", "common", "translate", str(epub_path)], input="y\n")

    output_path = output_dir / "book-pt.epub"
    state_path = processing_dir / "book-pt.ayvu-state.json"
    resume_state = ResumeStateStore(processing_dir).load(state_path)
    assert result.exit_code == 0
    assert "Default output folder:" in result.output
    assert str(output_dir) in result.output
    assert "Translated EPUB name:" in result.output
    assert "book-pt.epub" in result.output
    assert "Original EPUB stays in Original:" in result.output
    assert "Keep this output location?" in result.output
    assert calls["input_path"] == epub_path
    assert calls["output_path"] == output_path
    assert resume_state.output_path == output_path.resolve()


def test_translate_command_allows_custom_output_path_from_default_prompt(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    output_dir = tmp_path / "Traduzidos"
    custom_output = tmp_path / "Escolhidos" / "custom-name"
    processing_dir = tmp_path / "Processando"
    epub_path.write_bytes(b"fake epub")
    calls: dict[str, Path] = {}

    def fake_translate(_input_path: Path, output_path: Path, **_kwargs: object) -> TranslationReport:
        calls["output_path"] = output_path
        return TranslationReport(output_path=output_path, input_path=epub_path, target_language="pt")

    monkeypatch.setattr("ayvu.cli.default_translated_books_dir", lambda: output_dir)
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)
    monkeypatch.setattr(
        "ayvu.cli.run_translation_preflight",
        lambda **_kwargs: SimpleNamespace(translator=object(), glossary=None),
    )
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", fake_translate)
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path, on_progress=None: ValidationResult(ok=True, document_count=1))
    monkeypatch.setattr("ayvu.cli._offer_markdown_report", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["--mode", "common", "translate", str(epub_path)], input=f"n\n{custom_output}\n")

    output_path = custom_output.with_suffix(".epub")
    assert result.exit_code == 0
    assert "Keep this output location?" in result.output
    assert "Output EPUB path" in result.output
    assert calls["output_path"] == output_path


def test_translate_command_asks_before_overwriting_existing_output_and_cancels(tmp_path):
    epub_path = tmp_path / "book.epub"
    output_path = tmp_path / "book-pt.epub"
    epub_path.write_bytes(b"not a real epub")
    output_path.write_text("already here", encoding="utf-8")

    result = runner.invoke(app, ["--mode", "common", "translate", str(epub_path), "--output", str(output_path)], input="n\n")

    assert result.exit_code == 1
    assert "Output path:" in result.output
    assert str(output_path) in result.output
    assert "Translated EPUB already exists." in result.output
    assert "Overwrite existing translated EPUB?" in result.output
    assert "Canceled:" in result.output
    assert "existing output was not changed." in result.output
    assert output_path.read_text(encoding="utf-8") == "already here"
    assert "Traceback" not in result.output


def test_translate_command_continues_when_existing_output_is_confirmed(tmp_path):
    epub_path = tmp_path / "book.epub"
    output_path = tmp_path / "book-pt.epub"
    epub_path.write_bytes(b"not a real epub")
    output_path.write_text("already here", encoding="utf-8")

    result = runner.invoke(
        app,
        ["--mode", "common", "translate", str(epub_path), "--output", str(output_path), "--translator", "unknown"],
        input="y\n",
    )

    assert result.exit_code == 1
    assert "Overwrite existing translated EPUB?" in result.output
    assert "Environment check failed:" in result.output
    assert "Translator check failed:" in result.output
    assert "Unsupported translator:" in result.output
    assert "unknown" in result.output
    assert output_path.read_text(encoding="utf-8") == "already here"
    assert "Traceback" not in result.output


def test_render_markdown_report_includes_translation_context():
    report = TranslationReport(
        chapters_processed=2,
        texts_translated=3,
        texts_from_cache=1,
        errors=["chapter.xhtml: failed\nwhile translating"],
        output_path=Path("books/book-pt.epub"),
        input_path=Path("books/book.epub"),
        detected_language="en",
        target_language="pt",
    )

    markdown = _render_markdown_report(report, dry_run=False)

    assert "# Translation report" in markdown
    assert "- Original EPUB: books/book.epub" in markdown
    assert "- Detected language: en" in markdown
    assert "- Translated language: pt" in markdown
    assert "- Output: books/book-pt.epub" in markdown
    assert "- Chapters processed: 2" in markdown
    assert "- Texts translated: 3" in markdown
    assert "- Texts from cache: 1" in markdown
    assert "- Errors: 1" in markdown
    assert "- chapter.xhtml: failed while translating" in markdown


def test_save_markdown_report_uses_default_reports_dir_without_overwriting(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    report = TranslationReport(
        output_path=Path("book-pt.epub"),
        input_path=Path("book.epub"),
        target_language="pt",
    )
    monkeypatch.setattr("ayvu.cli._default_reports_dir", lambda: reports_dir)

    first_path = _save_markdown_report(report, dry_run=False)
    second_path = _save_markdown_report(report, dry_run=False)

    assert first_path == reports_dir / "book-pt-report.md"
    assert second_path == reports_dir / "book-pt-report-2.md"
    assert first_path.read_text(encoding="utf-8").startswith("# Translation report")
    assert second_path.read_text(encoding="utf-8").startswith("# Translation report")


def test_offer_markdown_report_does_not_save_when_declined(monkeypatch):
    saved = False

    def fake_save_report(_report: TranslationReport, _dry_run: bool) -> Path:
        nonlocal saved
        saved = True
        return Path("report.md")

    monkeypatch.setattr("ayvu.cli.typer.confirm", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("ayvu.cli._save_markdown_report", fake_save_report)

    _offer_markdown_report(TranslationReport(), dry_run=False, mode=UserMode.COMMON)

    assert not saved


def test_translate_command_offers_and_saves_markdown_report(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    output_path = tmp_path / "book-pt.epub"
    reports_dir = tmp_path / "reports"
    processing_dir = tmp_path / "processing"
    epub_path.write_bytes(b"fake epub")

    report = TranslationReport(
        chapters_processed=1,
        texts_translated=2,
        texts_from_cache=1,
        output_path=output_path,
        input_path=epub_path,
        detected_language="en",
        target_language="pt",
    )
    monkeypatch.setattr(
        "ayvu.cli.run_translation_preflight",
        lambda **_kwargs: SimpleNamespace(translator=object(), glossary=None),
    )
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", lambda *_args, **_kwargs: report)
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path, on_progress=None: ValidationResult(ok=True, document_count=1))
    monkeypatch.setattr("ayvu.cli._default_reports_dir", lambda: reports_dir)
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)

    result = runner.invoke(app, ["--mode", "common", "translate", str(epub_path), "--output", str(output_path)], input="y\n")

    report_path = reports_dir / "book-pt-report.md"
    state_path = processing_dir / "book-pt.ayvu-state.json"
    resume_state = ResumeStateStore(processing_dir).load(state_path)
    assert result.exit_code == 0
    assert "Translation report" in result.output
    assert "Original EPUB" in result.output
    assert "Detected language" in result.output
    assert "Save translation report as Markdown?" in result.output
    assert "Report saved to:" in result.output
    assert report_path.exists()
    assert "- Original EPUB: " in report_path.read_text(encoding="utf-8")
    assert str(epub_path) in report_path.read_text(encoding="utf-8")
    assert resume_state.status == COMPLETED_STATUS
    assert resume_state.input_path == epub_path.resolve()
    assert resume_state.output_path == output_path.resolve()
    assert resume_state.cache_path == Path(".cache/traducoes.sqlite").resolve()
    assert resume_state.source == "en"
    assert resume_state.target == "pt"
    assert resume_state.translator_name == "libretranslate"
    assert not resume_state.overwrite


def test_translate_command_handles_keyboard_interrupt_cleanly(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    output_path = tmp_path / "book-pt.epub"
    cache_path = tmp_path / "cache.sqlite"
    epub_path.write_bytes(b"fake epub")

    def interrupt_translation(*_args: object, **kwargs: object) -> TranslationReport:
        kwargs["on_chapter_start"](1, 3, "chapter-one.xhtml")
        kwargs["on_text_processed"]("translated")
        kwargs["on_text_processed"]("cache")
        kwargs["on_text_processed"]("error")
        kwargs["on_chapter_done"](1, 3, "chapter-one.xhtml", object())
        kwargs["on_chapter_start"](2, 3, "chapter-two.xhtml")
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "ayvu.cli.run_translation_preflight",
        lambda **_kwargs: SimpleNamespace(translator=object(), glossary=None),
    )
    monkeypatch.setattr("ayvu.cli.TranslationCache", lambda _path: FakeCache())
    monkeypatch.setattr("ayvu.cli.translate_epub", interrupt_translation)

    result = runner.invoke(
        app,
        [
            "translate",
            str(epub_path),
            "--output",
            str(output_path),
            "--cache",
            str(cache_path),
        ],
    )

    assert result.exit_code == 1
    assert "Translation interrupted by user." in result.output
    assert "Partial translation progress" in result.output
    assert "Chapters processed" in result.output
    assert "1/3" in result.output
    assert "Texts processed" in result.output
    assert "3" in result.output
    assert "Texts translated" in result.output
    assert "Texts from cache" in result.output
    assert "Text errors" in result.output
    assert "chapter-two.xhtml" in result.output
    assert "Cached translations saved before the interruption can be reused" in result.output
    assert str(cache_path) in result.output
    assert "Translated EPUB was not written:" in result.output
    assert "Traceback" not in result.output
    assert not output_path.exists()


class FakeCache:
    def __enter__(self) -> "FakeCache":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None


def _resume_state(tmp_path: Path) -> TranslationResumeState:
    return TranslationResumeState.create(
        input_path=tmp_path / "Original" / "book.epub",
        output_path=tmp_path / "Traduzidos" / "book-pt.epub",
        cache_path=tmp_path / "cache.sqlite",
        translator_name="libretranslate",
        url="http://localhost:5000",
        glossary_path=None,
        options=TranslationOptions(
            language_pair=LanguagePair(source="en", target="pt"),
            chunk_limit=1500,
        ),
        overwrite=False,
        timeout=30.0,
        retries=2,
    )
