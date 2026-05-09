import signal
import sys
import time

import numpy as np

from ..lib.args import num, num_int, parse_flags
from ..lib.terminal import (
    BSU,
    CLEAR_SCREEN,
    ESU,
    enter_fullscreen,
    exit_fullscreen,
    get_size,
    install_exit_handlers,
    move_to,
    require_tty,
)

EMPTY = 0
SCORCHED = 252
BURNING = 253
EMBER = 254
ASH = 255

# Per-stage (4-glyph palette, base RGB). Stage = age // 20, capped at 9.
TREE_STAGES = [
    (".\u00b7\u02d9\u22c5", (42, 90, 32)),    # 0  sprouts   ".·˙⋅"
    ("\u00b7\u2591\u2591\u00b7", (45, 106, 34)),  # 1  saplings  "·░░·"
    ("\u2591\u2591\u2591\u2591", (48, 120, 40)),  # 2  young     "░░░░"
    ("\u2591\u2592\u2591\u2592", (40, 132, 42)),  # 3  filling   "░▒░▒"
    ("\u2592\u2592\u2592\u2592", (38, 142, 48)),  # 4  medium    "▒▒▒▒"
    ("\u2592\u2593\u2592\u2593", (30, 122, 40)),  # 5  maturing  "▒▓▒▓"
    ("\u2593\u2593\u2593\u2593", (26, 110, 36)),  # 6  mature    "▓▓▓▓"
    ("\u2593\u2588\u2593\u2588", (22, 98, 32)),   # 7  dense     "▓█▓█"
    ("\u2599\u259f\u259b\u259c", (18, 86, 28)),   # 8  crown     "▙▟▛▜"
    ("\u2588\u2599\u2588\u259f", (14, 74, 24)),   # 9  old       "█▙█▟"
]

# Indexed by ff_idx = (h + tick) % 5 so each fire cell breathes through the stages.
FIRE_PALETTE = [
    (255, 221, 68),   # 0  peak
    (255, 170, 34),   # 1  bright
    (255, 102, 17),   # 2  deep
    (255,  68,  0),   # 3  collapse
    (255, 136, 51),   # 4  haze
]

# dir_code 0..8 is the 3x3 of spread directions in row-major order; 9 is a
# lightning flash. Each entry holds 4 glyphs cycled per cell as (tick + h) & 3.
#
#     0=NW  1=N    2=NE         ◤  ▲  ◥
#     3=W   4=--   5=E    ->    ◀  ▲  ▶          9 = lightning  (white-hot █)
#     6=SW  7=S    8=SE         ◣  ▼  ◢
FIRE_DIR_GLYPHS = [
    "\u25e4\u25f8\u25e4\u25f8",  # 0  NW    "◤◸◤◸"
    "\u25b2\u25b3\u25b4\u25b5",  # 1  N     "▲△▴▵"
    "\u25e5\u25f9\u25e5\u25f9",  # 2  NE    "◥◹◥◹"
    "\u25c0\u25c1\u25c2\u25c3",  # 3  W     "◀◁◂◃"
    "\u25b2\u25b3\u25b4\u25b5",  # 4  none  "▲△▴▵"  (default upward)
    "\u25b6\u25b7\u25b8\u25b9",  # 5  E     "▶▷▸▹"
    "\u25e3\u25fa\u25e3\u25fa",  # 6  SW    "◣◺◣◺"
    "\u25bc\u25bd\u25be\u25bf",  # 7  S     "▼▽▾▿"
    "\u25e2\u25ff\u25e2\u25ff",  # 8  SE    "◢◿◢◿"
    "\u2588\u2588\u2588\u2588",  # 9  lightning flash "████"
]
LIGHTNING_RGB = (255, 248, 220)

EMBER_CHARS = "\u259d\u2598\u2596\u2597"             # "▝▘▖▗"
EMBER_FG = [(170, 51, 16), (136, 34, 8), (153, 51, 21), (119, 26, 5)]
SCORCHED_CHARS = "\u2599\u259f\u259b\u259c"          # "▙▟▛▜"
SCORCHED_FG = [(102, 70, 40), (88, 58, 32), (115, 80, 46), (78, 52, 28)]
ASH_CHARS = "\u2581\u2582\u2583\u2581"               # "▁▂▃▁"
ASH_FG = [(58, 50, 42), (48, 40, 33), (66, 56, 46), (45, 38, 32)]
EMPTY_CHARS = "      \u00b7"                         # 6 spaces + "·"
EMPTY_FG = [(26, 26, 24), (24, 24, 21), (28, 28, 26), (22, 22, 20)]
SMOKE_CHARS = "\u2801\u2802\u2808\u2810\u2820\u2804\u2806\u2807"  # "⠁⠂⠈⠐⠠⠄⠆⠇"
SMOKE_FG = [(180, 182, 184), (148, 150, 152), (118, 120, 124), (162, 162, 160)]

