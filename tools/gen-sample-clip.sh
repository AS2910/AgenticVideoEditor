#!/usr/bin/env bash
# Regenerates the bundled placeholder clip: the Swift-drawn title card, with a
# spoken soundtrack so it is actually transcribable.
#
#   tools/gen-sample-clip.sh frontend/public/sample-ad.mp4
#
# macOS only — uses `say` for speech. Needs ffmpeg on PATH.
# The exact voice depends on the machine's TTS, so output is not byte-stable
# across macOS versions. That is fine: it is a placeholder, not a fixture.
set -euo pipefail

OUT="${1:?usage: gen-sample-clip.sh <out.mp4>}"
LINE="Get 20 percent off today only"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "→ drawing the title card"
swift "$HERE/gen-sample-clip.swift" "$TMP/video.mp4"

echo "→ speaking: $LINE"
say "$LINE" -o "$TMP/speech.aiff"
ffmpeg -y -loglevel error -i "$TMP/speech.aiff" -ar 16000 -ac 1 -c:a pcm_s16le "$TMP/speech.wav"

echo "→ muxing"
# apad keeps the audio running to the end of the card, so the video is not
# truncated to the (shorter) length of the speech.
ffmpeg -y -loglevel error -i "$TMP/video.mp4" -i "$TMP/speech.wav" \
  -filter_complex "[1:a]apad[a]" -map 0:v -map "[a]" \
  -c:v copy -c:a aac -shortest "$OUT"

echo "✓ wrote $OUT"
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUT" \
  | xargs -I{} echo "  duration: {}s"
ffprobe -v error -show_entries stream=codec_type,codec_name -of csv=p=0 "$OUT" \
  | sed 's/^/  stream: /'
