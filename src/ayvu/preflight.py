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
    def __init__(self, summary: str, next_step: str, detail: str = "") -> None:
        super().__init__(summary)
        self.summary = summary
        self.next_step = next_step
        self.detail = detail


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
            "O par de idiomas informado não é válido.",
            "Use códigos de idioma não vazios em --source e --target, por exemplo --source en --target pt.",
            detail=str(exc),
        ) from exc


def _load_checked_glossary(glossary_path: Path | None) -> Glossary:
    try:
        return load_glossary(glossary_path)
    except GlossaryError as exc:
        raise PreflightError(
            "Não foi possível carregar o glossário.",
            "Crie o arquivo, informe o caminho correto, ou remova --glossary para rodar sem glossário.",
            detail=str(exc),
        ) from exc


def _create_checked_translator(name: str, url: str, timeout: float, retries: int) -> Translator:
    try:
        return create_translator(name, url=url, timeout=timeout, retries=retries)
    except TranslatorError as exc:
        raise PreflightError(
            "Não foi possível preparar o tradutor.",
            "Use --translator libretranslate.",
            detail=str(exc),
        ) from exc


def _check_cache(cache_path: Path) -> None:
    try:
        with TranslationCache(cache_path) as cache:
            cache.verify_writable()
    except (OSError, sqlite3.Error) as exc:
        raise PreflightError(
            "Não foi possível criar ou escrever o cache.",
            "Escolha um caminho de cache com permissão de escrita usando --cache, ou ajuste as permissões da pasta do cache.",
            detail=f"Cache em {cache_path}: {exc}",
        ) from exc


def _check_epub(epub_path: Path) -> None:
    try:
        inspect_epub(epub_path)
    except Exception as exc:
        raise PreflightError(
            "Não foi possível ler o EPUB informado.",
            "Confirme que o arquivo é um EPUB válido e legível e tente novamente.",
            detail=f"{epub_path}: {exc}",
        ) from exc


def _check_translator(translator: Translator, language_pair: LanguagePair, url: str) -> None:
    try:
        translator.translate("Hello world", language_pair.source, language_pair.target)
    except Exception as exc:
        raise PreflightError(
            "O tradutor não respondeu.",
            f"Inicie o LibreTranslate em {url}, verifique --url e confirme que o par de idiomas está disponível.",
            detail=str(exc),
        ) from exc
