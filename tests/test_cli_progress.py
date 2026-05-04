import pytest

from ayvu.cli_progress import TextProgressCounters


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
