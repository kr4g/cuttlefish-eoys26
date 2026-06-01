#!/usr/bin/env bash
set -euo pipefail

TO="${1:?}"
GRID_COLS="${2:?}"
GRID_ROWS="${3:?}"
MAP_FILE="${4:?}"

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
  printf "[labels] %s | wid=%s tab=%s | %s\n" "$(date +%H:%M:%S)" "$WID" "$TAB_ID" "$1" >> "$DEBUG_LOG"
}

log "start to=$TO env_to=$ENV_TO grid=${GRID_COLS}x${GRID_ROWS}"

if [[ "$WID" == "0" ]]; then
  log "missing KITTY_WINDOW_ID"
  echo "kitty label mapper: KITTY_WINDOW_ID not set"
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
        if [[ "$DEBUG_ON" == "1" ]]; then
          if [[ "$target" == "-" ]]; then
            kitty @ ls > "${MAP_FILE}.ls.json" 2>/dev/null || true
          else
            kitty @ --to "$target" ls > "${MAP_FILE}.ls.json" 2>/dev/null || true
          fi
        fi
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
  echo "kitty label mapper: failed to resolve (col,row) for window id $WID"
  exec bash -il
fi

read -r COL ROW <<< "$POS"
log "start label loop col=$COL row=$ROW via=$USED_TO"
while true; do
  clear
  printf "\n\n\n   TILE (%s,%s)\n\n   expected origin: (0,0)=bottom-left\n" "$COL" "$ROW"
  sleep 1
done
