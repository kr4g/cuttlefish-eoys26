import os
import re
import socket
from dataclasses import dataclass

import numpy as np

from .args import num_int


_POSITION_ENV_VARS = ("CUTFISH_POSITION", "CUTFISH_HOSTNAME")


@dataclass(frozen=True)
class Viewport:
    grid_cols: int
    grid_rows: int
    col: int
    row: int
    hostname: str


def _parse_hostname_tile(hostname):
    m = re.search(r"(\d)(\d)$", hostname)
    if m:
        return int(m.group(1)), int(m.group(2))
    parts = re.findall(r"\d+", hostname)
    if len(parts) >= 2:
        return int(parts[0]), int(parts[1])
    if len(parts) == 1 and len(parts[0]) >= 2:
        return int(parts[0][0]), int(parts[0][1])
    return None


def _env_hostname():
    for name in _POSITION_ENV_VARS:
        val = os.environ.get(name)
        if val:
            return val
    return None


def resolve_host(flags):
    flag_host = flags.get("hostname")
    if flag_host:
        return str(flag_host)
    return str(_env_hostname() or socket.gethostname())


def position_resolvable(flags):
    if "hostname" in flags or "col" in flags or "row" in flags:
        return True
    host = _env_hostname() or socket.gethostname()
    return _parse_hostname_tile(str(host)) is not None


def resolve_viewport(flags):
    host = resolve_host(flags)
    parsed = _parse_hostname_tile(host)
    default_grid = 4 if parsed is not None else 1

    grid_cols = num_int(flags.get("grid-cols"), default_grid, 1, 32)
    grid_rows = num_int(flags.get("grid-rows"), default_grid, 1, 32)

    parsed_col = parsed[0] if parsed is not None else 0
    parsed_row = parsed[1] if parsed is not None else 0
    col = num_int(flags.get("col"), parsed_col, 0, grid_cols - 1)
    row = num_int(flags.get("row"), parsed_row, 0, grid_rows - 1)

    return Viewport(
        grid_cols=grid_cols,
        grid_rows=grid_rows,
        col=col,
        row=row,
        hostname=host,
    )


def build_fields(cols, lines, viewport, zoom, aspect, tile_cols=None, tile_rows=None):
    tile_cols = cols if tile_cols is None else int(max(1, tile_cols))
    tile_rows = lines if tile_rows is None else int(max(1, tile_rows))
    x_local = np.arange(cols, dtype=np.float32)
    y_local = (lines - 1 - np.arange(lines, dtype=np.float32))
    gx_local = ((x_local + 0.5) / np.float32(cols)) * np.float32(tile_cols) - 0.5
    gy_local = ((y_local + 0.5) / np.float32(lines)) * np.float32(tile_rows) - 0.5
    gx, gy = np.meshgrid(gx_local, gy_local, indexing="xy")
    gx = gx + np.float32(viewport.col * tile_cols)
    gy = gy + np.float32(viewport.row * tile_rows)

    global_w = np.float32(viewport.grid_cols * tile_cols)
    global_h = np.float32(viewport.grid_rows * tile_rows)
    x = ((gx + 0.5) / global_w * 2.0 - 1.0) * np.float32(zoom * aspect)
    y = ((gy + 0.5) / global_h * 2.0 - 1.0) * np.float32(zoom)
    ix = gx - global_w * 0.5
    iy = gy - global_h * 0.5
    return x.astype(np.float32), y.astype(np.float32), ix.astype(np.float32), iy.astype(np.float32)
