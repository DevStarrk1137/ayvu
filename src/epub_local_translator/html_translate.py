from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction

from .cache import TranslationCache
from .chunking import split_text
from .glossary import Glossary, apply_glossary
from .translator import Translator


IGNORED_TAGS = {"script", "style", "code", "pre", "kbd", "samp", "svg", "math"}
TextProgressCallback = Callable[[str], None]


@dataclass
class HtmlTranslationStats:
    translated: int = 0
    from_cache: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def translate_html(
    html: str | bytes,
    translator: Translator,
    cache: TranslationCache,
    source: str,
    target: str,
    glossary: Glossary | None = None,
    dry_run: bool = False,
    fail_fast: bool = False,
    chunk_limit: int = 3000,
    on_error: Callable[[Exception], None] | None = None,
    on_text_processed: TextProgressCallback | None = None,
) -> tuple[bytes, HtmlTranslationStats]:
    soup = BeautifulSoup(html, "lxml-xml")
    stats = HtmlTranslationStats()

    for text_node in list(soup.find_all(string=True)):
        if not _is_visible_text_node(text_node):
            stats.skipped += 1
            continue

        original = str(text_node)
        if not original.strip():
            stats.skipped += 1
            continue

        try:
            translated_text, used_cache = translate_text(
                original,
                translator=translator,
                cache=cache,
                source=source,
                target=target,
                glossary=glossary,
                dry_run=dry_run,
                chunk_limit=chunk_limit,
            )
            if not dry_run:
                text_node.replace_with(NavigableString(translated_text))
            if used_cache:
                stats.from_cache += 1
                _notify_text_processed(on_text_processed, "cache")
            elif dry_run:
                stats.translated += 1
                _notify_text_processed(on_text_processed, "dry_run")
            else:
                stats.translated += 1
                _notify_text_processed(on_text_processed, "translated")
        except Exception as exc:
            stats.errors.append(str(exc))
            _notify_text_processed(on_text_processed, "error")
            if on_error:
                on_error(exc)
            if fail_fast:
                raise

    return soup.encode(formatter="minimal"), stats


def translate_text(
    text: str,
    translator: Translator,
    cache: TranslationCache,
    source: str,
    target: str,
    glossary: Glossary | None = None,
    dry_run: bool = False,
    chunk_limit: int = 3000,
) -> tuple[str, bool]:
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    core = text.strip()
    if not core:
        return text, False

    cached = cache.get(core, source, target)
    if cached is not None:
        return leading + apply_glossary(cached, glossary) + trailing, True

    if dry_run:
        return text, False

    translated_chunks = [
        translator.translate(chunk, source, target)
        for chunk in split_text(core, limit=chunk_limit)
    ]
    translated = "".join(translated_chunks)
    cache.set(core, translated, source, target)
    translated = apply_glossary(translated, glossary)
    return leading + translated + trailing, False


def _is_visible_text_node(text_node: NavigableString) -> bool:
    if isinstance(text_node, (Comment, Declaration, Doctype, ProcessingInstruction)):
        return False

    parent = text_node.parent
    while parent is not None and getattr(parent, "name", None):
        if str(parent.name).lower() in IGNORED_TAGS:
            return False
        parent = parent.parent
    return True


def _notify_text_processed(callback: TextProgressCallback | None, status: str) -> None:
    if callback:
        callback(status)
