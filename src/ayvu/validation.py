from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ebooklib import ITEM_DOCUMENT
from ebooklib import epub


@dataclass
class ValidationResult:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    document_count: int = 0


def validate_output_epub(path: str | Path) -> ValidationResult:
    epub_path = Path(path)
    warnings: list[str] = []

    if not epub_path.exists():
        return ValidationResult(ok=False, warnings=[f"Output file does not exist: {epub_path}"])

    try:
        book = epub.read_epub(str(epub_path))
    except Exception as exc:
        return ValidationResult(ok=False, warnings=[f"Could not open output EPUB with ebooklib: {exc}"])

    documents = list(book.get_items_of_type(ITEM_DOCUMENT))
    if not documents:
        warnings.append("Output EPUB does not contain XHTML/HTML document items")

    return ValidationResult(ok=not warnings, warnings=warnings, document_count=len(documents))

