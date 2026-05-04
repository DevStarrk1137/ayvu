import pytest

from ayvu.cli_progress import TextProgressCounters, TranslationProgress


def test_text_progress_counters_track_known_statuses():
    counters = TextProgressCounters()

    counters.record("translated")
    counters.record("cache")
    counters.record("dry_run")
    counters.record("error")

    assert counters.processed == 4
    assert counters.new_count(dry_run=False) == 1
    assert counters.new_count(dry_run=True) == 1
    assert counters.cache == 1
    assert counters.error == 1


def test_text_progress_counters_reject_unknown_status():
    counters = TextProgressCounters()

    with pytest.raises(ValueError, match="Unknown text progress status"):
        counters.record("unknown")


def test_translation_progress_snapshot_tracks_partial_state():
    class FakeProgress:
        def add_task(self, _description: str, total: object = None) -> int:
            return 1

        def update(self, *_args: object, **_kwargs: object) -> None:
            return None

        def advance(self, *_args: object, **_kwargs: object) -> None:
            return None

    progress = TranslationProgress(FakeProgress(), dry_run=False)

    progress.chapter_started(1, 2, "chapter-one.xhtml")
    progress.text_processed("translated")
    progress.text_processed("cache")
    progress.chapter_done(1, 2, "chapter-one.xhtml", object())
    progress.chapter_started(2, 2, "chapter-two.xhtml")

    snapshot = progress.snapshot()

    assert snapshot.chapters_processed == 1
    assert snapshot.total_chapters == 2
    assert snapshot.current_chapter == "chapter-two.xhtml"
    assert snapshot.texts_processed == 2
    assert snapshot.texts_translated == 1
    assert snapshot.texts_from_cache == 1
