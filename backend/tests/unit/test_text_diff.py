from content_studio.modules.creation.text_diff import extract_meaningful_deletions


def test_extracts_removed_phrase() -> None:
    original = "Delight in our candle. It smells amazing and burns cleanly."
    edited = "Delight in our candle. It burns cleanly."
    deletions = extract_meaningful_deletions(original, edited)
    assert any("smells amazing" in d for d in deletions)


def test_extracts_removed_emoji() -> None:
    original = "New arrivals just dropped! 🎉🔥"
    edited = "New arrivals just dropped!"
    deletions = extract_meaningful_deletions(original, edited)
    assert any(d.strip() for d in deletions)


def test_excludes_tiny_noise() -> None:
    original = "Candle,  handmade."
    edited = "Candle, handmade."  # just collapsed a double space
    deletions = extract_meaningful_deletions(original, edited)
    assert deletions == []


def test_excludes_near_total_rewrite() -> None:
    original = "A" * 250
    edited = "completely different text"
    deletions = extract_meaningful_deletions(original, edited)
    assert deletions == []


def test_no_changes_returns_empty() -> None:
    text = "Same caption, no edits made."
    assert extract_meaningful_deletions(text, text) == []
