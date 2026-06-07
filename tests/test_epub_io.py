import csv
import threading
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import pytest
from ebooklib import ITEM_DOCUMENT

from ayvu.cache import TranslationCache
from ayvu.domain import ChapterSelection, ChapterSelectionError, LanguagePair, TranslationOptions
from ayvu.epub_io import (
    EpubDocument,
    EpubReplacements,
    EpubStructureError,
    TranslationReport,
    _document_entries,
    _document_zip_path,
    _get_opf_archive_path,
    _navigation_document_entries,
    _opf_base_path,
    apply_reviewed_epub,
    detect_epub_language,
    extract_markdown,
    inspect_epub,
    normalize_language_code,
    resolve_chapter_selection,
    translate_epub,
)
from ayvu.glossary import GLOSSARY_RULE_FORBIDDEN, GLOSSARY_RULE_PRESERVE, Glossary, GlossaryEntry
from ayvu.review_export import REVIEW_CSV_COLUMNS, write_review_csv
from ayvu.review_import import ReviewImportData, ReviewRow, read_review_csv


class FakeBook:
    def __init__(self, names: list[str]) -> None:
        self._items = [FakeItem(name) for name in names]

    def get_items_of_type(self, item_type: int) -> list["FakeItem"]:
        assert item_type == ITEM_DOCUMENT
        return self._items


class FakeItem:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


class FakeZip:
    def read(self, filename: str) -> bytes:
        return f"original:{filename}".encode("utf-8")


class PrefixTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def translate(self, text: str, source: str, target: str) -> str:
        self.calls.append((text, source, target))
        return f"PT:{text}"


class RaisingTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def translate(self, text: str, source: str, target: str) -> str:
        self.calls.append((text, source, target))
        raise AssertionError("translator must not be called in cache-only mode")


def _read_navigation_document(epub_path: Path) -> str:
    opf_archive_path = _get_opf_archive_path(epub_path)
    with ZipFile(epub_path) as source_epub:
        documents = _navigation_document_entries(source_epub, opf_archive_path, _opf_base_path(opf_archive_path))
        assert documents
        return source_epub.read(documents[0].archive_path).decode("utf-8")


def test_document_zip_path_for_root_opf():
    assert _document_zip_path(PurePosixPath("."), "text/chapter.xhtml") == "text/chapter.xhtml"


def test_document_zip_path_for_nested_opf():
    assert _document_zip_path(PurePosixPath("OEBPS"), "text/chapter.xhtml") == "OEBPS/text/chapter.xhtml"


def test_document_entries_keep_item_names_and_archive_paths():
    book = FakeBook(["text/chapter.xhtml", "text/next.xhtml"])

    documents = _document_entries(book, PurePosixPath("OEBPS"))

    assert [document.name for document in documents] == ["text/chapter.xhtml", "text/next.xhtml"]
    assert [document.archive_path for document in documents] == [
        "OEBPS/text/chapter.xhtml",
        "OEBPS/text/next.xhtml",
    ]


def test_epub_replacements_return_replacement_or_original_content():
    replacements = EpubReplacements()
    replacements.add("chapter.xhtml", b"translated")

    assert replacements.content_for("chapter.xhtml", FakeZip()) == b"translated"
    assert replacements.content_for("style.css", FakeZip()) == b"original:style.css"


def test_epub_structure_error_formats_missing_document_message():
    document = EpubDocument(name="text/chapter.xhtml", archive_path="OEBPS/text/chapter.xhtml")

    error = EpubStructureError.missing_document(document)

    assert error.as_message() == (
        "text/chapter.xhtml: document not found in EPUB archive at OEBPS/text/chapter.xhtml"
    )


def test_epub_structure_error_formats_chapter_error_message():
    document = EpubDocument(name="text/chapter.xhtml", archive_path="OEBPS/text/chapter.xhtml")

    error = EpubStructureError.chapter_error(document, ValueError("bad html"))

    assert error.as_message() == "text/chapter.xhtml: bad html"


def test_translation_report_records_preformatted_errors():
    report = TranslationReport()

    report.record_error("text/chapter.xhtml: bad html")

    assert report.errors == ["text/chapter.xhtml: bad html"]


def test_inspect_epub_reads_minimal_generated_epub(minimal_epub_path: Path):
    info = inspect_epub(minimal_epub_path)

    assert info.path == minimal_epub_path
    assert info.title == "Minimal Test Book"
    assert info.authors == ["Ayvu Tests"]
    assert info.language == "en"
    assert info.document_count >= 2
    assert info.item_count >= 4


