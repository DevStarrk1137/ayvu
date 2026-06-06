from ayvu.cache import CacheKey, TranslationCache
from ayvu.domain import LanguagePair
from ayvu.glossary import (
    GLOSSARY_RULE_FORBIDDEN,
    GLOSSARY_RULE_PRESERVE,
    GLOSSARY_RULE_TRANSLATE,
    Glossary,
    GlossaryEntry,
)
from ayvu.html_translate import apply_reviewed_html, extract_visible_text, translate_html, translate_text
from ayvu.translator import Translator


class FakeTranslator(Translator):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def translate(self, text: str, source: str, target: str) -> str:
        self.calls.append(text)
        replacements = {
            "Any programming book with": "Qualquer livro de programação com",
            "Patterns": "Patterns",
            "in its name.": "no nome.",
            "Keep me": "Mantenha-me",
        }
        return replacements.get(text, f"PT:{text}")


def test_translate_html_preserves_tags(tmp_path):
    html = '<html><body><p class="calibre1">Any programming book with <em>Patterns</em> in its name.</p></body></html>'
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt", glossary={"Patterns": "Patterns"})

    result = output.decode("utf-8")
    # The paragraph is translated as a single block, keeping inline tags intact.
    assert '<p class="calibre1">' in result
    assert "<em>Patterns</em>" in result
    assert stats.translated == 1
    assert len(translator.calls) == 1
    # The block is sent as one unit, with inline tags replaced by placeholders.
    sent = translator.calls[0]
    assert "Any programming book with" in sent
    assert "Patterns" in sent
    assert "in its name." in sent
    assert "<em>" not in sent
    assert "__AYVU_PROTECTED_" in sent


def test_translate_html_ignores_script_style_code_pre(tmp_path):
    html = """
    <html><body>
      <p>Keep me</p>
      <script>Keep me</script>
      <style>.x { content: "Keep me"; }</style>
      <code>Keep me</code>
      <pre>Keep me</pre>
    </body></html>
    """
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert "<p>Mantenha-me</p>" in result
    assert "<script>Keep me</script>" in result
    assert "<code>Keep me</code>" in result
    assert "<pre>Keep me</pre>" in result
    assert translator.calls == ["Keep me"]
    assert stats.translated == 1


def test_translate_html_uses_cache(tmp_path):
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_html("<html><body><p>Keep me</p></body></html>", translator, cache, "en", "pt")
        output, stats = translate_html("<html><body><p>Keep me</p></body></html>", translator, cache, "en", "pt")

    assert "Mantenha-me" in output.decode("utf-8")
    assert stats.from_cache == 1
    assert translator.calls == ["Keep me"]


def test_translate_text_cache_only_marks_missing_without_calling_translator(tmp_path):
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        result = translate_text(
            "Keep me",
            translator=translator,
            cache=cache,
            source="en",
            target="pt",
            cache_only=True,
        )

    assert result.missing
    assert not result.from_cache
    assert result.text == "Keep me"
    assert translator.calls == []


def test_translate_text_cache_only_uses_cache_when_available(tmp_path):
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        cache.set(
            CacheKey(text="Keep me", language_pair=LanguagePair(source="en", target="pt")),
            "Mantenha-me",
        )
        result = translate_text(
            "Keep me",
            translator=translator,
            cache=cache,
            source="en",
            target="pt",
            cache_only=True,
        )

    assert result.from_cache
    assert not result.missing
    assert result.text == "Mantenha-me"
    assert translator.calls == []


def test_translate_html_cache_only_keeps_missing_text_and_reports_it(tmp_path):
    translator = FakeTranslator()
    html = "<html><body><p>Keep me</p><p>Hello reader.</p></body></html>"
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        cache.set(
            CacheKey(text="Keep me", language_pair=LanguagePair(source="en", target="pt")),
            "Mantenha-me",
        )
        output, stats = translate_html(html, translator, cache, "en", "pt", cache_only=True)

    decoded = output.decode("utf-8")
    assert "Mantenha-me" in decoded
    assert "Hello reader." in decoded
    assert stats.from_cache == 1
    assert stats.missing == 1
    assert stats.translated == 0
    assert stats.missing_texts == ["Hello reader."]
    assert translator.calls == []


def test_translate_html_reports_review_segments_as_visible_text(tmp_path):
    html = '<html><body><p>Hello <a href="chapter.xhtml">reader</a>.</p></body></html>'
    segments = []
    translator = FakeTranslator()

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_html(
            html,
            translator,
            cache,
            "en",
            "pt",
            on_segment_translated=segments.append,
        )

    assert len(segments) == 1
    assert segments[0].kind == "text"
    assert segments[0].original == "Hello reader."
    assert segments[0].translated == "PT:Hello reader."
    assert not segments[0].from_cache


