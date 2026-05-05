from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from ayvu.cli import _offer_markdown_report, _render_markdown_report, _save_markdown_report, app
from ayvu.domain import LanguagePair, OutputPlan, TranslationOptions
from ayvu.epub_io import TranslationReport
from ayvu.preflight import PreflightError
from ayvu.resume import COMPLETED_STATUS, ResumeStateStore
from ayvu.validation import ValidationResult


runner = CliRunner()


def test_output_plan_keeps_explicit_output():
    output = Path("traduzidos/livro-final.epub")
    language_pair = LanguagePair(source="en", target="pt")

    plan = OutputPlan.for_translation(Path("livro.epub"), output, language_pair)

    assert plan.path == output


def test_output_plan_uses_target_suffix_next_to_input():
    language_pair = LanguagePair(source="en", target="pt-BR")

    plan = OutputPlan.for_translation(Path("books/livro.epub"), None, language_pair)

    assert plan.path == Path("books/livro-pt-BR.epub")


def test_output_plan_uses_translated_suffix_when_target_is_blank():
    language_pair = LanguagePair(source="en", target=" ")

    plan = OutputPlan.for_translation(Path("books/livro.epub"), None, language_pair)

    assert plan.path == Path("books/livro-translated.epub")


def test_output_plan_dry_run_does_not_block_existing_output(tmp_path):
    output = tmp_path / "livro-pt.epub"
    output.write_text("already here", encoding="utf-8")

    plan = OutputPlan(path=output, dry_run=True)

    assert not plan.blocks_existing_file(overwrite=False)


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


def test_translate_command_stops_when_preflight_fails(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake epub")

    def fail_preflight(**_kwargs: object) -> object:
        raise PreflightError("Cache check failed: no write permission", "Choose a writable cache path.")

    def fail_translate(*_args: object, **_kwargs: object) -> TranslationReport:
        raise AssertionError("translation should not start when preflight fails")

    monkeypatch.setattr("ayvu.cli.run_translation_preflight", fail_preflight)
    monkeypatch.setattr("ayvu.cli.translate_epub", fail_translate)

    result = runner.invoke(app, ["translate", str(epub_path)])

    assert result.exit_code == 1
    assert "Environment check failed:" in result.output
    assert "Cache check failed: no write permission" in result.output
    assert "Choose a writable cache path." in result.output
    assert "Traceback" not in result.output


def test_translate_command_asks_before_overwriting_existing_output_and_cancels(tmp_path):
    epub_path = tmp_path / "book.epub"
    output_path = tmp_path / "book-pt.epub"
    epub_path.write_bytes(b"not a real epub")
    output_path.write_text("already here", encoding="utf-8")

    result = runner.invoke(app, ["translate", str(epub_path), "--output", str(output_path)], input="n\n")

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
        ["translate", str(epub_path), "--output", str(output_path), "--translator", "unknown"],
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

    _offer_markdown_report(TranslationReport(), dry_run=False)

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
    monkeypatch.setattr("ayvu.cli.validate_output_epub", lambda _path: ValidationResult(ok=True, document_count=1))
    monkeypatch.setattr("ayvu.cli._default_reports_dir", lambda: reports_dir)
    monkeypatch.setattr("ayvu.cli.default_processing_dir", lambda: processing_dir)

    result = runner.invoke(app, ["translate", str(epub_path), "--output", str(output_path)], input="y\n")

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


class FakeCache:
    def __enter__(self) -> "FakeCache":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None