def test_extract_markdown_reads_visible_text_from_minimal_generated_epub(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_dir = tmp_path / "extracted"

    written = extract_markdown(minimal_epub_path, output_dir)

    extracted = "\n".join(path.read_text(encoding="utf-8") for path in written)
    assert written
    assert all(path.parent == output_dir for path in written)
    assert "Chapter One" in extracted
    assert "Hello reader. Visit" in extracted
    assert "chapter two" in extracted
    assert "Chapter Two" in extracted
    assert "Goodbye reader." in extracted


def test_translate_epub_translates_minimal_generated_epub_without_mutating_input(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-pt.epub"
    translator = PrefixTranslator()
    original_bytes = minimal_epub_path.read_bytes()
    options = TranslationOptions(language_pair=LanguagePair(source="en", target="pt"))

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
        )

    assert output_path.exists()
    assert minimal_epub_path.read_bytes() == original_bytes
    assert report.input_path == minimal_epub_path
    assert report.output_path == output_path
    assert report.detected_language == "en"
    assert report.target_language == "pt"
    assert report.chapters_processed >= 2
    assert report.texts_translated >= 4
    assert report.errors == []
    assert translator.calls

    with ZipFile(output_path) as output_epub:
        names = output_epub.namelist()
        chapter_name = next(name for name in names if name.endswith("text/chapter1.xhtml"))
        chapter = output_epub.read(chapter_name).decode("utf-8")
        assert any(name.endswith("images/pixel.png") for name in names)

    assert "PT:Hello reader. Visit" in chapter
    # The paragraph is translated as one block, keeping the inline link and its text.
    assert '<a href="chapter2.xhtml#answer">chapter two</a>' in chapter
    assert "../images/pixel.png" in chapter


def test_translate_epub_parallel_workers_preserves_order_and_review_segments(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-pt.epub"
    cache_path = tmp_path / "cache.sqlite"
    translator_ids: list[int] = []
    translator_lock = threading.Lock()
    review_segments = []
    statuses: list[str] = []
    options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        workers=2,
    )

    def translator_factory() -> PrefixTranslator:
        with translator_lock:
            translator_ids.append(len(translator_ids) + 1)
        return PrefixTranslator()

    with TranslationCache(cache_path) as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=PrefixTranslator(),
            cache=cache,
            options=options,
            review_segments=review_segments,
            on_text_processed=statuses.append,
            translator_factory=translator_factory,
            cache_factory=lambda: TranslationCache(cache_path),
        )

    assert output_path.exists()
    assert report.errors == []
    assert report.chapters_processed >= 2
    assert len(translator_ids) == report.chapters_processed
    assert statuses
    assert [segment.chapter_index for segment in review_segments] == sorted(
        segment.chapter_index for segment in review_segments
    )
    assert {segment.chapter_index for segment in review_segments} >= {1, 2}

    with ZipFile(output_path) as output_epub:
        names = output_epub.namelist()
        chapter_one_name = next(name for name in names if name.endswith("text/chapter1.xhtml"))
        chapter_two_name = next(name for name in names if name.endswith("text/chapter2.xhtml"))
        chapter_one = output_epub.read(chapter_one_name).decode("utf-8")
        chapter_two = output_epub.read(chapter_two_name).decode("utf-8")

    assert "PT:Hello reader. Visit" in chapter_one
    assert "PT:Goodbye reader." in chapter_two


def test_translate_epub_cache_only_reuses_cache_without_calling_translator(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    cache_path = tmp_path / "cache.sqlite"
    options = TranslationOptions(language_pair=LanguagePair(source="en", target="pt"))
    with TranslationCache(cache_path) as cache:
        first = translate_epub(
            minimal_epub_path,
            tmp_path / "first-pt.epub",
            translator=PrefixTranslator(),
            cache=cache,
            options=options,
        )

    output_path = tmp_path / "cache-only-pt.epub"
    raising = RaisingTranslator()
    cache_only_options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        cache_only=True,
    )
    with TranslationCache(cache_path) as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=raising,
            cache=cache,
            options=cache_only_options,
        )

    assert output_path.exists()
    assert report.output_written
    assert report.texts_missing == 0
    assert report.texts_translated == 0
    assert report.texts_from_cache == first.texts_translated + first.texts_from_cache
    assert raising.calls == []

    with ZipFile(output_path) as output_epub:
        names = output_epub.namelist()
        chapter_name = next(name for name in names if name.endswith("text/chapter1.xhtml"))
        chapter = output_epub.read(chapter_name).decode("utf-8")
    assert "PT:Hello reader. Visit" in chapter


