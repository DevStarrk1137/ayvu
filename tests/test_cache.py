from ayvu.cache import CacheKey, TranslationCache
from ayvu.domain import LanguagePair


def _cache_key(text: str, source: str = "en", target: str = "pt") -> CacheKey:
    return CacheKey(text=text, language_pair=LanguagePair(source=source, target=target))


def test_cache_round_trip(tmp_path):
    cache_path = tmp_path / "translations.sqlite"
    with TranslationCache(cache_path) as cache:
        key = _cache_key("Hello")

        assert cache.get(key) is None
        cache.set(key, "Olá")
        assert cache.get(key) == "Olá"


def test_cache_is_language_specific(tmp_path):
    cache_path = tmp_path / "translations.sqlite"
    with TranslationCache(cache_path) as cache:
        cache.set(_cache_key("Hello", "en", "pt"), "Olá")

        assert cache.get(_cache_key("Hello", "en", "es")) is None


def test_cache_writable_check_does_not_persist_probe(tmp_path):
    cache_path = tmp_path / "translations.sqlite"
    with TranslationCache(cache_path) as cache:
        cache.verify_writable()

        assert cache.get(_cache_key("__ayvu_cache_write_check__", "ayvu", "ayvu")) is None
