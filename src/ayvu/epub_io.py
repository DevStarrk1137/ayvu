from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from zipfile import ZIP_STORED, ZipFile
import xml.etree.ElementTree as ET

from ebooklib import ITEM_DOCUMENT
from ebooklib import epub

from .cache import TranslationCache
from .domain import TranslationOptions
from .glossary import Glossary, GlossaryUsage
from .html_translate import (
    HtmlTranslationStats,
    TextTranslationResult,
    extract_visible_text,
    translate_html,
    translate_text,
)
from .translator import Translator


ChapterStartCallback = Callable[[int, int, str], None]
ChapterDoneCallback = Callable[[int, int, str, HtmlTranslationStats], None]
TextProgressCallback = Callable[[str], None]
OPF_NAMESPACE = "http://www.idpf.org/2007/opf"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"

ET.register_namespace("", OPF_NAMESPACE)
ET.register_namespace("dc", DC_NAMESPACE)


@dataclass
class EpubInfo:
    path: Path
    title: str | None
    authors: list[str]
    language: str | None
    document_count: int
    item_count: int


@dataclass(frozen=True)
class EpubDocument:
    name: str
    archive_path: str


@dataclass(frozen=True)
class EpubStructureError:
    document: EpubDocument
    detail: str

    @classmethod
    def missing_document(cls, document: EpubDocument) -> "EpubStructureError":
        return cls(
            document=document,
            detail=f"document not found in EPUB archive at {document.archive_path}",
        )

    @classmethod
    def chapter_error(cls, document: EpubDocument, exc: Exception) -> "EpubStructureError":
        return cls(document=document, detail=str(exc))

    def as_message(self) -> str:
        return f"{self.document.name}: {self.detail}"


@dataclass
class TranslationReport:
    chapters_processed: int = 0
    texts_translated: int = 0
    texts_from_cache: int = 0
    texts_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    glossary_terms_configured: int = 0
    glossary_usage: GlossaryUsage = field(default_factory=GlossaryUsage)
    output_path: Path | None = None
    input_path: Path | None = None
    detected_language: str | None = None
    target_language: str | None = None

    def record_error(self, message: str) -> None:
        self.errors.append(message)

    def record_chapter(self, stats: HtmlTranslationStats) -> None:
        self.texts_translated += stats.translated
        self.texts_from_cache += stats.from_cache
        self.texts_skipped += stats.skipped
        self.errors.extend(stats.errors)
        self.glossary_usage.merge(stats.glossary_usage)
        self.chapters_processed += 1

    def record_text(self, result: TextTranslationResult) -> None:
        if result.from_cache:
            self.texts_from_cache += 1
        else:
            self.texts_translated += 1
        self.glossary_usage.merge(result.glossary_usage)


@dataclass
class EpubReplacements:
    items: dict[str, bytes] = field(default_factory=dict)

    def add(self, archive_path: str, content: bytes) -> None:
        self.items[archive_path] = content

    def content_for(self, filename: str, source_epub: ZipFile) -> bytes:
        replacement = self.items.get(filename)
        if replacement is not None:
            return replacement
        return source_epub.read(filename)


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