def test_translate_epub_cache_only_writes_with_missing_texts_by_default(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "cache-only-pt.epub"
    raising = RaisingTranslator()
    options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        cache_only=True,
    )
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=raising,
            cache=cache,
            options=options,
        )

    assert output_path.exists()
    assert report.output_written
    assert report.texts_missing >= 4
    assert report.texts_translated == 0
    assert report.texts_from_cache == 0
    assert len(report.missing_texts) == report.texts_missing
    assert raising.calls == []

    with ZipFile(output_path) as output_epub:
        names = output_epub.namelist()
        chapter_name = next(name for name in names if name.endswith("text/chapter1.xhtml"))
        chapter = output_epub.read(chapter_name).decode("utf-8")
    assert "Hello reader. Visit" in chapter
    assert "PT:" not in chapter


def test_translate_epub_cache_only_require_full_cache_blocks_output_when_missing(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "cache-only-pt.epub"
    raising = RaisingTranslator()
    options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        cache_only=True,
        require_full_cache=True,
    )
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=raising,
            cache=cache,
            options=options,
        )

    assert not output_path.exists()
    assert not report.output_written
    assert report.texts_missing >= 4
    assert raising.calls == []


def test_translate_epub_collects_review_segments_with_document_metadata(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-pt.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(language_pair=LanguagePair(source="en", target="pt"))
    review_segments = []

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
            review_segments=review_segments,
        )

    assert review_segments
    assert review_segments[0].segment_id == "c0001-s0001"
    assert review_segments[0].source_epub == str(minimal_epub_path)
    assert review_segments[0].output_epub == str(output_path)
    assert review_segments[0].chapter_index == 1
    assert review_segments[0].document_path.endswith("text/chapter1.xhtml")
    assert review_segments[0].source_language == "en"
    assert review_segments[0].target_language == "pt"

    paragraph = next(segment for segment in review_segments if "Hello reader" in segment.original)
    assert paragraph.segment_id == "c0001-s0003"
    assert paragraph.segment_kind == "text"
    assert paragraph.original == "Hello reader. Visit chapter two."
    assert paragraph.translated == "PT:Hello reader. Visit chapter two."
    assert not paragraph.from_cache


def test_translate_epub_preserves_metadata_and_navigation_by_default(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-pt.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(language_pair=LanguagePair(source="en", target="pt"))

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
        )

    assert inspect_epub(output_path).title == "Minimal Test Book"
    assert ("Minimal Test Book", "en", "pt") not in translator.calls
    navigation = _read_navigation_document(output_path)
    assert "Chapter One" in navigation
    assert "PT:Chapter One" not in navigation


def test_translate_epub_translates_metadata_and_navigation_when_enabled(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-pt.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        translate_metadata=True,
    )

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
        )

    assert inspect_epub(output_path).title == "PT:Minimal Test Book"
    assert ("Minimal Test Book", "en", "pt") in translator.calls
    navigation = _read_navigation_document(output_path)
    assert 'PT:<a href="text/chapter1.xhtml">Chapter One</a>' in navigation


def test_translate_epub_collects_metadata_review_segment_when_enabled(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-pt.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        translate_metadata=True,
    )
    review_segments = []

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
            review_segments=review_segments,
        )

    metadata = next(segment for segment in review_segments if segment.segment_id == "metadata-title")
    assert metadata.chapter_index == 0
    assert metadata.chapter_name == "metadata"
    assert metadata.segment_kind == "metadata_title"
    assert metadata.original == "Minimal Test Book"
    assert metadata.translated == "PT:Minimal Test Book"


def _read_chapter_one(epub_path: Path) -> str:
    with ZipFile(epub_path) as output_epub:
        chapter_name = next(
            name for name in output_epub.namelist() if name.endswith("text/chapter1.xhtml")
        )
        return output_epub.read(chapter_name).decode("utf-8")


def test_translate_epub_preserves_image_alt_by_default(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-pt.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(language_pair=LanguagePair(source="en", target="pt"))

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
        )

    chapter = _read_chapter_one(output_path)
    assert 'alt="Pixel"' in chapter
    assert ("Pixel", "en", "pt") not in translator.calls
    assert report.alt_texts_translated == 0


