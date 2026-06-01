#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GRID_COLS="${GRID_COLS:-4}"
GRID_ROWS="${GRID_ROWS:-4}"

CELL_COUNT=$((GRID_COLS * GRID_ROWS))
SESSION_FILE="$(mktemp /tmp/cuttlefish-kitty-labels.XXXXXX)"
DEBUG_LOG="/tmp/cuttlefish-kitty-labels-debug.$$.$RANDOM.log"
MAP_FILE="/tmp/cuttlefish-kitty-label-map.$$.$RANDOM.txt"
trap 'rm -f "$SESSION_FILE" "$MAP_FILE" "${MAP_FILE}.tmp"; rmdir "${MAP_FILE}.lock" 2>/dev/null || true' EXIT

echo "kitty labels debug log: $DEBUG_LOG"

{
  echo "new_tab cuttlefish-grid-labels"
  echo "layout grid"
  for ((i = 0; i < CELL_COUNT; i++)); do
    line="launch --cwd $(printf '%q' "$ROOT_DIR") env CUTFISH_KITTY_DEBUG=1 CUTFISH_KITTY_DEBUG_LOG=$(printf '%q' "$DEBUG_LOG") $(printf '%q' "$ROOT_DIR/scripts/kitty_tile_labels.sh") - $(printf '%q' "$GRID_COLS") $(printf '%q' "$GRID_ROWS") $(printf '%q' "$MAP_FILE")"
    printf "%s\n" "$line"
  done
} > "$SESSION_FILE"

exec kitty -o allow_remote_control=yes --session "$SESSION_FILE"
