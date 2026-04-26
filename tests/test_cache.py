from epub_local_translator.cache import TranslationCache


def test_cache_round_trip(tmp_path):
    cache_path = tmp_path / "translations.sqlite"
    with TranslationCache(cache_path) as cache:
        assert cache.get("Hello", "en", "pt") is None
        cache.set("Hello", "Olá", "en", "pt")
        assert cache.get("Hello", "en", "pt") == "Olá"


def test_cache_is_language_specific(tmp_path):
    cache_path = tmp_path / "translations.sqlite"
    with TranslationCache(cache_path) as cache:
        cache.set("Hello", "Olá", "en", "pt")
        assert cache.get("Hello", "en", "es") is None

