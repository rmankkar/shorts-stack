#!/usr/bin/env bash
set -euo pipefail

JOB_DIR="${1:-/data/jobs/test}"

AUDIO="${JOB_DIR}/voice.mp3"
CAPTIONS="${JOB_DIR}/captions.srt"
VISUALS="${JOB_DIR}/visuals.mp4"
OUTPUT="${JOB_DIR}/short.mp4"

# ---- subtitle look (all values are real pixels on the 1080x1920 frame) ----
FONT_NAME="DejaVu Sans"
FONT_SIZE=64          # text size in px
MARGIN_BOTTOM=30      # gap between the bottom of the text and the bottom of the video (min 30)
MARGIN_SIDE=60        # left/right padding so text never touches the screen edge
OUTLINE=4
SHADOW=1

[[ -f "$AUDIO" ]] || { echo "Missing audio: $AUDIO"; exit 1; }
[[ -f "$CAPTIONS" ]] || { echo "Missing captions: $CAPTIONS"; exit 1; }
[[ -f "$VISUALS" ]] || { echo "Missing visuals: $VISUALS"; exit 1; }

(( MARGIN_BOTTOM >= 30 )) || { echo "MARGIN_BOTTOM must be at least 30"; exit 1; }

# Why the old version broke: ffmpeg turns an .srt into ASS with a tiny virtual
# canvas (384x288) and scales every style value up to your video size. So
# FontSize=18 became ~120px text, MarginL/R=100 became ~670px each (wider than
# the screen allows), and MarginV=220 put the text near the top.
# Fix: convert the SRT to ASS first and declare the canvas as 1080x1920, so
# every number below means real pixels.
ASS="${JOB_DIR}/captions.ass"
ffmpeg -y -loglevel error -i "$CAPTIONS" "$ASS"
sed -i -E 's/^PlayResX:.*/PlayResX: 1080/; s/^PlayResY:.*/PlayResY: 1920/' "$ASS"

STYLE="FontName=${FONT_NAME},FontSize=${FONT_SIZE},Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=${OUTLINE},Shadow=${SHADOW},Alignment=2,MarginL=${MARGIN_SIDE},MarginR=${MARGIN_SIDE},MarginV=${MARGIN_BOTTOM}"

# Run from the job dir so the subtitle filename needs no path escaping.
cd "$JOB_DIR"

ffmpeg -y \
  -stream_loop -1 -i "$VISUALS" \
  -i "$AUDIO" \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles=captions.ass:force_style='${STYLE}'" \
  -map 0:v:0 -map 1:a:0 \
  -c:v libx264 -preset medium -crf 18 \
  -c:a aac -b:a 192k \
  -shortest -pix_fmt yuv420p \
  -movflags +faststart \
  "$OUTPUT"

echo "Video saved to: $OUTPUT"