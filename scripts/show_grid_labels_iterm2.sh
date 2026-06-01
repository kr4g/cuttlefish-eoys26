#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GRID_COLS="${GRID_COLS:-4}"
GRID_ROWS="${GRID_ROWS:-4}"
FLIP_X="${FLIP_X:-0}"
FLIP_Y="${FLIP_Y:-0}"
SWAP_XY="${SWAP_XY:-0}"

osascript - "$ROOT_DIR" "$GRID_COLS" "$GRID_ROWS" "$FLIP_X" "$FLIP_Y" "$SWAP_XY" <<'APPLESCRIPT'
on run argv
  set repoPath to item 1 of argv
  set gridCols to (item 2 of argv) as integer
  set gridRows to (item 3 of argv) as integer
  set flipX to (item 4 of argv) as integer
  set flipY to (item 5 of argv) as integer
  set swapXY to (item 6 of argv) as integer

  tell application "iTerm2"
    activate
    set newWin to (create window with default profile)
    set colSessions to {current session of newWin}

    repeat with c from 1 to (gridCols - 1)
      tell item (count colSessions) of colSessions
        set s to (split vertically with default profile)
      end tell
      set end of colSessions to s
    end repeat

    repeat with c from 1 to gridCols
      set baseSession to item c of colSessions
      set rowSessions to {baseSession}
      repeat with r from 1 to (gridRows - 1)
        tell item (count rowSessions) of rowSessions
          set s to (split horizontally with default profile)
        end tell
        set end of rowSessions to s
      end repeat

      repeat with r from 1 to gridRows
        set colVal to (c - 1)
        set rowVal to (gridRows - r)
        if swapXY is 1 then
          set tmp to colVal
          set colVal to rowVal
          set rowVal to tmp
        end if
        if flipX is 1 then
          set colVal to ((gridCols - 1) - colVal)
        end if
        if flipY is 1 then
          set rowVal to ((gridRows - 1) - rowVal)
        end if
        set cmd to "cd " & quoted form of repoPath & " && while true; do clear; printf '\\n\\n\\n   TILE (" & colVal & "," & rowVal & ")\\n\\n   expected origin: (0,0)=bottom-left\\n'; sleep 1; done"
        tell item r of rowSessions
          write text cmd
        end tell
      end repeat
    end repeat
  end tell
end run
APPLESCRIPT