def test_translate_epub_translates_image_alt_when_enabled(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-pt.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        translate_alt_text=True,
    )

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
        )

    chapter = _read_chapter_one(output_path)
    # The alt text is translated while the image and its src are preserved.
    assert 'alt="PT:Pixel"' in chapter
    assert "../images/pixel.png" in chapter
    assert ("Pixel", "en", "pt") in translator.calls
    assert report.alt_texts_translated == 1


def test_normalize_language_code_extracts_primary_subtag_from_bcp47():
    assert normalize_language_code("pt-BR") == "pt"
    assert normalize_language_code("en_US") == "en"
    assert normalize_language_code("EN") == "en"
    assert normalize_language_code("  fr ") == "fr"


def test_normalize_language_code_rejects_empty_or_invalid_values():
    assert normalize_language_code(None) is None
    assert normalize_language_code("") is None
    assert normalize_language_code("   ") is None
    assert normalize_language_code("english") is None
    assert normalize_language_code("12") is None
    assert normalize_language_code("e n") is None


def test_detect_epub_language_returns_normalized_metadata(minimal_epub_path: Path):
    assert detect_epub_language(minimal_epub_path) == "en"


def test_translate_epub_limits_documents_for_preview(minimal_epub_path: Path, tmp_path: Path):
    output_path = tmp_path / "minimal-preview.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        max_documents=1,
    )

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
        )

    assert report.chapters_processed == 1

    with ZipFile(output_path) as output_epub:
        names = output_epub.namelist()
        chapter_one_name = next(name for name in names if name.endswith("text/chapter1.xhtml"))
        chapter_two_name = next(name for name in names if name.endswith("text/chapter2.xhtml"))
        chapter_one = output_epub.read(chapter_one_name).decode("utf-8")
        chapter_two = output_epub.read(chapter_two_name).decode("utf-8")

    assert "PT:Hello reader. Visit" in chapter_one
    assert "PT:Goodbye reader." not in chapter_two
    assert "Goodbye reader." in chapter_two


def test_translate_epub_translates_selected_chapter_by_index_without_changing_others(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    output_path = tmp_path / "minimal-selected.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(
        language_pair=LanguagePair(source="en", target="pt"),
        chapter_selection=ChapterSelection.parse("2"),
    )

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
        )

    assert report.chapters_processed == 1

    with ZipFile(output_path) as output_epub:
        names = output_epub.namelist()
        chapter_one_name = next(name for name in names if name.endswith("text/chapter1.xhtml"))
        chapter_two_name = next(name for name in names if name.endswith("text/chapter2.xhtml"))
        chapter_one = output_epub.read(chapter_one_name).decode("utf-8")
        chapter_two = output_epub.read(chapter_two_name).decode("utf-8")

    assert "PT:Hello reader. Visit" not in chapter_one
    assert "Hello reader. Visit" in chapter_one
    assert "PT:Goodbye reader." in chapter_two


def test_resolve_chapter_selection_matches_title_and_path_patterns(minimal_epub_path: Path):
    by_title = resolve_chapter_selection(minimal_epub_path, ChapterSelection.parse("Chapter Two"))
    by_path = resolve_chapter_selection(minimal_epub_path, ChapterSelection.parse("*chapter2*"))

    assert [chapter.index for chapter in by_title] == [2]
    assert by_title[0].title == "Chapter Two"
    assert [chapter.index for chapter in by_path] == [2]


def test_resolve_chapter_selection_rejects_unmatched_selection(minimal_epub_path: Path):
    with pytest.raises(ChapterSelectionError, match="no chapters matched selection"):
        resolve_chapter_selection(minimal_epub_path, ChapterSelection.parse("999"))


def test_chapter_selection_rejects_invalid_range():
    with pytest.raises(ChapterSelectionError, match="chapter range is reversed"):
        ChapterSelection.parse("3-1")


def test_translate_epub_reports_glossary_usage(minimal_epub_path: Path, tmp_path: Path):
    output_path = tmp_path / "minimal-pt.epub"
    translator = PrefixTranslator()
    options = TranslationOptions(language_pair=LanguagePair(source="en", target="pt"))
    glossary = Glossary(
        [
            GlossaryEntry("PT:Hello reader", GLOSSARY_RULE_PRESERVE, required=True),
            GlossaryEntry("Missing Term", GLOSSARY_RULE_PRESERVE, required=True),
            GlossaryEntry("PT:Chapter Two", GLOSSARY_RULE_FORBIDDEN),
        ]
    )

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        report = translate_epub(
            minimal_epub_path,
            output_path,
            translator=translator,
            cache=cache,
            options=options,
            glossary=glossary,
        )

    assert report.glossary_terms_configured == 3
    assert report.glossary_usage.applied_terms["PT:Hello reader"] == 1
    assert report.glossary_usage.required_terms_present["PT:Hello reader"] == 1
    assert report.glossary_usage.required_terms_missing == ["Missing Term"]
    assert report.glossary_usage.forbidden_terms_found["PT:Chapter Two"] >= 1