def test_translate_html_reports_review_segments_from_cache(tmp_path):
    segments = []
    translator = FakeTranslator()

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        cache.set(
            CacheKey(text="Keep me", language_pair=LanguagePair(source="en", target="pt")),
            "Mantenha-me",
        )
        translate_html(
            "<html><body><p>Keep me</p></body></html>",
            translator,
            cache,
            "en",
            "pt",
            on_segment_translated=segments.append,
        )

    assert len(segments) == 1
    assert segments[0].original == "Keep me"
    assert segments[0].translated == "Mantenha-me"
    assert segments[0].from_cache
    assert translator.calls == []


def test_translate_text_result_reports_cache_hit(tmp_path):
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        cache_key = CacheKey(text="Keep me", language_pair=LanguagePair(source="en", target="pt"))
        cache.set(cache_key, "Mantenha-me")

        result = translate_text(" Keep me ", translator, cache, "en", "pt")

    assert result.text == " Mantenha-me "
    assert result.from_cache
    assert translator.calls == []


def test_translate_text_applies_advanced_glossary_rules_to_cache_hits(tmp_path):
    translator = FakeTranslator()
    glossary = Glossary(
        [
            GlossaryEntry("Observer", GLOSSARY_RULE_PRESERVE),
            GlossaryEntry("Game Loop", GLOSSARY_RULE_TRANSLATE, "loop de jogo"),
        ]
    )

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        cache_key = CacheKey(text="Keep me", language_pair=LanguagePair(source="en", target="pt"))
        cache.set(cache_key, "observer uses the Game Loop")

        result = translate_text("Keep me", translator, cache, "en", "pt", glossary=glossary)

    assert result.text == "Observer uses the loop de jogo"
    assert result.from_cache
    assert translator.calls == []


def test_translate_text_reports_glossary_usage_from_cache_hits(tmp_path):
    translator = FakeTranslator()
    glossary = Glossary(
        [
            GlossaryEntry("Observer", GLOSSARY_RULE_PRESERVE, required=True),
            GlossaryEntry("Game Loop", GLOSSARY_RULE_TRANSLATE, "loop de jogo", required=True),
            GlossaryEntry("AntiPattern", GLOSSARY_RULE_FORBIDDEN),
        ]
    )

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        cache_key = CacheKey(text="Keep me", language_pair=LanguagePair(source="en", target="pt"))
        cache.set(cache_key, "observer uses the Game Loop and AntiPattern")

        result = translate_text("Keep me", translator, cache, "en", "pt", glossary=glossary)

    assert result.glossary_usage.applied_terms == {"Game Loop": 1, "Observer": 1}
    assert result.glossary_usage.required_terms_present == {"Game Loop": 1, "Observer": 1}
    assert result.glossary_usage.forbidden_terms_found == {"AntiPattern": 1}


def test_translate_html_accumulates_glossary_usage(tmp_path):
    html = "<html><body><p>Keep me</p><p>Keep me</p></body></html>"
    translator = FakeTranslator()
    glossary = Glossary(
        [
            GlossaryEntry("Mantenha-me", GLOSSARY_RULE_PRESERVE, required=True),
        ]
    )

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        _output, stats = translate_html(html, translator, cache, "en", "pt", glossary=glossary)

    assert stats.glossary_usage.applied_terms == {"Mantenha-me": 2}
    assert stats.glossary_usage.required_terms_present == {"Mantenha-me": 2}


def test_translate_text_protects_special_terms_before_translating(tmp_path):
    text = (
        "Use `uv run ayvu --help`, open https://example.com/docs, edit "
        "src/ayvu/html_translate.py, run git status, keep v1.2.0, call "
        "translate_text(), and pass CacheKey."
    )
    protected_terms = [
        "`uv run ayvu --help`",
        "https://example.com/docs",
        "src/ayvu/html_translate.py",
        "git status",
        "v1.2.0",
        "translate_text()",
        "CacheKey",
    ]

    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        result = translate_text(text, translator, cache, "en", "pt")

    translated_input = translator.calls[0]
    for term in protected_terms:
        assert term not in translated_input
        assert term in result.text
    assert "__AYVU_PROTECTED_" in translated_input
    assert "__AYVU_PROTECTED_" not in result.text


def test_translate_text_caches_restored_protected_terms(tmp_path):
    text = "Call translate_text() at https://example.com/docs."
    translator = FakeTranslator()

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        first_result = translate_text(text, translator, cache, "en", "pt")
        second_result = translate_text(text, translator, cache, "en", "pt")

    assert first_result.text == "PT:Call translate_text() at https://example.com/docs."
    assert second_result.text == first_result.text
    assert second_result.from_cache
    assert translator.calls == ["Call __AYVU_PROTECTED_0__ at __AYVU_PROTECTED_1__."]


