import difflib

_MIN_DELETION_LENGTH = 2
_MAX_DELETION_LENGTH = 200


def extract_meaningful_deletions(original: str, edited: str) -> list[str]:
    """What did the user remove when editing AI-generated text into
    `edited`? Used both to persist a "learned deletion" (fed into future
    generation briefs) and to strip the same substrings from sibling
    not-yet-reviewed items right now. Deliberately bounded: shorter than
    2 chars is noise (a stray space/punctuation fix), longer than 200
    means the user rewrote the draft rather than deleted a phrase — that's
    not a reusable "avoid this" signal, it's a whole-draft dislike."""
    matcher = difflib.SequenceMatcher(None, original, edited)
    deletions = []
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag not in ("delete", "replace"):
            continue
        span = original[i1:i2].strip()
        if _MIN_DELETION_LENGTH <= len(span) <= _MAX_DELETION_LENGTH:
            deletions.append(span)
    return deletions
