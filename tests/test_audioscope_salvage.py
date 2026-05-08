from gski.audioscope_salvage import salvage_segments, LOOP_PLACEHOLDER


def seg(t, speaker="A", text="hello"):
    return {"s": speaker, "t": t, "x": text}


def test_salvage_passthrough_on_clean_segments():
    segments = [
        seg("00:00", text="hello everyone welcome to the meeting"),
        seg("00:10", text="today we will discuss the roadmap"),
    ]
    cleaned, modified = salvage_segments(segments)
    assert modified is False
    assert cleaned == segments


def test_salvage_truncates_intra_segment_word_loop():
    looped = "Да, сейчас, " + "на... " * 500 + "[incomprehensible]"
    segments = [
        seg("00:00", text="clean prefix content here"),
        seg("00:14", speaker="B", text=looped),
    ]
    cleaned, modified = salvage_segments(segments)
    assert modified is True
    assert len(cleaned) == 2
    # prefix segment intact
    assert cleaned[0]["x"] == "clean prefix content here"
    # looped segment: "Да, сейчас," preserved, loop replaced with placeholder
    assert cleaned[1]["s"] == "B"
    assert cleaned[1]["t"] == "00:14"
    assert "Да, сейчас" in cleaned[1]["x"]
    assert LOOP_PLACEHOLDER in cleaned[1]["x"]
    # no 5x repetition of 'на' left
    assert "на на на на на" not in cleaned[1]["x"].lower()
    assert "на... на... на... на... на..." not in cleaned[1]["x"]


def test_salvage_replaces_segment_that_is_entirely_loop():
    # Segment where the loop starts at position 0 — no usable prefix.
    looped = "na " * 1000
    segments = [
        seg("00:00", text="valid content before"),
        seg("00:14", speaker="B", text=looped.strip()),
    ]
    cleaned, modified = salvage_segments(segments)
    assert modified is True
    assert len(cleaned) == 2
    assert cleaned[1]["x"] == LOOP_PLACEHOLDER


def test_salvage_passes_through_normal_repetitions():
    # "I I I think" or "что что что" — stutter, not loop; <5 repeats should pass.
    segments = [
        seg("00:00", text="I I I I think we should do this"),
        seg("00:05", text="yes yes yes exactly my point"),
    ]
    cleaned, modified = salvage_segments(segments)
    assert modified is False
    assert cleaned == segments


def test_salvage_handles_real_chunk_6_data():
    # Mini-reproduction of the actual observed Gemini output.
    looped = "Да, сейчас, " + ("на... " * 1600).strip()
    segments = [
        {"s": "Speaker 1", "t": "00:00", "x": "может быть можно и без мессенджера"},
        {"s": "Speaker 2", "t": "00:14", "x": looped},
    ]
    cleaned, modified = salvage_segments(segments)
    assert modified is True
    assert cleaned[0]["x"] == "может быть можно и без мессенджера"
    # loop cut, prefix preserved
    assert "Да, сейчас" in cleaned[1]["x"]
    assert LOOP_PLACEHOLDER in cleaned[1]["x"]
    # salvaged text must be short (no leftover loop tail)
    assert len(cleaned[1]["x"]) < 200
