from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .cache import TranslationCache
from .domain import LanguagePair, LanguagePairError
from .epub_io import inspect_epub
from .glossary import Glossary, GlossaryError, load_glossary
from .translator import Translator, TranslatorError, create_translator


class PreflightError(RuntimeError):
    def __init__(self, message: str, next_step: str) -> None:
        super().__init__(message)
        self.next_step = next_step


@dataclass(frozen=True)
class TranslationPreflightResult:
    translator: Translator
    glossary: Glossary


def run_translation_preflight(
    epub_path: Path,
    cache_path: Path,
    glossary_path: Path | None,
    translator_name: str,
    url: str,
    timeout: float,
    retries: int,
    language_pair: LanguagePair,
    dry_run: bool,
) -> TranslationPreflightResult:
    _check_language_pair(language_pair)
    glossary = _load_checked_glossary(glossary_path)
    translator = _create_checked_translator(translator_name, url, timeout, retries)
    _check_cache(cache_path)
    _check_epub(epub_path)
    if not dry_run:
        _check_translator(translator, language_pair, url)
    return TranslationPreflightResult(translator=translator, glossary=glossary)


def _check_language_pair(language_pair: LanguagePair) -> None:
    try:
        language_pair.validate_for_translation()
    except LanguagePairError as exc:
        raise PreflightError(
            f"Language pair check failed: {exc}.",
            "Use non-empty language codes with --source and --target, for example --source en --target pt.",
        ) from exc


def _load_checked_glossary(glossary_path: Path | None) -> Glossary:
    try:
        return load_glossary(glossary_path)
    except GlossaryError as exc:
        raise PreflightError(
            f"Glossary check failed: {exc}",
            "Create the file, pass the correct path, or remove --glossary to run without one.",
        ) from exc


def _create_checked_translator(name: str, url: str, timeout: float, retries: int) -> Translator:
    try:
        return create_translator(name, url=url, timeout=timeout, retries=retries)
    except TranslatorError as exc:
        raise PreflightError(
            f"Translator check failed: {exc}",
            "Use --translator libretranslate.",
        ) from exc


def _check_cache(cache_path: Path) -> None:
    try:
        with TranslationCache(cache_path) as cache:
            cache.verify_writable()
    except (OSError, sqlite3.Error) as exc:
        raise PreflightError(
            f"Cache check failed: could not create or write cache at {cache_path}: {exc}",
            "Choose a writable cache path with --cache or fix permissions for the cache directory.",
        ) from exc


def _check_epub(epub_path: Path) -> None:
    try:
        inspect_epub(epub_path)
    except Exception as exc:
        raise PreflightError(
            f"EPUB check failed: could not read {epub_path}: {exc}",
            "Confirm the file is a valid readable EPUB and try again.",
        ) from exc


def _check_translator(translator: Translator, language_pair: LanguagePair, url: str) -> None:
    try:
        translator.translate("Hello world", language_pair.source, language_pair.target)
    except Exception as exc:
        raise PreflightError(
            f"Translator check failed: {exc}",
            f"Start LibreTranslate at {url}, check --url, and confirm the language pair is available.",
        ) from exc
