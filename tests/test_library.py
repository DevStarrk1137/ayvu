from pathlib import Path

import pytest

from ayvu.config import AyvuConfig
from ayvu.library import LibraryOpenError, open_library_epub, scan_library


def test_scan_library_groups_originals_and_translations_by_book(tmp_path):
    config = AyvuConfig(books_dir=tmp_path)
    original_dir = config.original_dir
    translated_dir = config.translated_dir
    original_dir.mkdir(parents=True)
    translated_dir.mkdir(parents=True)
    (original_dir / "Beta.epub").write_bytes(b"")
    (original_dir / "Alpha.epub").write_bytes(b"")
    (translated_dir / "Alpha-pt.epub").write_bytes(b"")
    (translated_dir / "Beta-es.epub").write_bytes(b"")
    (translated_dir / "Gamma-pt-BR.epub").write_bytes(b"")
    (translated_dir / "ignore.txt").write_text("not an epub", encoding="utf-8")

    books = scan_library(config)

    assert [book.name for book in books] == ["Alpha", "Beta", "Gamma"]
    assert books[0].has_original
    assert [translation.label for translation in books[0].translations] == ["Traduzido - Português"]
    assert [translation.label for translation in books[1].translations] == ["Traduzido - Espanhol"]
    assert not books[2].has_original
    assert [translation.label for translation in books[2].translations] == ["Traduzido - Português (Brasil)"]


def test_scan_library_returns_empty_when_configured_dirs_do_not_exist(tmp_path):
    config = AyvuConfig(books_dir=tmp_path)

    assert scan_library(config) == ()


def test_open_library_epub_uses_configured_reader_command(tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"")
    calls: list[list[str]] = []

    open_library_epub(
        epub_path,
        reader_app="foliate --new-window",
        runner=calls.append,
        which=lambda _name: None,
    )

    assert calls == [["foliate", "--new-window", str(epub_path)]]


def test_open_library_epub_uses_detected_system_reader(tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"")
    calls: list[list[str]] = []

    open_library_epub(
        epub_path,
        runner=calls.append,
        which=lambda name: f"/usr/bin/{name}" if name == "xdg-open" else None,
    )

    assert calls == [["xdg-open", str(epub_path)]]


def test_open_library_epub_requires_reader_app_or_detected_reader(tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"")

    with pytest.raises(LibraryOpenError, match="No EPUB reader"):
        open_library_epub(epub_path, runner=lambda _command: None, which=lambda _name: None)


def test_open_library_epub_reports_missing_epub(tmp_path):
    with pytest.raises(LibraryOpenError, match="not found"):
        open_library_epub(tmp_path / "missing.epub", runner=lambda _command: None, which=lambda _name: "xdg-open")


def test_open_library_epub_reports_reader_failure(tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"")

    def fail(_command: list[str]) -> None:
        raise OSError("broken")

    with pytest.raises(LibraryOpenError, match="Could not open EPUB"):
        open_library_epub(epub_path, reader_app="foliate", runner=fail)
