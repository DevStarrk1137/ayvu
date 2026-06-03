from __future__ import annotations

import copy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, NavigableString, ProcessingInstruction

from .cache import CacheKey, TranslationCache
from .chunking import split_text
from .domain import LanguagePair
from .glossary import Glossary, GlossaryUsage, apply_glossary_with_usage
from .translator import Translator


IGNORED_TAGS = {"script", "style", "code", "pre", "kbd", "samp", "svg", "math"}
# Ignored tags that may appear inline inside a block. Their whole markup is kept
# untranslated as an opaque token instead of acting as a block boundary.
IGNORED_INLINE_TAGS = {"code", "kbd", "samp"}
# Inline tags whose text is translated together with the surrounding block. The
# tags themselves are replaced by neutral placeholders and restored afterwards.
INLINE_TAGS = {
    "a", "abbr", "b", "bdi", "bdo", "br", "cite", "data", "del", "dfn", "em",
    "i", "ins", "mark", "q", "rp", "rt", "ruby", "s", "small", "span", "strike",
    "strong", "sub", "sup", "time", "u", "var", "wbr",
}
PROTECTED_PLACEHOLDER_PREFIX = "__AYVU_PROTECTED_"
PROTECTED_PLACEHOLDER_SUFFIX = "__"
TAG_PLACEHOLDER_PREFIX = "__AYVU_TAG_"
TAG_PLACEHOLDER_SUFFIX = "__"
TAG_TOKEN_PATTERN = re.compile(r"__AYVU_TAG_(\d+)__")
TAG_MARKUP_SENTINEL = "AYVU_TAG_MARKUP_SENTINEL"
FRAGMENT_ROOT_TAG = "__ayvu_fragment_root__"
TextProgressCallback = Callable[[str], None]


SPECIAL_TERM_PATTERNS = (
    TAG_TOKEN_PATTERN,
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
    alt_translated: int = 0
    errors: list[str] = field(default_factory=list)
    glossary_usage: GlossaryUsage = field(default_factory=GlossaryUsage)


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
    glossary_usage: GlossaryUsage = field(default_factory=GlossaryUsage)


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
    translate_alt_text: bool = False,
) -> tuple[bytes, HtmlTranslationStats]:
    soup = BeautifulSoup(html, "lxml-xml")
    stats = HtmlTranslationStats()

    for run in _collect_translation_runs(soup):
        template, tag_markup = _build_block_template(run)
        if not _has_translatable_text(template):
            stats.skipped += 1
            continue

        try:
            result = translate_text(
                template,
                translator=translator,
                cache=cache,
                source=source,
                target=target,
                glossary=glossary,
                dry_run=dry_run,
                chunk_limit=chunk_limit,
            )
            if not dry_run:
                fragment = _expand_tag_tokens(escape(result.text), tag_markup)
                _replace_run(run, _parse_fragment_nodes(fragment))
            stats.glossary_usage.merge(result.glossary_usage)
            _record_success(stats, result.from_cache, dry_run, on_text_processed)
        except Exception as exc:
            stats.errors.append(str(exc))
            _notify_text_processed(on_text_processed, "error")
            if on_error:
                on_error(exc)
            if fail_fast:
                raise

    if translate_alt_text:
        _translate_image_alt_text(
            soup,
            translator=translator,
            cache=cache,
            source=source,
            target=target,
            glossary=glossary,
            dry_run=dry_run,
            fail_fast=fail_fast,
            chunk_limit=chunk_limit,
            stats=stats,
            on_error=on_error,
            on_text_processed=on_text_processed,
        )

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
        application = apply_glossary_with_usage(cached, glossary)
        return TextTranslationResult(
            text=parts.restore(application.text),
            from_cache=True,
            glossary_usage=application.usage,
        )

    if dry_run:
        return TextTranslationResult(text=text)

    protected = _protect_special_terms(parts.core)
    translated_chunks = [
        translator.translate(chunk, source, target)
        for chunk in split_text(protected.text, limit=chunk_limit)
    ]
    translated = protected.restore("".join(translated_chunks))
    cache.set(cache_key, translated)
    application = apply_glossary_with_usage(translated, glossary)
    return TextTranslationResult(text=parts.restore(application.text), glossary_usage=application.usage)


def _translate_image_alt_text(
    soup: BeautifulSoup,
    translator: Translator,
    cache: TranslationCache,
    source: str,
    target: str,
    glossary: Glossary | None,
    dry_run: bool,
    fail_fast: bool,
    chunk_limit: int,
    stats: HtmlTranslationStats,
    on_error: Callable[[Exception], None] | None,
    on_text_processed: TextProgressCallback | None,
) -> None:
    """Translate the ``alt`` text of ``img`` elements as plain text.

    Only the alternative description is translated; the image, its ``src`` and
    every other attribute are preserved. Reading text rendered inside the image
    (OCR) is intentionally out of scope.
    """
    for image in _image_elements(soup):
        alt = image.get("alt")
        if not isinstance(alt, str) or not alt.strip():
            continue
        try:
            result = translate_text(
                alt,
                translator=translator,
                cache=cache,
                source=source,
                target=target,
                glossary=glossary,
                dry_run=dry_run,
                chunk_limit=chunk_limit,
            )
            if not dry_run:
                image["alt"] = result.text
            stats.glossary_usage.merge(result.glossary_usage)
            stats.alt_translated += 1
            _record_success(stats, result.from_cache, dry_run, on_text_processed)
        except Exception as exc:
            stats.errors.append(str(exc))
            _notify_text_processed(on_text_processed, "error")
            if on_error:
                on_error(exc)
            if fail_fast:
                raise


