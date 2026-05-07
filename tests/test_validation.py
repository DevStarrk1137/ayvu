from pathlib import Path

from ayvu.validation import validate_output_epub


def test_validate_output_epub_accepts_minimal_generated_epub(minimal_epub_path: Path):
    result = validate_output_epub(minimal_epub_path)

    assert result.ok
    assert result.warnings == []
    assert result.document_count >= 2
