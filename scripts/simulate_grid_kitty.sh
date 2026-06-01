#!/usr/bin/env bash
set -euo pipefail

EFFECT="${1:-bitwise}"
if [[ $# -gt 0 ]]; then
  shift
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GRID_COLS="${GRID_COLS:-4}"
GRID_ROWS="${GRID_ROWS:-4}"
FPS="${FPS:-60}"
EPOCH_OFFSET="${EPOCH_OFFSET:-0}"
EPOCH_UNIX="${EPOCH_UNIX:-$(python - <<'PY'
import time
print(f"{time.time():.6f}")
PY
)}"
TILE_COLS="${TILE_COLS:-0}"
TILE_ROWS="${TILE_ROWS:-0}"

declare -a EXTRA_ARGS=()
if (($# > 0)); then
  EXTRA_ARGS=("$@")
fi

CELL_COUNT=$((GRID_COLS * GRID_ROWS))
SESSION_FILE="$(mktemp /tmp/cuttlefish-kitty-grid.XXXXXX)"
DEBUG_LOG="/tmp/cuttlefish-kitty-grid-debug.$$.$RANDOM.log"
MAP_FILE="/tmp/cuttlefish-kitty-grid-map.$$.$RANDOM.txt"
trap 'rm -f "$SESSION_FILE" "$MAP_FILE" "${MAP_FILE}.tmp"; rmdir "${MAP_FILE}.lock" 2>/dev/null || true' EXIT

echo "kitty grid debug log: $DEBUG_LOG"

{
  echo "new_tab cuttlefish-grid"
  echo "layout grid"
  for ((i = 0; i < CELL_COUNT; i++)); do
    line="launch --cwd $(printf '%q' "$ROOT_DIR") env CUTFISH_KITTY_DEBUG=1 CUTFISH_KITTY_DEBUG_LOG=$(printf '%q' "$DEBUG_LOG") $(printf '%q' "$ROOT_DIR/scripts/kitty_tile_run.sh") - $(printf '%q' "$EFFECT") $(printf '%q' "$GRID_COLS") $(printf '%q' "$GRID_ROWS") $(printf '%q' "$FPS") $(printf '%q' "$EPOCH_OFFSET") $(printf '%q' "$EPOCH_UNIX") $(printf '%q' "$TILE_COLS") $(printf '%q' "$TILE_ROWS") $(printf '%q' "$MAP_FILE")"
    if ((${#EXTRA_ARGS[@]} > 0)); then
      for arg in "${EXTRA_ARGS[@]}"; do
        line+=" $(printf '%q' "$arg")"
      done
    fi
    printf "%s\n" "$line"
  done
} > "$SESSION_FILE"

exec kitty -o allow_remote_control=yes --session "$SESSION_FILE"