def test_translate_html_does_not_translate_doctype_or_comments(tmp_path):
    html = '<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html><html><body><!-- Keep me --><p>Keep me</p></body></html>'
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert "<!DOCTYPE html>" in result
    assert "<!-- Keep me -->" in result
    assert "<p>Mantenha-me</p>" in result
    assert translator.calls == ["Keep me"]
    assert stats.translated == 1


def test_extract_visible_text_uses_translation_visibility_rules():
    html = """
    <html><body>
      <!-- Keep me out -->
      <p>Keep me</p>
      <script>Keep me out</script>
      <style>.x { content: "Keep me out"; }</style>
      <code>Keep me out</code>
      <pre>Keep me out</pre>
      <svg><text>Keep me out</text></svg>
      <math><mi>Keep me out</mi></math>
    </body></html>
    """

    assert extract_visible_text(html) == ["Keep me"]


def test_translate_html_translates_sentence_split_by_tags_as_one_unit(tmp_path):
    html = "<html><body><p>This is <em>very</em> important here.</p></body></html>"
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert "<em>very</em>" in result
    assert stats.translated == 1
    # The whole sentence reaches the translator once, not fragment by fragment.
    assert len(translator.calls) == 1
    sent = translator.calls[0]
    assert "This is" in sent and "important here." in sent
    assert "<em>" not in sent


def test_translate_html_preserves_link_attributes_in_block(tmp_path):
    html = '<html><body><p>Read <a href="ch1.xhtml" id="k1">chapter one</a> now.</p></body></html>'
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, _stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert '<a href="ch1.xhtml" id="k1">' in result
    assert "</a>" in result
    assert len(translator.calls) == 1
    assert "ch1.xhtml" not in translator.calls[0]


def test_translate_html_preserves_nested_inline_tags(tmp_path):
    html = "<html><body><p>A <strong>very <em>bold</em></strong> idea.</p></body></html>"
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert "<strong>" in result
    assert "<em>bold</em>" in result
    assert "</strong>" in result
    assert stats.translated == 1
    assert len(translator.calls) == 1


def test_translate_html_keeps_inline_code_opaque_in_block(tmp_path):
    html = "<html><body><p>Run <code>build()</code> before release.</p></body></html>"
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert "<code>build()</code>" in result
    assert stats.translated == 1
    assert len(translator.calls) == 1
    # The code element is sent as an opaque placeholder, never as translatable text.
    assert "build()" not in translator.calls[0]


def test_translate_html_preserves_void_tags_in_block(tmp_path):
    html = "<html><body><p>line one<br/>line two</p></body></html>"
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert "<br/>" in result
    assert stats.translated == 1
    assert len(translator.calls) == 1


def test_translate_html_caches_block_with_tags(tmp_path):
    html = "<html><body><p>Hello <em>world</em></p></body></html>"
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_html(html, translator, cache, "en", "pt")
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert "<em>world</em>" in result
    assert stats.from_cache == 1
    assert len(translator.calls) == 1


def test_translate_html_does_not_reuse_old_per_node_cache_for_block(tmp_path):
    html = "<html><body><p>Hello <em>world</em></p></body></html>"
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        # Simulate a stale per-text-node cache entry from the old translation flow.
        stale_key = CacheKey(text="world", language_pair=LanguagePair(source="en", target="pt"))
        cache.set(stale_key, "MUNDO_STALE")

        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    # The block has its own cache key, so the stale per-node entry is never used.
    assert "MUNDO_STALE" not in result
    assert "<em>world</em>" in result
    assert stats.from_cache == 0
    assert stats.translated == 1
    assert len(translator.calls) == 1


def test_translate_html_translates_loose_text_with_block_siblings(tmp_path):
    html = "<html><body>Intro <p>Para</p> outro</body></html>"
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    # Loose text around a block element must not be lost.
    assert "PT:Intro" in result
    assert "PT:Para" in result
    assert "PT:outro" in result
    assert stats.translated == 3


def test_translate_html_protects_special_terms_inside_block(tmp_path):
    html = "<html><body><p>Open https://example.com/docs with <em>care</em>.</p></body></html>"
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, _stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert "https://example.com/docs" in result
    assert "<em>care</em>" in result
    assert len(translator.calls) == 1
    # Both the URL and the inline tag are hidden behind placeholders during translation.
    assert "https://example.com/docs" not in translator.calls[0]
    assert "<em>" not in translator.calls[0]


