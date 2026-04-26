from ayvu.cache import TranslationCache
from ayvu.html_translate import translate_html
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
    assert '<p class="calibre1">' in result
    assert "<em>Patterns</em>" in result
    assert "Qualquer livro de programação com" in result
    assert "no nome." in result
    assert stats.translated == 3


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
