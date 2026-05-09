import argparse

from gski.audioscope import format_diarize, register


def test_cli_parser_accepts_new_flags():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    register(sub)
    args = parser.parse_args([
        "audioscope", "--audio", "x.ogg",
        "--diarize", "--timestamps",
        "--chunk-len-sec", "600", "--overlap-sec", "20",
        "--no-chunking",
    ])
    assert args.chunk_len_sec == 600
    assert args.overlap_sec == 20
    assert args.no_chunking is True


def test_cli_parser_defaults():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    register(sub)
    args = parser.parse_args(["audioscope", "--audio", "x.ogg"])
    assert args.chunk_len_sec == 900
    assert args.overlap_sec == 30
    assert args.no_chunking is False


def test_format_diarize_renders_system_speaker_distinctly():
    segs = [
        {"s": "Speaker 1", "t": "00:10", "x": "hello"},
        {"s": "__system__", "t": "05:00", "x": "[\u2026gap: 4m 0s untranscribed\u2026]"},
        {"s": "Speaker 1", "t": "09:00", "x": "world"},
    ]
    out = format_diarize(segs)
    assert "[05:00] [SYSTEM]" in out
    assert "[00:10] Speaker 1" in out
    assert "[09:00] Speaker 1" in out
    # System segment should not carry the raw __system__ token in the output.
    assert "__system__" not in out