def normalize_language_code(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    primary = cleaned.split("-", 1)[0].split("_", 1)[0].lower()
    if not primary.isalpha() or not 2 <= len(primary) <= 3:
        return None
    return primary


def detect_epub_language(path: str | Path) -> str | None:
    info = inspect_epub(path)
    return normalize_language_code(info.language)


def translate_epub(
    input_path: str | Path,
    output_path: str | Path,
    translator: Translator,
    cache: TranslationCache,
    options: TranslationOptions,
    glossary: Glossary | None = None,
    on_chapter_start: ChapterStartCallback | None = None,
    on_chapter_done: ChapterDoneCallback | None = None,
    on_text_processed: TextProgressCallback | None = None,
) -> TranslationReport:
    source_path = Path(input_path)
    destination_path = Path(output_path)
    book = epub.read_epub(str(source_path))
    report = TranslationReport(
        output_path=destination_path,
        input_path=source_path,
        detected_language=_first_metadata(book, "DC", "language"),
        target_language=options.target,
        glossary_terms_configured=len(glossary.entries) if glossary else 0,
    )
    opf_archive_path = _get_opf_archive_path(source_path)
    opf_base_path = _opf_base_path(opf_archive_path)
    replacements = EpubReplacements()

    with ZipFile(source_path, "r") as source_epub:
        archive_names = set(source_epub.namelist())
        navigation_documents = _navigation_document_entries(source_epub, opf_archive_path, opf_base_path)
        documents = _limited_documents(
            _documents_for_translation(
                _document_entries(book, opf_base_path),
                navigation_documents,
                translate_metadata=options.translate_metadata,
            ),
            options.max_documents,
        )
        total_documents = len(documents)

        if options.translate_metadata and opf_archive_path and opf_archive_path in archive_names:
            try:
                translated_opf = _translate_opf_title(
                    source_epub.read(opf_archive_path),
                    translator=translator,
                    cache=cache,
                    options=options,
                    glossary=glossary,
                    report=report,
                    on_text_processed=on_text_processed,
                )
                if translated_opf is not None and not options.dry_run:
                    replacements.add(opf_archive_path, translated_opf)
            except Exception as exc:
                report.record_error(f"metadata title: {exc}")
                _notify_text_processed(on_text_processed, "error")
                if options.fail_fast:
                    raise

        for index, document in enumerate(documents, start=1):
            if document.archive_path not in archive_names:
                report.record_error(EpubStructureError.missing_document(document).as_message())
                if options.fail_fast:
                    raise FileNotFoundError(document.archive_path)
                continue

            if on_chapter_start:
                on_chapter_start(index, total_documents, document.name)

            try:
                translated_content, stats = translate_html(
                    source_epub.read(document.archive_path),
                    translator=translator,
                    cache=cache,
                    source=options.source,
                    target=options.target,
                    glossary=glossary,
                    dry_run=options.dry_run,
                    fail_fast=options.fail_fast,
                    chunk_limit=options.chunk_limit,
                    on_text_processed=on_text_processed,
                )
                if not options.dry_run:
                    replacements.add(document.archive_path, translated_content)
                report.record_chapter(stats)
                if on_chapter_done:
                    on_chapter_done(index, total_documents, document.name, stats)
            except Exception as exc:
                report.record_error(EpubStructureError.chapter_error(document, exc).as_message())
                if options.fail_fast:
                    raise

    if not options.dry_run:
        if glossary:
            report.glossary_usage.finalize_required_terms(glossary)
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
        text = "\n".join(extract_visible_text(item.get_content()))
        file_path = destination / f"{index:03d}-{Path(item.get_name()).stem}.md"
        file_path.write_text(_clean_extracted_text(text), encoding="utf-8")
        written.append(file_path)

    return written


def _clean_extracted_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = [line for line in lines if line]
    return "\n\n".join(clean_lines) + ("\n" if clean_lines else "")


def _get_opf_base_path(epub_path: Path) -> PurePosixPath:
    return _opf_base_path(_get_opf_archive_path(epub_path))


def _get_opf_archive_path(epub_path: Path) -> str | None:
    with ZipFile(epub_path, "r") as source_epub:
        container_xml = source_epub.read("META-INF/container.xml")

    root = ET.fromstring(container_xml)
    namespace = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfile = root.find(".//container:rootfile", namespace)
    if rootfile is None:
        rootfile = root.find(".//rootfile")
    if rootfile is None:
        return None

    full_path = rootfile.attrib.get("full-path", "").strip()
    return full_path or None


def _opf_base_path(opf_archive_path: str | None) -> PurePosixPath:
    if opf_archive_path is None:
        return PurePosixPath(".")
    parent = PurePosixPath(opf_archive_path).parent
    return parent if str(parent) != "." else PurePosixPath(".")


def _document_zip_path(opf_base_path: PurePosixPath, item_name: str) -> str:
    path = PurePosixPath(item_name)
    if opf_base_path != PurePosixPath("."):
        path = opf_base_path / path
    return path.as_posix()


def _document_entries(book: epub.EpubBook, opf_base_path: PurePosixPath) -> list[EpubDocument]:
    documents: list[EpubDocument] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        name = item.get_name()
        documents.append(EpubDocument(name=name, archive_path=_document_zip_path(opf_base_path, name)))
    return documents


def _limited_documents(documents: list[EpubDocument], max_documents: int | None) -> list[EpubDocument]:
    if max_documents is None:
        return documents
    return documents[:max(0, max_documents)]


def _documents_for_translation(
    documents: list[EpubDocument],
    navigation_documents: list[EpubDocument],
    translate_metadata: bool,
) -> list[EpubDocument]:
    navigation_paths = {document.archive_path for document in navigation_documents}
    if not translate_metadata:
        return [document for document in documents if document.archive_path not in navigation_paths]

    selected = list(documents)
    selected_paths = {document.archive_path for document in selected}
    for document in navigation_documents:
        if document.archive_path not in selected_paths:
            selected.append(document)
            selected_paths.add(document.archive_path)
    return selected


def _navigation_document_entries(
    source_epub: ZipFile,
    opf_archive_path: str | None,
    opf_base_path: PurePosixPath,
) -> list[EpubDocument]:
    if opf_archive_path is None or opf_archive_path not in source_epub.namelist():
        return []

    try:
        root = ET.fromstring(source_epub.read(opf_archive_path))
    except ET.ParseError:
        return []

    manifest = _first_child_by_local_name(root, "manifest")
    if manifest is None:
        return []

    documents: list[EpubDocument] = []
    for item in manifest:
        if _local_name(item.tag) != "item":
            continue
        properties = item.attrib.get("properties", "")
        if "nav" not in properties.split():
            continue
        href = item.attrib.get("href", "").strip()
        if not href:
            continue
        archive_path = _document_zip_path(opf_base_path, _manifest_href_path(href))
        documents.append(EpubDocument(name=href, archive_path=archive_path))
    return documents


def _manifest_href_path(href: str) -> str:
    clean = href.split("#", 1)[0].split("?", 1)[0]
    return PurePosixPath(unquote(clean)).as_posix()


def _translate_opf_title(
    opf_content: bytes,
    translator: Translator,
    cache: TranslationCache,
    options: TranslationOptions,
    glossary: Glossary | None,
    report: TranslationReport,
    on_text_processed: TextProgressCallback | None,
) -> bytes | None:
    root = ET.fromstring(opf_content)
    title = _first_metadata_title(root)
    if title is None or title.text is None or not title.text.strip():
        return None

    result = translate_text(
        title.text,
        translator=translator,
        cache=cache,
        source=options.source,
        target=options.target,
        glossary=glossary,
        dry_run=options.dry_run,
        chunk_limit=options.chunk_limit,
    )
    title.text = result.text
    report.record_text(result)
    _notify_text_processed(on_text_processed, _text_progress_status(result, options.dry_run))
    return ET.tostring(root, encoding="utf-8", xml_declaration=_has_xml_declaration(opf_content))


def _first_metadata_title(root: ET.Element) -> ET.Element | None:
    metadata = _first_child_by_local_name(root, "metadata")
    if metadata is None:
        return None
    for child in metadata:
        if _local_name(child.tag) == "title":
            return child
    return None


def _first_child_by_local_name(root: ET.Element, name: str) -> ET.Element | None:
    for child in root.iter():
        if _local_name(child.tag) == name:
            return child
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _has_xml_declaration(content: bytes) -> bool:
    return content.lstrip().startswith(b"<?xml")


def _text_progress_status(result: TextTranslationResult, dry_run: bool) -> str:
    if result.from_cache:
        return "cache"
    if dry_run:
        return "dry_run"
    return "translated"


def _notify_text_processed(callback: TextProgressCallback | None, status: str) -> None:
    if callback:
        callback(status)


def _copy_epub_with_replacements(
    input_path: Path,
    output_path: Path,
    replacements: EpubReplacements,
) -> None:
    with ZipFile(input_path, "r") as source_epub, ZipFile(output_path, "w") as output_epub:
        for info in source_epub.infolist():
            data = replacements.content_for(info.filename, source_epub)
            if info.filename == "mimetype":
                info.compress_type = ZIP_STORED
            output_epub.writestr(info, data)


def _first_metadata(book: epub.EpubBook, namespace: str, name: str) -> str | None:
    values = book.get_metadata(namespace, name)
    if not values:
        return None
    return values[0][0]
