#!/usr/bin/env bash
set -euo pipefail

TO="${1:?}"
EFFECT="${2:?}"
GRID_COLS="${3:?}"
GRID_ROWS="${4:?}"
FPS="${5:?}"
EPOCH_OFFSET="${6:?}"
EPOCH_UNIX="${7:?}"
TILE_COLS="${8:-0}"
TILE_ROWS="${9:-0}"
MAP_FILE="${10:?}"
shift 10

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WID="${KITTY_WINDOW_ID:-0}"
TAB_ID="${KITTY_TAB_ID:-0}"
DEBUG_ON="${CUTFISH_KITTY_DEBUG:-0}"
DEBUG_LOG="${CUTFISH_KITTY_DEBUG_LOG:-/tmp/cuttlefish-kitty-debug.log}"
ENV_TO="${KITTY_LISTEN_ON:-}"

log() {
  if [[ "$DEBUG_ON" != "1" ]]; then
    return
  fi
  printf "[run] %s | wid=%s tab=%s | %s\n" "$(date +%H:%M:%S)" "$WID" "$TAB_ID" "$1" >> "$DEBUG_LOG"
}

log "start to=$TO env_to=$ENV_TO effect=$EFFECT grid=${GRID_COLS}x${GRID_ROWS}"

if [[ "$WID" == "0" ]]; then
  log "missing KITTY_WINDOW_ID"
  echo "kitty tile mapper: KITTY_WINDOW_ID not set"
  exec bash -il
fi

POS=""
USED_TO=""
TARGETS=("-")
if [[ -n "$ENV_TO" && "$ENV_TO" != "-" ]]; then
  TARGETS+=("$ENV_TO")
fi
if [[ "$TO" != "-" && "$TO" != "$ENV_TO" ]]; then
  TARGETS+=("$TO")
fi

for _ in {1..300}; do
  if [[ -f "$MAP_FILE" ]]; then
    while read -r mwid mcol mrow; do
      if [[ "$mwid" == "$WID" ]]; then
        POS="$mcol $mrow"
        USED_TO="map"
        log "resolved pos=$POS via map"
        break 2
      fi
    done < "$MAP_FILE"
  fi

  if mkdir "${MAP_FILE}.lock" 2>/dev/null; then
    for target in "${TARGETS[@]}"; do
      if python "$SCRIPT_DIR/kitty_tile_coords.py" "$target" "$TAB_ID" "-1" "$GRID_COLS" "$GRID_ROWS" > "${MAP_FILE}.tmp" 2>/dev/null; then
        mv "${MAP_FILE}.tmp" "$MAP_FILE"
        USED_TO="$target"
        log "wrote map via $target"
        break
      fi
    done
    rm -f "${MAP_FILE}.tmp"
    rmdir "${MAP_FILE}.lock" 2>/dev/null || true
  fi

  sleep 0.05
done

if [[ -z "$POS" ]]; then
  log "failed to resolve position"
  echo "kitty tile mapper: failed to resolve (col,row) for window id $WID"
  exec bash -il
fi

read -r COL ROW <<< "$POS"
log "launch animation col=$COL row=$ROW via=$USED_TO"
CMD=(python -m cuttlefish "$EFFECT" --grid-cols "$GRID_COLS" --grid-rows "$GRID_ROWS" --col "$COL" --row "$ROW" --fps "$FPS" --epoch-offset "$EPOCH_OFFSET" --epoch-unix "$EPOCH_UNIX")
if [[ "$TILE_COLS" -gt 0 ]]; then
  CMD+=(--tile-cols "$TILE_COLS")
fi
if [[ "$TILE_ROWS" -gt 0 ]]; then
  CMD+=(--tile-rows "$TILE_ROWS")
fi
CMD+=("$@")
exec "${CMD[@]}"