EMBER_LIFE_GLYPHS = "\u00b7\u00b0\u2022*"   # "·°•*" cold->hot
EMBER_HOT_RGB  = (255, 210, 80)
EMBER_COLD_RGB = (150, 40, 8)

# Cap on simultaneous embers; older sparks are dropped first.
MAX_EMBERS = 128

# Per-burning-cell, per-step probability. Effective rate scales with wind.
EMBER_SPAWN_P = 0.06

# Per-ember, per-step ignition probability; multiplied by remaining life.
EMBER_IGNITE_P = 0.30

# Per-frame life decay; ember lifetime is 1 / EMBER_LIFE_DECAY frames.
EMBER_LIFE_DECAY = 0.025

EMBER_SPEED = 0.6

# Upward bias (cells/frame at life=1); decays linearly with life.
EMBER_BUOYANCY = 0.30

BIAS_DIRS = {
    "none": (0.0, 0.0),
    "n":    (0.0, -1.0),
    "ne":   (0.7071068, -0.7071068),
    "e":    (1.0, 0.0),
    "se":   (0.7071068, 0.7071068),
    "s":    (0.0, 1.0),
    "sw":   (-0.7071068, 0.7071068),
    "w":    (-1.0, 0.0),
    "nw":   (-0.7071068, -0.7071068),
}

# Fraction of `--wind` strength contributed by `--bias`; the rest is curl noise.
BIAS_FRACTION = 0.6

# Per-cell flow alignment biases per-direction spread:
#   p_dir *= clip(1 + ALPHA * (flow . spread_dir_unit), MULT_MIN, MULT_MAX)
SPREAD_ALPHA = 0.55
SPREAD_MULT_MIN = 0.1
SPREAD_MULT_MAX = 2.5


def _rgb_pack(r, g, b):
    return (int(r) << 16) | (int(g) << 8) | int(b)


def _codepoints(s):
    return np.array([ord(c) for c in s], dtype=np.uint32)


_EMPTY_CHARS = _codepoints(EMPTY_CHARS)
_ASH_CHARS = _codepoints(ASH_CHARS)
_EMBER_CHARS = _codepoints(EMBER_CHARS)
_SCORCHED_CHARS = _codepoints(SCORCHED_CHARS)
_SMOKE_CHARS = _codepoints(SMOKE_CHARS)
_EMBER_LIFE_GLYPHS = _codepoints(EMBER_LIFE_GLYPHS)
_EMPTY_RGB = np.array([_rgb_pack(*c) for c in EMPTY_FG], dtype=np.uint32)
_ASH_RGB = np.array([_rgb_pack(*c) for c in ASH_FG], dtype=np.uint32)
_EMBER_RGB = np.array([_rgb_pack(*c) for c in EMBER_FG], dtype=np.uint32)
_SCORCHED_RGB = np.array([_rgb_pack(*c) for c in SCORCHED_FG], dtype=np.uint32)
_SMOKE_RGB = np.array([_rgb_pack(*c) for c in SMOKE_FG], dtype=np.uint32)
_LIGHTNING_RGB = np.uint32(_rgb_pack(*LIGHTNING_RGB))

_FIRE_BASE = np.array([list(c) for c in FIRE_PALETTE], dtype=np.float32)

# _FIRE_DIR_CHARS[dir_code, (tick + h) & 3] -> uint32 codepoint.
_FIRE_DIR_CHARS = np.array(
    [[ord(c) for c in quad] for quad in FIRE_DIR_GLYPHS], dtype=np.uint32
)
DIR_NONE = 4
DIR_LIGHTNING = 9

_TREE_CHARS = np.array(
    [[ord(c) for c in chars] for chars, _ in TREE_STAGES], dtype=np.uint32
)
# _TREE_RGB[stage_idx, h % 36] -> per-cell color variation.
_TREE_RGB = np.empty((len(TREE_STAGES), 36), dtype=np.uint32)
for _si, (_chars, _color) in enumerate(TREE_STAGES):
    for _v in range(36):
        _variation = 0.82 + _v / 100.0
        _r = min(255, int(_color[0] * _variation))
        _g = min(255, int(_color[1] * _variation))
        _b = min(255, int(_color[2] * _variation))
        _TREE_RGB[_si, _v] = _rgb_pack(_r, _g, _b)


meta = {
    "name": "forest-fire",
    "description": "A regrowing forest plagued by lightning, fire, and wind.",
    "usage": (
        "[--growth N] [--lightning N] [--spread N] "
        "[--wind 0..3] [--turbulence 0..1] [--bias n|ne|e|...|none] "
        "[--scale 0.5..4] [--embers 0..3] [--ember-ignite 0..3] "
        "[--ember-life 0.25..4] [--ember-buoyancy 0..2] "
        "[--speed 0..10] [--fps 10..60] [--density 0..1]"
    ),
}


