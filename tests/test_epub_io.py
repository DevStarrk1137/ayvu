from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from ebooklib import ITEM_DOCUMENT

from ayvu.cache import TranslationCache
from ayvu.domain import LanguagePair, TranslationOptions
from ayvu.epub_io import (
    EpubDocument,
    EpubReplacements,
    EpubStructureError,
    TranslationReport,
    _document_entries,
    _document_zip_path,
    detect_epub_language,
    extract_markdown,
    inspect_epub,
    normalize_language_code,
    translate_epub,
)
from ayvu.glossary import GLOSSARY_RULE_FORBIDDEN, GLOSSARY_RULE_PRESERVE, Glossary, GlossaryEntry


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
    assert report.texts_translated >= 5
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
