from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .cache import TranslationCache
from .domain import LanguagePair, LanguagePairError
from .epub_io import inspect_epub
from .glossary import Glossary, GlossaryError, load_glossary
from .translator import (
    RouteResolutionError,
    RoutedTranslator,
    TranslationRoute,
    Translator,
    TranslatorError,
    TranslatorLanguage,
    create_translator,
    resolve_translation_route,
)


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
    route: TranslationRoute | None = None


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
    cache_only: bool = False,
    requests_per_second: float | None = None,
    retry_backoff: float = 0.5,
    retry_backoff_max: float = 8.0,
) -> TranslationPreflightResult:
    _check_language_pair(language_pair)
    glossary = _load_checked_glossary(glossary_path)
    translator = _create_checked_translator(
        translator_name,
        url,
        timeout,
        retries,
        requests_per_second=requests_per_second,
        retry_backoff=retry_backoff,
        retry_backoff_max=retry_backoff_max,
    )
    _check_cache(cache_path)
    _check_epub(epub_path)
    route: TranslationRoute | None = None
    if not dry_run and not cache_only:
        route = _resolve_route_or_fallback(translator, language_pair, url)
        if route is not None and not route.is_direct:
            translator = RoutedTranslator(translator, route)
    return TranslationPreflightResult(translator=translator, glossary=glossary, route=route)


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


def _create_checked_translator(
    name: str,
    url: str,
    timeout: float,
    retries: int,
    requests_per_second: float | None,
    retry_backoff: float,
    retry_backoff_max: float,
) -> Translator:
    try:
        return create_translator(
            name,
            url=url,
            timeout=timeout,
            retries=retries,
            requests_per_second=requests_per_second,
            retry_backoff=retry_backoff,
            retry_backoff_max=retry_backoff_max,
        )
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


def _resolve_route_or_fallback(
    translator: Translator,
    language_pair: LanguagePair,
    url: str,
) -> TranslationRoute | None:
    languages = _list_translator_languages(translator, url)
    if languages is None:
        return _probe_translator_pair(translator, language_pair, url)

    try:
        return resolve_translation_route(languages, language_pair.source, language_pair.target)
    except RouteResolutionError as exc:
        raise PreflightError(
            "O par de idiomas não está disponível no tradutor.",
            (
                "Confirme em 'ayvu languages' os idiomas instalados, escolha outro --target, "
                "ou instale o idioma necessário no LibreTranslate."
            ),
            detail=str(exc),
        ) from exc


def _list_translator_languages(
    translator: Translator,
    url: str,
) -> tuple[TranslatorLanguage, ...] | None:
    lister = getattr(translator, "list_languages", None)
    if lister is None:
        return None
    try:
        return lister()
    except TranslatorError as exc:
        raise PreflightError(
            "O tradutor não respondeu.",
            f"Inicie o LibreTranslate em {url}, verifique --url e confirme que o servidor está acessível.",
            detail=str(exc),
        ) from exc


def _probe_translator_pair(
    translator: Translator,
    language_pair: LanguagePair,
    url: str,
) -> TranslationRoute:
    try:
        translator.translate("Hello world", language_pair.source, language_pair.target)
    except Exception as exc:
        raise PreflightError(
            "O tradutor não respondeu.",
            f"Inicie o LibreTranslate em {url}, verifique --url e confirme que o par de idiomas está disponível.",
            detail=str(exc),
        ) from exc
    return TranslationRoute(source=language_pair.source, target=language_pair.target)