def _build_hash_table(rows, cols):
    y, x = np.indices((rows, cols), dtype=np.int32)
    return (((x * 7 + y * 13) ^ (x * 31 + y * 17)) & 0xFF).astype(np.uint8)


def _seed_forest(rng, rows, cols, density):
    return np.where(
        rng.random((rows, cols)) < density,
        1 + (rng.random((rows, cols)) * 60).astype(np.uint8),
        EMPTY,
    ).astype(np.uint8)


# (dy, dx, spread_dir_x, spread_dir_y, diag_penalty, spread_code 0..8) for
# all 8 neighbors. Diagonals get a 0.55x penalty so the front doesn't run
# faster along corners than along edges. Iteration order is shuffled per step.
_NEIGHBORS = []
for _dy in (-1, 0, 1):
    for _dx in (-1, 0, 1):
        if _dx == 0 and _dy == 0:
            continue
        _len = (_dx * _dx + _dy * _dy) ** 0.5
        _diag = 0.55 if (abs(_dx) + abs(_dy) == 2) else 1.0
        _NEIGHBORS.append((
            _dy, _dx,
            float(-_dx / _len), float(-_dy / _len),
            float(_diag),
            int((-_dy + 1) * 3 + (-_dx + 1)),
        ))


def _flow_field(rows, cols, t, strength, turbulence, bias_x, bias_y, scale,
                scratch):
    """Curl of a stream function (sum of 2 sinusoidal harmonics) plus a
    constant bias. Divergence-free, so it reads as fluid flow with vortices
    and saddle points. Returns (None, None) when strength == 0 so consumers
    can take a fast path."""
    if strength <= 0:
        return None, None

    base_freq = 0.085 / max(0.5, scale)
    k1 = base_freq
    k2 = base_freq * 2.3

    # turbulence = 0 freezes the field, 1 visibly churns.
    w1 = 0.20 * turbulence
    w2 = 0.31 * turbulence
    p1 = 0.13 * turbulence
    p2 = 0.27 * turbulence

    cached_shape = scratch.get("shape")
    if cached_shape != (rows, cols):
        scratch["x"] = np.arange(cols, dtype=np.float32)
        scratch["y"] = np.arange(rows, dtype=np.float32)
        scratch["shape"] = (rows, cols)
    x = scratch["x"]
    y = scratch["y"]

    sx1 = np.sin(k1 * x + w1 * t, dtype=np.float32)[None, :]
    cx1 = np.cos(k1 * x + w1 * t, dtype=np.float32)[None, :]
    sy1 = np.sin(k1 * y + p1 * t, dtype=np.float32)[:, None]
    cy1 = np.cos(k1 * y + p1 * t, dtype=np.float32)[:, None]

    sx2 = np.sin(k2 * x + w2 * t + 0.7, dtype=np.float32)[None, :]
    cx2 = np.cos(k2 * x + w2 * t + 0.7, dtype=np.float32)[None, :]
    sy2 = np.sin(k2 * y + p2 * t + 1.3, dtype=np.float32)[:, None]
    cy2 = np.cos(k2 * y + p2 * t + 1.3, dtype=np.float32)[:, None]

    # psi_i = sin(k*x+...) * cos(k*y+...);  d/dy = -k * sin*sin;  -d/dx = -k * cos*cos.
    # k absorbed into per-harmonic amplitude; raw output bounded ~[-1.6, 1.6].
    raw_x = -(sx1 * sy1) - 0.6 * (sx2 * sy2)
    raw_y = -(cx1 * cy1) - 0.6 * (cx2 * cy2)
    inv = np.float32(1.0 / 1.6)

    wfx = (strength * inv) * raw_x + np.float32(bias_x)
    wfy = (strength * inv) * raw_y + np.float32(bias_y)
    return wfx.astype(np.float32, copy=False), wfy.astype(np.float32, copy=False)


def _spawn_embers(burning_mask, embers, wind_strength, spawn_p, rng):
    if not burning_mask.any() or spawn_p <= 0:
        return embers
    ys_b, xs_b = np.nonzero(burning_mask)
    n = ys_b.size
    p = spawn_p * (0.4 + 0.6 * min(1.0, wind_strength))
    roll = rng.random(n, dtype=np.float32)
    spawned = roll < p
    if not spawned.any():
        return embers
    sy = ys_b[spawned].astype(np.float32)
    sx = xs_b[spawned].astype(np.float32)
    new = np.column_stack([sy, sx, np.ones(sy.size, dtype=np.float32)])
    embers = new if embers.size == 0 else np.vstack([embers, new])
    if embers.shape[0] > MAX_EMBERS:
        # Keep the highest-life rows.
        keep = np.argpartition(-embers[:, 2], MAX_EMBERS - 1)[:MAX_EMBERS]
        embers = embers[keep]
    return embers


