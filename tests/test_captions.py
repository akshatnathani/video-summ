from ingest.captions import (
    base_lang,
    build_transcript,
    choose_track,
    merge_cues,
    parse_json3,
    parse_timed_text,
    _clean,
    _dedupe_rolling,
)


def test_base_lang_strips_region():
    assert base_lang("en-US") == "en"
    assert base_lang("pt_BR") == "pt"
    assert base_lang(None) == ""


def test_clean_strips_tags_and_sound_cues():
    assert _clean("<i>hello</i> [music] world") == "hello world"
    assert _clean("a   b\nc") == "a b c"


def test_parse_json3_builds_cues_from_events():
    payload = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Hello "}, {"utf8": "world"}]},
            {"aAppend": 1, "segs": [{"utf8": "ignored"}]},
            {"tStartMs": 2000, "dDurationMs": 500, "segs": [{"utf8": "  "}]},  # blank -> dropped
        ]
    }
    cues = parse_json3(payload)
    assert len(cues) == 1
    start, end, text = cues[0]
    assert start == 0.0
    assert end == 1.0
    assert text == "Hello world"


def test_parse_timed_text_handles_vtt_cues():
    vtt = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.500\n"
        "Hello there\n\n"
        "00:00:03.000 --> 00:00:04.000\n"
        "Second cue\n"
    )
    cues = parse_timed_text(vtt)
    assert len(cues) == 2
    assert cues[0] == (1.0, 2.5, "Hello there")
    assert cues[1][2] == "Second cue"


def test_dedupe_rolling_drops_repeated_prefix():
    cues = [
        (0.0, 1.0, "the quick brown"),
        (1.0, 2.0, "quick brown fox"),
    ]
    out = _dedupe_rolling(cues)
    assert [c[2] for c in out] == ["the quick brown", "fox"]


def test_merge_cues_splits_on_gap():
    cues = [(0.0, 1.0, "Hello."), (5.0, 6.0, "Much later.")]
    merged = merge_cues(cues)
    assert len(merged) == 2
    assert merged[0]["text"] == "Hello."
    assert merged[1]["text"] == "Much later."


def test_merge_cues_joins_close_short_fragments():
    cues = [(0.0, 0.5, "Hi"), (0.5, 1.0, "there")]
    merged = merge_cues(cues)
    assert len(merged) == 1
    assert merged[0]["text"] == "Hi there"


def test_choose_track_prefers_manual_then_english():
    tracks = [
        {"lang": "fr", "base_lang": "fr", "kind": "auto"},
        {"lang": "en", "base_lang": "en", "kind": "auto"},
        {"lang": "es", "base_lang": "es", "kind": "manual"},
    ]
    picked = choose_track(tracks, video_lang=None)
    assert picked["kind"] == "manual"
    assert picked["lang"] == "es"


def test_choose_track_falls_back_to_auto_english():
    tracks = [
        {"lang": "fr", "base_lang": "fr", "kind": "auto"},
        {"lang": "en", "base_lang": "en", "kind": "auto"},
    ]
    picked = choose_track(tracks, video_lang=None)
    assert picked["lang"] == "en"


def test_choose_track_empty_returns_none():
    assert choose_track([], None) is None


def test_build_transcript_rejects_too_short_text():
    cues = [(0.0, 1.0, "Hi.")]
    assert build_transcript(cues, "en", 10.0) is None


def test_build_transcript_returns_segments_and_text():
    cues = [(0.0, 2.0, "This is a reasonably long opening sentence for the transcript.")]
    result = build_transcript(cues, "en", 2.0)
    assert result is not None
    assert result["source"] == "platform_captions"
    assert result["language"] == "en"
    assert len(result["segments"]) == 1