def test_translate_html_preserves_image_alt_by_default(tmp_path):
    html = '<html><body><p><img src="cover.png" alt="A red house" /></p></body></html>'
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(html, translator, cache, "en", "pt")

    result = output.decode("utf-8")
    assert 'alt="A red house"' in result
    assert "A red house" not in translator.calls
    assert stats.alt_translated == 0


def test_translate_html_translates_image_alt_when_enabled(tmp_path):
    html = '<html><body><p><img src="cover.png" alt="A red house" /></p></body></html>'
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(
            html, translator, cache, "en", "pt", translate_alt_text=True
        )

    result = output.decode("utf-8")
    # The alt text is translated while src and the image element are preserved.
    assert 'alt="PT:A red house"' in result
    assert 'src="cover.png"' in result
    assert "A red house" in translator.calls
    assert stats.alt_translated == 1
    assert stats.translated == 1


def test_translate_html_reports_review_segments_for_image_alt(tmp_path):
    html = '<html><body><p><img src="cover.png" alt="A red house" /></p></body></html>'
    segments = []
    translator = FakeTranslator()

    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        translate_html(
            html,
            translator,
            cache,
            "en",
            "pt",
            translate_alt_text=True,
            on_segment_translated=segments.append,
        )

    assert len(segments) == 1
    assert segments[0].kind == "alt"
    assert segments[0].original == "A red house"
    assert segments[0].translated == "PT:A red house"


def test_translate_html_skips_empty_or_missing_image_alt(tmp_path):
    html = (
        '<html><body><p>'
        '<img src="decor.png" alt="" />'
        '<img src="logo.png" />'
        "</p></body></html>"
    )
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        output, stats = translate_html(
            html, translator, cache, "en", "pt", translate_alt_text=True
        )

    result = output.decode("utf-8")
    assert 'alt=""' in result
    assert translator.calls == []
    assert stats.alt_translated == 0


def test_translate_html_uses_cache_for_image_alt(tmp_path):
    html = '<html><body><p><img src="cover.png" alt="A red house" /></p></body></html>'
    translator = FakeTranslator()
    with TranslationCache(tmp_path / "cache.sqlite") as cache:
        cache.set(
            CacheKey(text="A red house", language_pair=LanguagePair(source="en", target="pt")),
            "Uma casa vermelha",
        )
        output, stats = translate_html(
            html, translator, cache, "en", "pt", translate_alt_text=True
        )

    result = output.decode("utf-8")
    assert 'alt="Uma casa vermelha"' in result
    assert translator.calls == []
    assert stats.alt_translated == 1
    assert stats.from_cache == 1


def _resolver(reviewed: dict[int, str], seen: list[tuple[int, str, str]] | None = None):
    def resolve(index: int, kind: str, original: str):
        if seen is not None:
            seen.append((index, kind, original))
        return reviewed.get(index)

    return resolve


def test_apply_reviewed_html_replaces_segment_text_by_index():
    html = "<html><body><p>Hello reader.</p><p>Second one.</p></body></html>"
    seen: list[tuple[int, str, str]] = []

    output, stats = apply_reviewed_html(html, _resolver({1: "Ola leitor."}, seen))

    result = output.decode("utf-8")
    assert "Ola leitor." in result
    assert "Second one." in result  # left untouched (resolver returned None)
    assert stats.applied == 1
    assert seen == [(1, "text", "Hello reader."), (2, "text", "Second one.")]


def test_apply_reviewed_html_flattens_inline_tags_in_replaced_segment():
    html = '<html><body><p>Hello <a href="ch.xhtml"><em>reader</em></a>.</p></body></html>'

    output, stats = apply_reviewed_html(html, _resolver({1: "Ola leitor."}))

    result = output.decode("utf-8")
    assert "Ola leitor." in result
    assert "<a" not in result
    assert "<em>" not in result
    assert stats.applied == 1


def test_apply_reviewed_html_escapes_special_characters():
    html = "<html><body><p>Tom and Jerry</p></body></html>"

    output, _stats = apply_reviewed_html(html, _resolver({1: "Tom & Jerry <3"}))

    result = output.decode("utf-8")
    assert "Tom &amp; Jerry &lt;3" in result


def test_apply_reviewed_html_applies_image_alt_after_text_runs():
    html = (
        '<html><body><p>Hello reader.</p>'
        '<p><img src="cover.png" alt="A red house" /></p></body></html>'
    )
    seen: list[tuple[int, str, str]] = []

    output, stats = apply_reviewed_html(html, _resolver({2: "Uma casa vermelha"}, seen))

    result = output.decode("utf-8")
    assert 'alt="Uma casa vermelha"' in result
    assert stats.applied == 1
    assert seen == [(1, "text", "Hello reader."), (2, "alt", "A red house")]