def _ignite_embers(embers, grid, dir_grid, ignite_p, rng):
    """Roll ignition for each ember on a tree cell; mutates `grid` and
    `dir_grid` in place. A successful ignition consumes the ember."""
    if embers.shape[0] == 0 or ignite_p <= 0:
        return embers
    rows, cols = grid.shape
    ys = np.clip(embers[:, 0].astype(np.int32), 0, rows - 1)
    xs = np.clip(embers[:, 1].astype(np.int32), 0, cols - 1)
    cell = grid[ys, xs]
    on_tree = (cell >= 1) & (cell < SCORCHED)
    p = ignite_p * embers[:, 2]
    roll = rng.random(embers.shape[0], dtype=np.float32)
    ignites = on_tree & (roll < p)
    if ignites.any():
        gy = ys[ignites]
        gx = xs[ignites]
        grid[gy, gx] = BURNING
        dir_grid[gy, gx] = DIR_NONE
        embers = embers[~ignites]
    return embers


def _advect_embers(embers, wfx, wfy, shape, life_decay, buoyancy, rng):
    if embers.shape[0] == 0:
        return embers
    rows, cols = shape
    if wfx is not None:
        ys = np.clip(embers[:, 0].astype(np.int32), 0, rows - 1)
        xs = np.clip(embers[:, 1].astype(np.int32), 0, cols - 1)
        # Per-ember jitter so embers from the same cell diverge.
        jitter_x = (rng.random(embers.shape[0], dtype=np.float32) - 0.5) * 0.25
        jitter_y = (rng.random(embers.shape[0], dtype=np.float32) - 0.5) * 0.15
        embers[:, 0] += (
            wfy[ys, xs] * EMBER_SPEED
            - buoyancy * embers[:, 2]
            + jitter_y
        )
        embers[:, 1] += wfx[ys, xs] * EMBER_SPEED + jitter_x
    else:
        jitter_x = (rng.random(embers.shape[0], dtype=np.float32) - 0.5) * 0.2
        embers[:, 0] -= buoyancy * embers[:, 2]
        embers[:, 1] += jitter_x
    embers[:, 2] -= life_decay
    alive = (
        (embers[:, 2] > 0.0)
        & (embers[:, 0] >= 0.0) & (embers[:, 0] < rows)
        & (embers[:, 1] >= 0.0) & (embers[:, 1] < cols)
    )
    return embers[alive]


def _shifted_into(out, src, dy, dx):
    """Set out[y, x] = src[y + dy, x + dx], with off-grid cells = 0."""
    rows, cols = src.shape
    out[:] = 0
    sy = slice(max(0, dy), rows + min(0, dy))
    sx = slice(max(0, dx), cols + min(0, dx))
    dy_dst = slice(max(0, -dy), rows + min(0, -dy))
    dx_dst = slice(max(0, -dx), cols + min(0, -dx))
    out[dy_dst, dx_dst] = src[sy, sx]


def _step_forest(grid, spread_p, wfx, wfy, growth_p, lightning_p, rng):
    """Vectorized sim step. Spread uses sequential-OR over neighbors so the
    winning direction is recorded in `dir_grid` for the renderer; with wind,
    per-direction probability gets a per-cell flow-alignment multiplier.
    Returns (new_grid, new_dir_grid)."""
    rows, cols = grid.shape
    is_empty = grid == EMPTY
    is_ash = grid == ASH
    is_ember = grid == EMBER
    is_scorched = grid == SCORCHED
    is_burning = grid == BURNING
    is_tree = ~(is_empty | is_ash | is_ember | is_scorched | is_burning)

    catch_fire = np.zeros(grid.shape, dtype=bool)
    new_dir_grid = np.zeros(grid.shape, dtype=np.uint8)
    nb = np.empty_like(is_burning)
    rand_buf = np.empty(grid.shape, dtype=np.float32)
    have_wind = wfx is not None
    if have_wind:
        nbfx = np.empty_like(wfx)
        nbfy = np.empty_like(wfy)

    # Shuffle so the recorded direction is fairly weighted by each neighbor's
    # p_dir rather than biased toward whichever appears first in the loop.
    perm = rng.permutation(len(_NEIGHBORS)).tolist()
    for idx in perm:
        dy, dx, sd_x, sd_y, diag, spread_code = _NEIGHBORS[idx]
        _shifted_into(nb, is_burning, dy, dx)
        candidate = is_tree & nb & ~catch_fire
        if not candidate.any():
            continue
        rng.random(out=rand_buf, dtype=np.float32)
        if have_wind:
            _shifted_into(nbfx, wfx, dy, dx)
            _shifted_into(nbfy, wfy, dy, dx)
            align = nbfx * np.float32(sd_x) + nbfy * np.float32(sd_y)
            mult = np.clip(1.0 + SPREAD_ALPHA * align,
                           SPREAD_MULT_MIN, SPREAD_MULT_MAX)
            p_per_cell = np.minimum(1.0, spread_p * diag * mult)
            ignite = candidate & (rand_buf < p_per_cell)
        else:
            p = spread_p * diag
            if p <= 0:
                continue
            ignite = candidate & (rand_buf < p)
        catch_fire |= ignite
        new_dir_grid[ignite] = spread_code

    rand_lightning = rng.random((rows, cols), dtype=np.float32)
    lightning = is_tree & ~catch_fire & (rand_lightning < lightning_p)
    new_dir_grid[lightning] = DIR_LIGHTNING

    rand_grow = rng.random((rows, cols), dtype=np.float32)
    empty_grew = is_empty & (rand_grow < growth_p)

    rand_ash_grow = rng.random((rows, cols), dtype=np.float32)
    ash_grew = is_ash & (rand_ash_grow < growth_p * 0.4)

    rand_ash_die = rng.random((rows, cols), dtype=np.float32)
    ash_died = is_ash & ~ash_grew & (rand_ash_die < 0.02)

    nxt = grid.copy()
    # Decay chain: BURNING -> EMBER -> SCORCHED -> ASH (one step each).
    nxt[is_burning] = EMBER
    nxt[is_ember] = SCORCHED
    nxt[is_scorched] = ASH
    # uint16 to dodge uint8 overflow at v=255.
    aged = np.minimum(grid.astype(np.uint16) + 1, 240).astype(np.uint8)
    nxt[is_tree] = aged[is_tree]
    nxt[catch_fire] = BURNING
    nxt[lightning] = BURNING
    nxt[empty_grew] = 1
    nxt[ash_grew] = 1
    nxt[ash_died] = EMPTY
    return nxt, new_dir_grid


