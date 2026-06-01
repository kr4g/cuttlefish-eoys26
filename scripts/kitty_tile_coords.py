#!/usr/bin/env python3
import json
import subprocess
import sys
from collections import deque


def _center(g):
    if all(k in g for k in ("left", "right", "top", "bottom")):
        return (g["left"] + g["right"]) * 0.5, (g["top"] + g["bottom"]) * 0.5
    x = g.get("x", 0)
    y = g.get("y", 0)
    w = g.get("width", 1)
    h = g.get("height", 1)
    return x + w * 0.5, y + h * 0.5


def _map_from_neighbors(windows):
    ids = [int(w.get("id", -1)) for w in windows]
    ids = [wid for wid in ids if wid >= 0]
    if not ids:
        return None

    nbrs = {}
    for w in windows:
        wid = int(w.get("id", -1))
        if wid < 0:
            continue
        n = w.get("neighbors", {}) or {}
        nbrs[wid] = {
            "left": [int(x) for x in n.get("left", [])],
            "right": [int(x) for x in n.get("right", [])],
            "top": [int(x) for x in n.get("top", [])],
            "bottom": [int(x) for x in n.get("bottom", [])],
        }

    if any(wid not in nbrs for wid in ids):
        return None

    origins = [wid for wid in ids if not nbrs[wid]["left"] and not nbrs[wid]["bottom"]]
    if not origins:
        return None
    origin = origins[0]

    coords = {origin: (0, 0)}
    q = deque([origin])
    while q:
        wid = q.popleft()
        x, y = coords[wid]
        for nw in nbrs[wid]["right"]:
            if nw not in coords:
                coords[nw] = (x + 1, y)
                q.append(nw)
        for nw in nbrs[wid]["top"]:
            if nw not in coords:
                coords[nw] = (x, y + 1)
                q.append(nw)
        for nw in nbrs[wid]["left"]:
            if nw not in coords:
                coords[nw] = (x - 1, y)
                q.append(nw)
        for nw in nbrs[wid]["bottom"]:
            if nw not in coords:
                coords[nw] = (x, y - 1)
                q.append(nw)

    if len(coords) < len(ids):
        return None

    min_x = min(c[0] for c in coords.values())
    min_y = min(c[1] for c in coords.values())
    norm = {wid: (x - min_x, y - min_y) for wid, (x, y) in coords.items()}
    return norm


def main():
    if len(sys.argv) != 6:
        sys.exit(2)
    to = sys.argv[1]
    tab_id = int(sys.argv[2])
    window_id = int(sys.argv[3])
    grid_cols = int(sys.argv[4])
    grid_rows = int(sys.argv[5])
    need = grid_cols * grid_rows

    try:
        proc = subprocess.run(
            ["kitty", "@", "ls"] if to == "-" else ["kitty", "@", "--to", to, "ls"],
            capture_output=True,
            text=True,
            check=False,
            timeout=0.5,
        )
    except subprocess.TimeoutExpired:
        sys.exit(3)
    if proc.returncode != 0:
        sys.exit(3)
    data = json.loads(proc.stdout)

    tab = None
    if tab_id > 0:
        for osw in data:
            for t in osw.get("tabs", []):
                if int(t.get("id", -1)) == tab_id:
                    tab = t
                    break
            if tab is not None:
                break
    if tab is None and window_id < 0:
        focused_tabs = [t for osw in data for t in osw.get("tabs", []) if t.get("is_focused")]
        if focused_tabs:
            tab = max(focused_tabs, key=lambda t: t.get("id", -1))
        else:
            all_tabs = [t for osw in data for t in osw.get("tabs", [])]
            if all_tabs:
                tab = max(all_tabs, key=lambda t: t.get("id", -1))
    if tab is None:
        for osw in data:
            for t in osw.get("tabs", []):
                for w in t.get("windows", []):
                    if int(w.get("id", -1)) == window_id:
                        tab = t
                        break
                if tab is not None:
                    break
            if tab is not None:
                break
    if tab is None:
        sys.exit(4)

    windows = tab.get("windows", [])
    wins = []
    for w in windows:
        g = w.get("geometry", {})
        cx, cy = _center(g)
        wins.append((int(w["id"]), float(cx), float(cy)))

    if len(wins) < need:
        sys.exit(5)

    wins = wins[:need]
    neigh_map = _map_from_neighbors(windows[:need])
    if neigh_map is not None:
        col_of = {wid: int(col) for wid, (col, _row) in neigh_map.items()}
        row_of = {wid: int(row) for wid, (_col, row) in neigh_map.items()}
    else:
        by_x = sorted(wins, key=lambda t: (t[1], t[2]))
        col_of = {}
        for i, (wid, _, _) in enumerate(by_x):
            col_of[wid] = i // grid_rows

        by_y = sorted(wins, key=lambda t: (t[2], t[1]))
        row_from_top_of = {}
        for i, (wid, _, _) in enumerate(by_y):
            row_from_top_of[wid] = i // grid_cols
        row_of = {wid: grid_rows - 1 - row_from_top_of[wid] for wid, _, _ in wins}

    if window_id < 0:
        for wid, _, _ in wins:
            col = col_of[wid]
            row = row_of[wid]
            sys.stdout.write(f"{wid} {col} {row}\n")
        return

    if window_id not in col_of or window_id not in row_of:
        sys.exit(6)

    col = col_of[window_id]
    row = row_of[window_id]
    sys.stdout.write(f"{col} {row}\n")


if __name__ == "__main__":
    main()
