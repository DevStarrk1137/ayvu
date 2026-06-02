from ayvu.cache import CacheKey, TranslationCache
from ayvu.domain import LanguagePair
from ayvu.glossary import (
    GLOSSARY_RULE_FORBIDDEN,
    GLOSSARY_RULE_PRESERVE,
    GLOSSARY_RULE_TRANSLATE,
    Glossary,
    GlossaryEntry,
)
from ayvu.html_translate import extract_visible_text, translate_html, translate_text
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
