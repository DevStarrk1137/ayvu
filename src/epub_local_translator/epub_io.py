from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from zipfile import ZIP_STORED, ZipFile
import xml.etree.ElementTree as ET

from ebooklib import ITEM_DOCUMENT
from ebooklib import epub

from .cache import TranslationCache
from .glossary import Glossary
from .html_translate import HtmlTranslationStats, translate_html
from .translator import Translator


ChapterStartCallback = Callable[[int, int, str], None]
ChapterDoneCallback = Callable[[int, int, str, HtmlTranslationStats], None]
TextProgressCallback = Callable[[str], None]


@dataclass
class EpubInfo:
    path: Path
    title: str | None
    authors: list[str]
    language: str | None
    document_count: int
    item_count: int


@dataclass
class TranslationReport:
    chapters_processed: int = 0
    texts_translated: int = 0
    texts_from_cache: int = 0
    texts_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    output_path: Path | None = None


def inspect_epub(path: str | Path) -> EpubInfo:
    epub_path = Path(path)
    book = epub.read_epub(str(epub_path))
    title = _first_metadata(book, "DC", "title")
    language = _first_metadata(book, "DC", "language")
    authors = [entry[0] for entry in book.get_metadata("DC", "creator")]
    documents = list(book.get_items_of_type(ITEM_DOCUMENT))
    items = list(book.get_items())
    return EpubInfo(
        path=epub_path,
        title=title,
        authors=authors,
        language=language,
        document_count=len(documents),
        item_count=len(items),
    )


def translate_epub(
    input_path: str | Path,
    output_path: str | Path,
    translator: Translator,
    cache: TranslationCache,
    source: str,
    target: str,
    glossary: Glossary | None = None,
    dry_run: bool = False,
    fail_fast: bool = False,
    chunk_limit: int = 3000,
    on_chapter_start: ChapterStartCallback | None = None,
    on_chapter_done: ChapterDoneCallback | None = None,
    on_text_processed: TextProgressCallback | None = None,
) -> TranslationReport:
    source_path = Path(input_path)
    destination_path = Path(output_path)
    book = epub.read_epub(str(source_path))
    report = TranslationReport(output_path=destination_path)
    opf_base_path = _get_opf_base_path(source_path)
    replacements: dict[str, bytes] = {}

    documents = list(book.get_items_of_type(ITEM_DOCUMENT))
    total_documents = len(documents)

    with ZipFile(source_path, "r") as source_epub:
        archive_names = set(source_epub.namelist())

        for index, item in enumerate(documents, start=1):
            item_name = item.get_name()
            item_path = _document_zip_path(opf_base_path, item_name)
            if item_path not in archive_names:
                message = f"{item_name}: document not found in EPUB archive at {item_path}"
                report.errors.append(message)
                if fail_fast:
                    raise FileNotFoundError(item_path)
                continue

            if on_chapter_start:
                on_chapter_start(index, total_documents, item_name)

            try:
                translated_content, stats = translate_html(
                    source_epub.read(item_path),
                    translator=translator,
                    cache=cache,
                    source=source,
                    target=target,
                    glossary=glossary,
                    dry_run=dry_run,
                    fail_fast=fail_fast,
                    chunk_limit=chunk_limit,
                    on_text_processed=on_text_processed,
                )
                if not dry_run:
                    replacements[item_path] = translated_content
                _merge_stats(report, stats)
                report.chapters_processed += 1
                if on_chapter_done:
                    on_chapter_done(index, total_documents, item_name, stats)
            except Exception as exc:
                message = f"{item_name}: {exc}"
                report.errors.append(message)
                if fail_fast:
                    raise

    if not dry_run:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_epub_with_replacements(source_path, destination_path, replacements)

    return report


def extract_markdown(input_path: str | Path, output_dir: str | Path) -> list[Path]:
    source_path = Path(input_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    book = epub.read_epub(str(source_path))
    written: list[Path] = []

    for index, item in enumerate(book.get_items_of_type(ITEM_DOCUMENT), start=1):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(item.get_content(), "lxml")
        text = soup.get_text("\n")
        file_path = destination / f"{index:03d}-{Path(item.get_name()).stem}.md"
        file_path.write_text(_clean_extracted_text(text), encoding="utf-8")
        written.append(file_path)

    return written


def _clean_extracted_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = [line for line in lines if line]
    return "\n\n".join(clean_lines) + ("\n" if clean_lines else "")


def _get_opf_base_path(epub_path: Path) -> PurePosixPath:
    with ZipFile(epub_path, "r") as source_epub:
        container_xml = source_epub.read("META-INF/container.xml")

    root = ET.fromstring(container_xml)
    namespace = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfile = root.find(".//container:rootfile", namespace)
    if rootfile is None:
        rootfile = root.find(".//rootfile")
    if rootfile is None:
        return PurePosixPath(".")

    full_path = rootfile.attrib.get("full-path", "")
    parent = PurePosixPath(full_path).parent
    return parent if str(parent) != "." else PurePosixPath(".")


def _document_zip_path(opf_base_path: PurePosixPath, item_name: str) -> str:
    path = PurePosixPath(item_name)
    if opf_base_path != PurePosixPath("."):
        path = opf_base_path / path
    return path.as_posix()


def _copy_epub_with_replacements(
    input_path: Path,
    output_path: Path,
    replacements: dict[str, bytes],
) -> None:
    with ZipFile(input_path, "r") as source_epub, ZipFile(output_path, "w") as output_epub:
        for info in source_epub.infolist():
            data = replacements.get(info.filename)
            if data is None:
                data = source_epub.read(info.filename)
            if info.filename == "mimetype":
                info.compress_type = ZIP_STORED
            output_epub.writestr(info, data)


def _first_metadata(book: epub.EpubBook, namespace: str, name: str) -> str | None:
    values = book.get_metadata(namespace, name)
    if not values:
        return None
    return values[0][0]


def _merge_stats(report: TranslationReport, stats: HtmlTranslationStats) -> None:
    report.texts_translated += stats.translated
    report.texts_from_cache += stats.from_cache
    report.texts_skipped += stats.skipped
    report.errors.extend(stats.errors)
