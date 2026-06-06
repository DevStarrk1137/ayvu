from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


class ReviewImportError(Exception):
    """Raised when a review CSV cannot be read or is malformed."""


# Columns the import needs to locate and apply a reviewed segment. Other export
# columns (chapter index/name, languages, from_cache) are optional here so that
# hand-edited review files stay usable as long as these are present.
REQUIRED_REVIEW_COLUMNS = ("segment_id", "document_path", "original", "translated")


@dataclass(frozen=True)
class ReviewRow:
    segment_id: str
    document_path: str
    original: str
    translated: str
    segment_kind: str = ""
    source_language: str = ""
    target_language: str = ""


@dataclass(frozen=True)
class ReviewImportData:
    rows: tuple[ReviewRow, ...]
    duplicate_ids: tuple[str, ...]

    @property
    def source_language(self) -> str:
        return next((row.source_language for row in self.rows if row.source_language), "")

    @property
    def target_language(self) -> str:
        return next((row.target_language for row in self.rows if row.target_language), "")


def read_review_csv(path: str | Path) -> ReviewImportData:
    source = Path(path)
    try:
        with source.open(encoding="utf-8", newline="") as input_file:
            reader = csv.DictReader(input_file)
            _check_columns(reader.fieldnames)
            rows = tuple(_row_from_record(record) for record in reader)
    except FileNotFoundError as exc:
        raise ReviewImportError(f"Review file not found: {source}") from exc
    except UnicodeDecodeError as exc:
        raise ReviewImportError(f"Review file is not valid UTF-8: {source}") from exc
    except OSError as exc:
        raise ReviewImportError(f"Could not read review file: {source}") from exc

    return ReviewImportData(rows=rows, duplicate_ids=_duplicate_ids(rows))


def _check_columns(fieldnames: list[str] | None) -> None:
    if not fieldnames:
        raise ReviewImportError("Review file has no header row.")
    missing = [column for column in REQUIRED_REVIEW_COLUMNS if column not in fieldnames]
    if missing:
        raise ReviewImportError("Review file is missing required columns: " + ", ".join(missing))


def _row_from_record(record: dict[str, str]) -> ReviewRow:
    return ReviewRow(
        segment_id=(record.get("segment_id") or "").strip(),
        document_path=(record.get("document_path") or "").strip(),
        original=record.get("original") or "",
        translated=record.get("translated") or "",
        segment_kind=(record.get("segment_kind") or "").strip(),
        source_language=(record.get("source_language") or "").strip(),
        target_language=(record.get("target_language") or "").strip(),
    )


def _duplicate_ids(rows: tuple[ReviewRow, ...]) -> tuple[str, ...]:
    counts = Counter(row.segment_id for row in rows if row.segment_id)
    return tuple(sorted(segment_id for segment_id, count in counts.items() if count > 1))
