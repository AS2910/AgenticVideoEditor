"""Messy real-world audio (run 5, item 8): 20 variants of the chai clip with a
music bed, cafe noise, room echo, crosstalk, phone audio and clipping, and a
runner that says where transcription, voice matching and timing break.

    python -m evals.messy build                  # make the 20 variants (+ the clean control)
    python -m evals.messy run --label before     # score them (real Whisper when OPENAI_API_KEY is set)
    python -m evals.messy report results/<after>.json --before results/<before>.json

The variants are made, not committed: `build` is deterministic (fixed seeds,
ffmpeg and numpy only), so the same command makes the same files.
"""