def _image_elements(soup: BeautifulSoup) -> list:
    return [node for node in soup.find_all(True) if _tag_name(node) == "img"]


def _visible_text_nodes(soup: BeautifulSoup) -> list[NavigableString]:
    return [text_node for text_node in soup.find_all(string=True) if _is_visible_text_node(text_node)]


def _collect_translation_runs(element) -> list[list]:
    """Group consecutive inline siblings into translation runs.

    Block-level and ignored-block children act as boundaries; we recurse into
    them so their own inline content becomes separate runs. This keeps loose
    text mixed with block elements from being lost.
    """
    runs: list[list] = []
    current: list = []
    for child in list(element.children):
        if _is_run_member(child):
            current.append(child)
            continue
        if current:
            runs.append(current)
            current = []
        if _should_recurse_into(child):
            runs.extend(_collect_translation_runs(child))
    if current:
        runs.append(current)
    return runs


def _is_run_member(node) -> bool:
    if _is_special_string(node):
        return False
    if isinstance(node, NavigableString):
        return True
    name = _tag_name(node)
    if name in IGNORED_INLINE_TAGS:
        return True
    if name in INLINE_TAGS:
        return not _contains_block_descendant(node)
    return False


def _should_recurse_into(node) -> bool:
    name = _tag_name(node)
    return bool(name) and name not in IGNORED_TAGS


def _contains_block_descendant(node) -> bool:
    return any(
        _tag_name(descendant) not in INLINE_TAGS
        and _tag_name(descendant) not in IGNORED_INLINE_TAGS
        for descendant in node.find_all(True)
    )


def _build_block_template(run: list) -> tuple[str, list[str]]:
    parts: list[str] = []
    tag_markup: list[str] = []
    for node in run:
        _emit_template_node(node, parts, tag_markup)
    return "".join(parts), tag_markup


def _emit_template_node(node, parts: list[str], tag_markup: list[str]) -> None:
    if _is_special_string(node):
        parts.append(_register_tag_markup(tag_markup, str(node)))
        return
    if isinstance(node, NavigableString):
        parts.append(str(node))
        return
    if _tag_name(node) in IGNORED_INLINE_TAGS or _is_void_element(node):
        parts.append(_register_tag_markup(tag_markup, str(node)))
        return

    open_markup, close_markup = _split_tag_markup(node)
    parts.append(_register_tag_markup(tag_markup, open_markup))
    for child in list(node.children):
        _emit_template_node(child, parts, tag_markup)
    parts.append(_register_tag_markup(tag_markup, close_markup))


def _register_tag_markup(tag_markup: list[str], markup: str) -> str:
    placeholder = f"{TAG_PLACEHOLDER_PREFIX}{len(tag_markup)}{TAG_PLACEHOLDER_SUFFIX}"
    tag_markup.append(markup)
    return placeholder


def _split_tag_markup(node) -> tuple[str, str]:
    clone = copy.copy(node)
    clone.clear()
    clone.append(NavigableString(TAG_MARKUP_SENTINEL))
    open_markup, _, close_markup = str(clone).partition(TAG_MARKUP_SENTINEL)
    return open_markup, close_markup


def _has_translatable_text(template: str) -> bool:
    return bool(TAG_TOKEN_PATTERN.sub("", template).strip())


def _expand_tag_tokens(text: str, tag_markup: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 0 <= index < len(tag_markup):
            return tag_markup[index]
        return match.group(0)

    return TAG_TOKEN_PATTERN.sub(replace, text)


def _parse_fragment_nodes(fragment: str) -> list:
    soup = BeautifulSoup(f"<{FRAGMENT_ROOT_TAG}>{fragment}</{FRAGMENT_ROOT_TAG}>", "lxml-xml")
    root = soup.find(FRAGMENT_ROOT_TAG)
    if root is None:
        return [NavigableString(fragment)]
    return [child.extract() for child in list(root.children)]


def _replace_run(run: list, new_nodes: list) -> None:
    if not new_nodes:
        return
    anchor = run[0]
    for node in new_nodes:
        anchor.insert_before(node)
    for node in run:
        node.extract()


def _is_special_string(node) -> bool:
    return isinstance(node, (Comment, Declaration, Doctype, ProcessingInstruction))


def _is_void_element(node) -> bool:
    return not node.contents


def _tag_name(node) -> str:
    name = getattr(node, "name", None)
    return name.lower() if isinstance(name, str) else ""


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
