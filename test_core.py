"""
Tests for core.py. Not comprehensive - covers specific behavior that's
broken once and worth guarding against regressing, added when a bug is
found rather than upfront. Hits the real Anthropic API (no mocking) -
these are slow (seconds) and cost real tokens, so keep the list short
and deliberate rather than exhaustive.

Run with: python3 -m pytest test_core.py -v
"""

import core

HAWAIIAN_POEM = "O ke au i kahuli wela ka honua\nO ke au i kahuli lole ka lani\nO ke au i kukaiaka ka lā"


def test_text_mode_reports_detected_language():
    """Expression mode has always reported the detected/given source
    language as a {"type": "language", ...} event (see
    _extract_language_event in core.py), rendered as a badge in the UI.
    Text mode (full passages, e.g. this Hawaiian poem - auto-detect,
    no source_lang given) never did - found live when a user noticed
    the language badge stayed empty for a translated poem. Text mode
    should report it too, for the same reason expression mode does:
    the user should be able to see what the tool identified the source
    as, not just get a bare translation."""
    events = list(core.stream_translate(HAWAIIAN_POEM, None, "German", mode="text"))
    language_events = [e for e in events if e["type"] == "language"]
    assert language_events, "text mode produced no 'language' event at all"
    assert language_events[0]["name"], "language event's name was empty"