def _dilate_neighborhood(mask, radius):
    """Boolean dilation by an axis-aligned square (radius=2 -> 5x5)."""
    out = mask.copy()
    nb = np.empty_like(mask)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy == 0 and dx == 0:
                continue
            _shifted_into(nb, mask, dy, dx)
            out |= nb
    return out


def _split_rgb(rgb_arr):
    r = ((rgb_arr >> 16) & 0xFF).astype(np.uint16)
    g = ((rgb_arr >> 8) & 0xFF).astype(np.uint16)
    b = (rgb_arr & 0xFF).astype(np.uint16)
    return r, g, b


def _pack_rgb(r, g, b):
    r = np.minimum(255, r).astype(np.uint32)
    g = np.minimum(255, g).astype(np.uint32)
    b = np.minimum(255, b).astype(np.uint32)
    return (r << 16) | (g << 8) | b


def _compute_frame(grid, dir_grid, hash_table, tick, wfx, wfy, embers):
    """Layered render: base state -> flow-field tint on trees -> smoke ->
    heat-glow halo -> singed trees -> ember sparks."""
    h = hash_table
    h32 = h.astype(np.int32)

    char_arr = np.full(grid.shape, 0x20, dtype=np.uint32)
    rgb_arr = np.zeros(grid.shape, dtype=np.uint32)

    empty_mask = grid == EMPTY
    if empty_mask.any():
        idx = h32 % len(_EMPTY_CHARS)
        ec = _EMPTY_CHARS[idx]
        is_space = ec == 0x20
        rgb_for_empty = np.where(is_space, np.uint32(0), _EMPTY_RGB[h & 3])
        char_arr[empty_mask] = ec[empty_mask]
        rgb_arr[empty_mask] = rgb_for_empty[empty_mask]

    ash_mask = grid == ASH
    if ash_mask.any():
        idx = h32 % len(_ASH_CHARS)
        char_arr[ash_mask] = _ASH_CHARS[idx][ash_mask]
        rgb_arr[ash_mask] = _ASH_RGB[h & 3][ash_mask]

    scorched_mask = grid == SCORCHED
    if scorched_mask.any():
        idx = h32 % len(_SCORCHED_CHARS)
        char_arr[scorched_mask] = _SCORCHED_CHARS[idx][scorched_mask]
        rgb_arr[scorched_mask] = _SCORCHED_RGB[h & 3][scorched_mask]

    ember_mask = grid == EMBER
    if ember_mask.any():
        idx = (h32 + tick) & 3
        char_arr[ember_mask] = _EMBER_CHARS[idx][ember_mask]
        rgb_arr[ember_mask] = _EMBER_RGB[idx][ember_mask]

    burning_mask = grid == BURNING
    if burning_mask.any():
        # Phase by per-cell hash so neighbors are out of sync (shimmer, not blink).
        frame_idx = (h32 + tick) & 3
        char_arr[burning_mask] = _FIRE_DIR_CHARS[dir_grid, frame_idx][burning_mask]
        ff_idx = (h32 + tick) % 5
        flicker = 0.75 + (((h32 * 3 + tick * 7) & 0xF).astype(np.float32) / 60.0)
        base = _FIRE_BASE[ff_idx]
        rgb_f = np.minimum(255.0, base * flicker[..., None]).astype(np.uint32)
        burning_rgb = (rgb_f[..., 0] << 16) | (rgb_f[..., 1] << 8) | rgb_f[..., 2]
        rgb_arr[burning_mask] = burning_rgb[burning_mask]
        lightning_mask = burning_mask & (dir_grid == DIR_LIGHTNING)
        if lightning_mask.any():
            rgb_arr[lightning_mask] = _LIGHTNING_RGB

    tree_mask = ~(empty_mask | ash_mask | scorched_mask | ember_mask | burning_mask)
    if tree_mask.any():
        age = np.minimum(grid.astype(np.int32) - 1, 180)
        si = np.minimum(age // 20, len(TREE_STAGES) - 1).astype(np.int32)
        si = np.clip(si, 0, len(TREE_STAGES) - 1)
        char_arr[tree_mask] = _TREE_CHARS[si, h & 3][tree_mask]
        rgb_arr[tree_mask] = _TREE_RGB[si, h32 % 36][tree_mask]

    # Subtle directional tint on trees, scaled by |flow| so calm regions
    # auto-dampen and the canopy still reads as green.
    if wfx is not None and tree_mask.any():
        fx_clip = np.clip(wfx, -1.0, 1.0)
        fy_clip = np.clip(wfy, -1.0, 1.0)
        r, g, b = _split_rgb(rgb_arr)
        ri = r.astype(np.int16)
        gi = g.astype(np.int16)
        bi = b.astype(np.int16)
        ri += (9.0 * fx_clip).astype(np.int16)
        gi += (5.0 * fy_clip).astype(np.int16)
        bi += (-7.0 * fy_clip).astype(np.int16)
        np.clip(ri, 0, 255, out=ri)
        np.clip(gi, 0, 255, out=gi)
        np.clip(bi, 0, 255, out=bi)
        tinted = _pack_rgb(ri.astype(np.uint16),
                           gi.astype(np.uint16),
                           bi.astype(np.uint16))
        rgb_arr[tree_mask] = tinted[tree_mask]

    # Smoke: scatter markers along the per-cell flow from each burning cell,
    # then keep only those landing on EMPTY (vortices shed spirals, not slabs).
    has_fire = burning_mask.any()
    if has_fire and wfx is not None and empty_mask.any():
        rows, cols = grid.shape
        ys_b, xs_b = np.nonzero(burning_mask)
        if ys_b.size:
            fy_b = wfy[ys_b, xs_b]
            fx_b = wfx[ys_b, xs_b]
            smoke_mask = np.zeros_like(empty_mask)
            for k in (1, 2, 3):
                ty = ys_b + np.rint(fy_b * k).astype(np.int32)
                tx = xs_b + np.rint(fx_b * k).astype(np.int32)
                valid = (ty >= 0) & (ty < rows) & (tx >= 0) & (tx < cols)
                smoke_mask[ty[valid], tx[valid]] = True
            smoke_mask &= empty_mask
            if smoke_mask.any():
                smoke_idx = (h32 + tick) % len(_SMOKE_CHARS)
                char_arr[smoke_mask] = _SMOKE_CHARS[smoke_idx][smoke_mask]
                rgb_arr[smoke_mask] = _SMOKE_RGB[h & 3][smoke_mask]

    if has_fire:
        halo = _dilate_neighborhood(burning_mask, 2) & ~burning_mask
        if halo.any():
            r, g, b = _split_rgb(rgb_arr)
            # Lerp toward (255, 80, 30) by 0.18.
            r = (r * 82 // 100) + (255 * 18 // 100)
            g = (g * 82 // 100) + (80 * 18 // 100)
            b = (b * 82 // 100) + (30 * 18 // 100)
            rgb_arr[halo] = _pack_rgb(r, g, b)[halo]

    if has_fire and tree_mask.any():
        danger = _dilate_neighborhood(burning_mask, 1) & tree_mask
        if danger.any():
            r, g, b = _split_rgb(rgb_arr)
            # Lerp toward (90, 30, 15) by 0.55.
            r = (r * 45 // 100) + (90 * 55 // 100)
            g = (g * 35 // 100) + (30 * 35 // 100)
            b = (b * 35 // 100) + (15 * 35 // 100)
            rgb_arr[danger] = _pack_rgb(r, g, b)[danger]

    # Painted last so sparks sit on top of everything except active flame.
    if embers is not None and embers.shape[0] > 0:
        rows, cols = grid.shape
        ys = np.clip(embers[:, 0].astype(np.int32), 0, rows - 1)
        xs = np.clip(embers[:, 1].astype(np.int32), 0, cols - 1)
        life = embers[:, 2]
        show = grid[ys, xs] != BURNING
        if show.any():
            ys = ys[show]
            xs = xs[show]
            life = life[show]
            tier = np.clip((life * 4.0).astype(np.int32), 0, 3)
            char_arr[ys, xs] = _EMBER_LIFE_GLYPHS[tier]
            hr, hg, hb = EMBER_HOT_RGB
            cr, cg, cb = EMBER_COLD_RGB
            r = (hr * life + cr * (1.0 - life)).astype(np.uint32)
            g = (hg * life + cg * (1.0 - life)).astype(np.uint32)
            b = (hb * life + cb * (1.0 - life)).astype(np.uint32)
            rgb_arr[ys, xs] = (r << 16) | (g << 8) | b

    return char_arr, rgb_arr


def _emit_diff(char_arr, rgb_arr, prev, write):
    """Diff against the previous frame and write only what changed."""
    packed = (char_arr.astype(np.int64) << 24) | rgb_arr.astype(np.int64)
    diff = packed != prev
    parts = [BSU]

    if diff.any():
        prev[:] = packed
        # numpy returns ys/xs in row-major scan order, exactly what the
        # cursor-positioning loop below expects.
        ys, xs = np.nonzero(diff)
        chars = char_arr[ys, xs]
        rgbs = rgb_arr[ys, xs]
        ys_l = ys.tolist()
        xs_l = xs.tolist()
        chars_l = chars.tolist()
        rgbs_l = rgbs.tolist()

        last_color = -1
        cur_r = -1
        cur_c = -1
        for y, x, ch, rgb in zip(ys_l, xs_l, chars_l, rgbs_l):
            if cur_r != y or cur_c != x:
                parts.append(move_to(y + 1, x + 1))
                cur_r = y
                cur_c = x
            if ch == 0x20:
                parts.append(" ")
            else:
                if rgb != last_color:
                    r = (rgb >> 16) & 0xFF
                    g = (rgb >> 8) & 0xFF
                    b = rgb & 0xFF
                    parts.append(f"\x1b[38;2;{r};{g};{b}m")
                    last_color = rgb
                parts.append(chr(ch))
            cur_c += 1

    parts.append(ESU)
    write("".join(parts))


def run(argv=None):
    if argv is None:
        argv = []
    require_tty()

    flags = parse_flags(argv)
    growth = num(flags.get("growth"), 0.002, 0, 0.05)
    lightning = num(flags.get("lightning"), 0.00001, 0, 0.001)
    spread = num(flags.get("spread"), 0.63, 0.05, 1)
    speed = num(flags.get("speed"), 1.0, 0.0, 10.0)
    fps = num_int(flags.get("fps"), 60, 10, 60)
    density = num(flags.get("density"), 0.33, 0, 1)
    wind_strength = num(flags.get("wind"), 2.0, 0.0, 3.0)
    turbulence = num(flags.get("turbulence"), 0.4, 0.0, 1.0)
    scale = num(flags.get("scale"), 3.0, 0.5, 4.0)
    bias_key = flags.get("bias")
    if not isinstance(bias_key, str) or bias_key not in BIAS_DIRS:
        bias_key = "none"
    bias_ux, bias_uy = BIAS_DIRS[bias_key]
    bias_x = wind_strength * BIAS_FRACTION * bias_ux
    bias_y = wind_strength * BIAS_FRACTION * bias_uy

    # Each is a multiplier on the corresponding base constant; 1.0 = unchanged.
    embers_intensity = num(flags.get("embers"), 1.25, 0.0, 3.0)
    ember_ignite_mult = num(flags.get("ember-ignite"), 0.43, 0.0, 3.0)
    ember_life_mult = num(flags.get("ember-life"), 2.0, 0.25, 4.0)
    ember_buoyancy_mult = num(flags.get("ember-buoyancy"), 0.0, 0.0, 2.0)
    ember_spawn_p_eff = EMBER_SPAWN_P * embers_intensity
    ember_ignite_p_eff = EMBER_IGNITE_P * ember_ignite_mult
    # `--ember-life` is a lifetime multiplier; divide rather than multiply.
    ember_life_decay_eff = EMBER_LIFE_DECAY / ember_life_mult
    ember_buoyancy_eff = EMBER_BUOYANCY * ember_buoyancy_mult
    embers_active = wind_strength > 0 and embers_intensity > 0

    rng = np.random.default_rng()

    state = {
        "grid": None,
        "dir_grid": None,
        "hash": None,
        "prev": None,
        # Pre-step snapshot, used to stagger per-cell visual transitions
        # across the frames between sim ticks.
        "prev_grid": None,
        "prev_dir_grid": None,
        "frames_since_step": 0,
        "wfx": None,
        "wfy": None,
        "flow_scratch": {},
        "sim_t": 0.0,
        # (N, 3) float32: columns are y, x, life.
        "embers": np.empty((0, 3), dtype=np.float32),
    }
    needs_resize = [True]

    def do_resize():
        cols, rows = get_size()
        cols = max(20, cols)
        rows = max(8, rows)
        state["grid"] = _seed_forest(rng, rows, cols, density)
        state["dir_grid"] = np.zeros((rows, cols), dtype=np.uint8)
        state["hash"] = _build_hash_table(rows, cols)
        state["prev"] = np.full((rows, cols), -1, dtype=np.int64)
        state["prev_grid"] = state["grid"].copy()
        state["prev_dir_grid"] = state["dir_grid"].copy()
        state["flow_scratch"] = {}
        state["wfx"], state["wfy"] = _flow_field(
            rows, cols, state["sim_t"], wind_strength, turbulence,
            bias_x, bias_y, scale, state["flow_scratch"],
        )
        # In-flight embers may sit off the new grid.
        state["embers"] = np.empty((0, 3), dtype=np.float32)
        sys.stdout.write(CLEAR_SCREEN)
        sys.stdout.flush()

    if hasattr(signal, "SIGWINCH"):
        signal.signal(signal.SIGWINCH, lambda _s, _f: needs_resize.__setitem__(0, True))

    def cleanup():
        exit_fullscreen()

    install_exit_handlers(cleanup)
    enter_fullscreen()

    write = sys.stdout.write
    flush = sys.stdout.flush

    tick = 0
    frame_interval = 1.0 / fps
    # `speed` is a multiplier where 1.0 = one sim step per ~3 render frames.
    # 0.0 pauses the sim; >> 1 steps multiple times per render frame.
    DEFAULT_FRAMES_PER_STEP = 3.0
    steps_per_frame = speed / DEFAULT_FRAMES_PER_STEP
    step_accum = 0.0
    # Denominator for staggering per-cell visual transitions across frames.
    # When >= 1 sim step per render frame there's nothing to interpolate.
    frames_per_step = (1.0 / steps_per_frame) if steps_per_frame > 0 else 0.0
    smooth_transitions = frames_per_step > 1.0

    next_frame = time.monotonic()
    while True:
        if needs_resize[0]:
            needs_resize[0] = False
            do_resize()

        tick += 1
        step_accum += steps_per_frame
        # Cap iterations defensively so a freak large delta can't spin here.
        max_steps_this_frame = 8
        steps_this_frame = 0
        stepped = False
        while step_accum >= 1.0 and steps_this_frame < max_steps_this_frame:
            if not stepped:
                state["prev_grid"] = state["grid"].copy()
                state["prev_dir_grid"] = state["dir_grid"].copy()
            state["grid"], state["dir_grid"] = _step_forest(
                state["grid"], spread, state["wfx"], state["wfy"],
                growth, lightning, rng,
            )
            if embers_active:
                state["embers"] = _spawn_embers(
                    state["grid"] == BURNING, state["embers"],
                    wind_strength, ember_spawn_p_eff, rng,
                )
                state["embers"] = _ignite_embers(
                    state["embers"], state["grid"], state["dir_grid"],
                    ember_ignite_p_eff, rng,
                )
            step_accum -= 1.0
            steps_this_frame += 1
            stepped = True

        if stepped:
            state["frames_since_step"] = 0
            # Advance once per sim batch, not per intermediate sim step.
            state["sim_t"] += 1.0
            rows_g, cols_g = state["grid"].shape
            state["wfx"], state["wfy"] = _flow_field(
                rows_g, cols_g, state["sim_t"], wind_strength, turbulence,
                bias_x, bias_y, scale, state["flow_scratch"],
            )
        else:
            state["frames_since_step"] += 1

        # Per-frame ember motion (decoupled from sim speed for smoothness).
        if embers_active and state["embers"].shape[0] > 0:
            state["embers"] = _advect_embers(
                state["embers"], state["wfx"], state["wfy"],
                state["grid"].shape,
                ember_life_decay_eff, ember_buoyancy_eff, rng,
            )

        # Each cell has a deterministic flip threshold in [0, 1) from its hash.
        # As t advances from 0 to 1 between sim ticks, cells with threshold <= t
        # show the new state, others still show the previous.
        if smooth_transitions:
            t = state["frames_since_step"] / frames_per_step
            flip_at_t = state["hash"].astype(np.float32) * (1.0 / 256.0)
            use_current = flip_at_t <= t
            visible_grid = np.where(use_current, state["grid"], state["prev_grid"])
            visible_dir = np.where(
                use_current, state["dir_grid"], state["prev_dir_grid"]
            )
        else:
            visible_grid = state["grid"]
            visible_dir = state["dir_grid"]

        char_arr, rgb_arr = _compute_frame(
            visible_grid, visible_dir, state["hash"], tick,
            state["wfx"], state["wfy"], state["embers"],
        )
        _emit_diff(char_arr, rgb_arr, state["prev"], write)
        flush()

        next_frame += frame_interval
        sleep_for = next_frame - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        elif sleep_for < -frame_interval:
            next_frame = time.monotonic()


if __name__ == "__main__":
    run(sys.argv[1:])