def _export_review_csv(minimal_epub_path: Path, tmp_path: Path) -> Path:
    output_path = tmp_path / "minimal-pt.epub"
    review_segments = []
    options = TranslationOptions(language_pair=LanguagePair(source="en", target="pt"))
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_epub(
            minimal_epub_path,
            output_path,
            translator=PrefixTranslator(),
            cache=cache,
            options=options,
            review_segments=review_segments,
        )
    return write_review_csv(tmp_path / "review.csv", review_segments)


def _rewrite_csv(csv_path: Path, mutate) -> None:
    with csv_path.open(encoding="utf-8", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    for row in rows:
        mutate(row)
    with csv_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(REVIEW_CSV_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def test_apply_reviewed_epub_applies_reviewed_translation(minimal_epub_path: Path, tmp_path: Path):
    csv_path = _export_review_csv(minimal_epub_path, tmp_path)

    def review_paragraph(row: dict) -> None:
        if "Hello reader" in row["original"]:
            row["translated"] = "REVISADO leitor."

    _rewrite_csv(csv_path, review_paragraph)

    output_path = tmp_path / "minimal-reviewed.epub"
    report = apply_reviewed_epub(minimal_epub_path, output_path, read_review_csv(csv_path))

    chapter = _read_chapter_one(output_path)
    assert "REVISADO leitor." in chapter
    assert report.applied >= 1
    assert report.inconsistent == []
    assert report.missing_in_epub == []
    # Original EPUB is never modified (its English text is split by an inline link).
    original_chapter = _read_chapter_one(minimal_epub_path)
    assert "Hello reader. Visit" in original_chapter
    assert "chapter two</a>" in original_chapter


def test_apply_reviewed_epub_reports_inconsistent_when_original_changed(
    minimal_epub_path: Path,
    tmp_path: Path,
):
    csv_path = _export_review_csv(minimal_epub_path, tmp_path)

    def tamper_paragraph(row: dict) -> None:
        if "Hello reader" in row["original"]:
            row["original"] = "Different source text."
            row["translated"] = "Nao deve ser aplicado."

    _rewrite_csv(csv_path, tamper_paragraph)

    output_path = tmp_path / "minimal-reviewed.epub"
    report = apply_reviewed_epub(minimal_epub_path, output_path, read_review_csv(csv_path))

    assert "c0001-s0003" in report.inconsistent
    assert "Nao deve ser aplicado." not in _read_chapter_one(output_path)


def test_apply_reviewed_epub_reports_unknown_document(minimal_epub_path: Path, tmp_path: Path):
    review = ReviewImportData(
        rows=(
            ReviewRow(
                segment_id="c0001-s0001",
                document_path="OEBPS/text/ghost.xhtml",
                original="Whatever",
                translated="Tanto faz",
            ),
        ),
        duplicate_ids=(),
    )

    output_path = tmp_path / "minimal-reviewed.epub"
    report = apply_reviewed_epub(minimal_epub_path, output_path, review)

    assert report.unknown_documents == ["OEBPS/text/ghost.xhtml"]
    assert report.applied == 0
    assert output_path.exists()


def test_apply_reviewed_epub_reports_missing_segment_index(minimal_epub_path: Path, tmp_path: Path):
    csv_path = _export_review_csv(minimal_epub_path, tmp_path)
    data = read_review_csv(csv_path)
    document_path = next(row.document_path for row in data.rows if row.segment_id == "c0001-s0001")

    review = ReviewImportData(
        rows=(
            ReviewRow(
                segment_id="c0001-s9999",
                document_path=document_path,
                original="Out of range",
                translated="Fora de alcance",
            ),
        ),
        duplicate_ids=(),
    )

    output_path = tmp_path / "minimal-reviewed.epub"
    report = apply_reviewed_epub(minimal_epub_path, output_path, review)

    assert "c0001-s9999" in report.missing_in_epub
