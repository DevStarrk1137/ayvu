from pathlib import Path

import pytest
from typer.testing import CliRunner

from ayvu.cli import TextProgressCounters, app
from ayvu.domain import LanguagePair, OutputPlan, TranslationOptions


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


def test_text_progress_counters_track_known_statuses():
    counters = TextProgressCounters()

    counters.record("translated")
    counters.record("cache")
    counters.record("dry_run")
    counters.record("error")

    assert counters.processed == 4
    assert counters.new_count(dry_run=False) == 1
    assert counters.new_count(dry_run=True) == 1
    assert counters.cache == 1
    assert counters.error == 1


def test_text_progress_counters_reject_unknown_status():
    counters = TextProgressCounters()

    with pytest.raises(ValueError, match="Unknown text progress status"):
        counters.record("unknown")


def test_translate_command_has_clear_error_for_unknown_translator(tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"not a real epub")

    result = runner.invoke(app, ["translate", str(epub_path), "--translator", "unknown", "--dry-run"])

    assert result.exit_code == 1
    assert "Translator error:" in result.output
    assert "Unsupported translator: unknown" in result.output
    assert "Use --translator libretranslate." in result.output
    assert "Traceback" not in result.output
