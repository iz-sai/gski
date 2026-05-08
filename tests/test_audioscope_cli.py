import argparse

from gski.audioscope import register


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
