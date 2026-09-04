from types import SimpleNamespace

import pytest

from content_studio.modules.commerce.service import build_story_brief, derive_story_hook

pytestmark = pytest.mark.asyncio


async def test_derive_story_hook_takes_first_sentence() -> None:
    caption = "Cozy nights start here. Light one candle and let the evening slow down."
    assert derive_story_hook(caption) == "Cozy nights start here."


async def test_derive_story_hook_clips_a_long_first_sentence() -> None:
    caption = "This is a genuinely very long first sentence with no punctuation break at all here"
    hook = derive_story_hook(caption, max_length=30)
    assert len(hook) <= 30
    assert hook.endswith("…")


async def test_derive_story_hook_keeps_a_short_caption_as_is() -> None:
    assert derive_story_hook("Whiskey Caramel is back!") == "Whiskey Caramel is back!"


async def test_build_story_brief_strips_size_suffix_and_never_includes_a_link() -> None:
    """Stories can't carry a real clickable link (no sticker support via
    Instagram's Content Publishing API), and burning a URL into
    AI-rendered pixels isn't reliable either — so the brief never includes
    one, even when the product has a permalink. The link lives in the
    post's own caption instead (see _build_text_brief)."""
    product = SimpleNamespace(
        title="Whiskey Caramel 200γρ.",
        raw_payload={"permalink": "https://ceri.gr/shop/wax-melts/whiskey-caramel/"},
    )

    brief = build_story_brief(product, "Whiskey Caramel is back!")

    assert "200γρ" not in brief
    assert "Whiskey Caramel" in brief
    assert "https://ceri.gr" not in brief


async def test_build_story_brief_handles_missing_permalink() -> None:
    product = SimpleNamespace(title="Lavender Fields", raw_payload={})

    brief = build_story_brief(product, "Relax into lavender.")

    assert "Lavender Fields" in brief
    assert "Relax into lavender." in brief


async def test_build_story_brief_excludes_the_quoted_collection_label() -> None:
    product = SimpleNamespace(
        title='Mistral "Artwood Collection" Χειροποίητο Κερί Σόγιας 200γρ.', raw_payload={},
    )

    brief = build_story_brief(product, "Mistral is back!")

    assert "Artwood Collection" not in brief
    assert "Mistral" in brief
