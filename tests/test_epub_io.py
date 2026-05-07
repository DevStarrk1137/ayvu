from pathlib import PurePosixPath

from ebooklib import ITEM_DOCUMENT

from ayvu.epub_io import (
    EpubDocument,
    EpubReplacements,
    EpubStructureError,
    TranslationReport,
    _document_entries,
    _document_zip_path,
)


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
