from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .config import AyvuConfig


LANGUAGE_NAMES = {
    "de": "Alemão",
    "en": "Inglês",
    "es": "Espanhol",
    "fr": "Francês",
    "it": "Italiano",
    "ja": "Japonês",
    "pt": "Português",
    "pt-br": "Português (Brasil)",
}


class LibraryOpenError(RuntimeError):
    pass


@dataclass(frozen=True)
class LibraryTranslation:
    path: Path
    language: str

    @property
    def label(self) -> str:
        return f"Traduzido - {language_display_name(self.language)}"


@dataclass(frozen=True)
class LibraryBook:
    name: str
    original_path: Path | None
    translations: tuple[LibraryTranslation, ...]

    @property
    def has_original(self) -> bool:
        return self.original_path is not None


def scan_library(config: AyvuConfig) -> tuple[LibraryBook, ...]:
    originals = _epub_files(config.original_dir)
    translations = _epub_files(config.translated_dir)
    original_paths = {path.stem: path for path in originals}
    grouped_translations = _group_translations(translations, original_paths)

    book_names = set(original_paths) | set(grouped_translations)
    books = [
        LibraryBook(
            name=name,
            original_path=original_paths.get(name),
            translations=tuple(sorted(grouped_translations[name], key=_translation_sort_key)),
        )
        for name in book_names
    ]
    return tuple(sorted(books, key=lambda book: book.name.casefold()))


def language_display_name(language: str) -> str:
    normalized = language.strip()
    if not normalized:
        return "idioma desconhecido"
    return LANGUAGE_NAMES.get(normalized.lower(), normalized)


def open_library_epub(
    path: Path,
    reader_app: str | None = None,
    runner: Callable[[list[str]], object] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> None:
    if not path.is_file():
        raise LibraryOpenError(f"EPUB file was not found: {path}")

    command = _reader_command(reader_app, which or shutil.which)
    if command is None:
        raise LibraryOpenError("No EPUB reader app is configured or available on this system.")

    run = runner or subprocess.Popen
    try:
        run([*command, str(path)])
    except OSError as exc:
        raise LibraryOpenError(f"Could not open EPUB with {command[0]}: {exc}") from exc


def _epub_files(directory: Path) -> tuple[Path, ...]:
    if not directory.exists():
        return ()
    return tuple(sorted((path for path in directory.glob("*.epub") if path.is_file()), key=_path_sort_key))


def _group_translations(
    translations: Iterable[Path],
    original_paths: dict[str, Path],
) -> dict[str, list[LibraryTranslation]]:
    grouped: dict[str, list[LibraryTranslation]] = defaultdict(list)
    for path in translations:
        book_name, language = _split_translation_stem(path.stem, original_paths)
        grouped[book_name].append(LibraryTranslation(path=path, language=language))
    return grouped


def _split_translation_stem(stem: str, original_paths: dict[str, Path]) -> tuple[str, str]:
    for original_stem in sorted(original_paths, key=len, reverse=True):
        prefix = f"{original_stem}-"
        if stem.startswith(prefix) and len(stem) > len(prefix):
            return original_stem, stem[len(prefix) :]

    return _split_stem_without_original(stem)


def _split_stem_without_original(stem: str) -> tuple[str, str]:
    parts = stem.split("-")
    if len(parts) >= 3 and _looks_language_code(parts[-2]) and _looks_region_code(parts[-1]):
        return "-".join(parts[:-2]) or stem, f"{parts[-2]}-{parts[-1]}"
    if len(parts) >= 2:
        return "-".join(parts[:-1]) or stem, parts[-1]
    return stem, ""


def _looks_language_code(value: str) -> bool:
    return value.isalpha() and len(value) in (2, 3)


def _looks_region_code(value: str) -> bool:
    return value.isalpha() and len(value) == 2


def _reader_command(reader_app: str | None, which: Callable[[str], str | None]) -> list[str] | None:
    if reader_app:
        try:
            command = shlex.split(reader_app)
        except ValueError as exc:
            raise LibraryOpenError("Reader app command is invalid.") from exc
        if command:
            return command

    for command in _system_reader_commands():
        if which(command[0]):
            return list(command)
    return None


def _system_reader_commands() -> tuple[tuple[str, ...], ...]:
    if os.name == "nt":
        return ()
    return (("xdg-open",), ("gio", "open"), ("open",))


def _path_sort_key(path: Path) -> str:
    return path.stem.casefold()


def _translation_sort_key(translation: LibraryTranslation) -> tuple[str, str]:
    return (language_display_name(translation.language).casefold(), translation.path.name.casefold())
