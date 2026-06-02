from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction

from .cache import CacheKey, TranslationCache
from .chunking import split_text
from .domain import LanguagePair
from .glossary import Glossary, apply_glossary
from .translator import Translator


IGNORED_TAGS = {"script", "style", "code", "pre", "kbd", "samp", "svg", "math"}
PROTECTED_PLACEHOLDER_PREFIX = "__AYVU_PROTECTED_"
PROTECTED_PLACEHOLDER_SUFFIX = "__"
TextProgressCallback = Callable[[str], None]


SPECIAL_TERM_PATTERNS = (
    re.compile(r"`[^`\n]+`"),
    re.compile(r"\{\{[^{}\n]+\}\}"),
    re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}"),
    re.compile(r"%(?:\([A-Za-z_][A-Za-z0-9_]*\))?[sd]"),
    re.compile(r"(?m)(?<!\S)(?:[$#>]\s*)[^\n]+"),
    re.compile(
        r"(?<![\w-])"
        r"(?:ayvu|uv|git|docker|pip|python3?|pytest|curl|wget|npm|node|cargo|poetry)"
        r"(?:\s+(?:[^\s`<>(),;!?]+))+",
    ),
    re.compile(r"https?://[^\s`<>()\"']+"),
    re.compile(r"(?<![\w./-])(?:~|\.{1,2})?/[^\s`<>()\"']+"),
    re.compile(r"(?<![\w./-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+"),
    re.compile(r"(?<![\w./-])[A-Za-z]:\\[^\s`<>()\"']+"),
    re.compile(r"(?<![\w.-])v?\d+\.\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?\b"),
    re.compile(r"(?<!\w)--?[A-Za-z][A-Za-z0-9-]*(?:=[^\s`<>()]+)?"),
    re.compile(r"(?<!\w)\$[A-Z_][A-Z0-9_]*\b"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\(\)"),
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]*\b"),
    re.compile(r"\b[A-Za-z]+[A-Z][A-Za-z0-9]*\b"),
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b"),
)


@dataclass(frozen=True)
class ProtectedSpan:
    start: int
    end: int


@dataclass(frozen=True)
class ProtectedText:
    text: str
    terms: tuple[tuple[str, str], ...] = ()

    def restore(self, translated: str) -> str:
        for placeholder, original in self.terms:
            translated = translated.replace(placeholder, original)
        return translated


@dataclass
class HtmlTranslationStats:
    translated: int = 0
    from_cache: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TextParts:
    leading: str
    core: str
    trailing: str

    @classmethod
    def from_text(cls, text: str) -> "TextParts":
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()) :]
        return cls(leading=leading, core=text.strip(), trailing=trailing)

    def restore(self, core: str) -> str:
        return self.leading + core + self.trailing


@dataclass(frozen=True)
class TextTranslationResult:
    text: str
    from_cache: bool = False


def extract_visible_text(html: str | bytes) -> list[str]:
    soup = BeautifulSoup(html, "lxml-xml")
    return [str(text_node) for text_node in _visible_text_nodes(soup) if str(text_node).strip()]


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
        if not _is_translatable_text_node(text_node):
            stats.skipped += 1
            continue

        original = str(text_node)

        try:
            result = translate_text(
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
                text_node.replace_with(NavigableString(result.text))
            _record_success(stats, result.from_cache, dry_run, on_text_processed)
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
) -> TextTranslationResult:
    parts = TextParts.from_text(text)
    if not parts.core:
        return TextTranslationResult(text=text)

    language_pair = LanguagePair(source=source, target=target)
    cache_key = CacheKey(text=parts.core, language_pair=language_pair)
    cached = cache.get(cache_key)
    if cached is not None:
        return TextTranslationResult(text=parts.restore(apply_glossary(cached, glossary)), from_cache=True)

    if dry_run:
        return TextTranslationResult(text=text)

    protected = _protect_special_terms(parts.core)
    translated_chunks = [
        translator.translate(chunk, source, target)
        for chunk in split_text(protected.text, limit=chunk_limit)
    ]
    translated = protected.restore("".join(translated_chunks))
    cache.set(cache_key, translated)
    translated = apply_glossary(translated, glossary)
    return TextTranslationResult(text=parts.restore(translated))


def _visible_text_nodes(soup: BeautifulSoup) -> list[NavigableString]:
    return [text_node for text_node in soup.find_all(string=True) if _is_visible_text_node(text_node)]


def _is_translatable_text_node(text_node: NavigableString) -> bool:
    if not _is_visible_text_node(text_node):
        return False
    return bool(str(text_node).strip())


def _is_visible_text_node(text_node: NavigableString) -> bool:
    if isinstance(text_node, (Comment, Declaration, Doctype, ProcessingInstruction)):
        return False

    parent = text_node.parent
    while parent is not None and getattr(parent, "name", None):
        if str(parent.name).lower() in IGNORED_TAGS:
            return False
        parent = parent.parent
    return True


def _protect_special_terms(text: str) -> ProtectedText:
    spans = _special_term_spans(text)
    if not spans:
        return ProtectedText(text=text)

    protected_parts: list[str] = []
    terms: list[tuple[str, str]] = []
    cursor = 0
    for span in spans:
        placeholder = _protected_placeholder(len(terms))
        protected_parts.append(text[cursor : span.start])
        protected_parts.append(placeholder)
        terms.append((placeholder, text[span.start : span.end]))
        cursor = span.end

    protected_parts.append(text[cursor:])
    return ProtectedText(text="".join(protected_parts), terms=tuple(terms))


def _special_term_spans(text: str) -> list[ProtectedSpan]:
    spans: list[ProtectedSpan] = []
    for pattern in SPECIAL_TERM_PATTERNS:
        for match in pattern.finditer(text):
            span = _clean_match_span(text, match.start(), match.end())
            if span is None or _overlaps_any(span, spans):
                continue
            spans.append(span)
    return sorted(spans, key=lambda span: span.start)


def _clean_match_span(text: str, start: int, end: int) -> ProtectedSpan | None:
    while start < end and text[start].isspace():
        start += 1
    while start < end and text[end - 1] in ".,;:!?":
        end -= 1
    while (
        start < end
        and text[end - 1] in ")]}"
        and _has_unmatched_closer(text[start:end], text[end - 1])
    ):
        end -= 1
    if start >= end:
        return None
    return ProtectedSpan(start=start, end=end)


def _has_unmatched_closer(value: str, closer: str) -> bool:
    opener = {")": "(", "]": "[", "}": "{"}[closer]
    return value.count(closer) > value.count(opener)


def _overlaps_any(candidate: ProtectedSpan, spans: list[ProtectedSpan]) -> bool:
    return any(candidate.start < span.end and candidate.end > span.start for span in spans)


def _protected_placeholder(index: int) -> str:
    return f"{PROTECTED_PLACEHOLDER_PREFIX}{index}{PROTECTED_PLACEHOLDER_SUFFIX}"


def _notify_text_processed(callback: TextProgressCallback | None, status: str) -> None:
    if callback:
        callback(status)


def _record_success(
    stats: HtmlTranslationStats,
    used_cache: bool,
    dry_run: bool,
    on_text_processed: TextProgressCallback | None,
) -> None:
    if used_cache:
        stats.from_cache += 1
        _notify_text_processed(on_text_processed, "cache")
        return

    stats.translated += 1
    if dry_run:
        _notify_text_processed(on_text_processed, "dry_run")
        return
    _notify_text_processed(on_text_processed, "translated")
