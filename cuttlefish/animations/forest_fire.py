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
SCORCHED = 252  # blackened skeleton: 1 step between EMBER and ASH
BURNING = 253
EMBER = 254
ASH = 255

# Density-based palette: the character paints how filled the cell is, color
# carries the species/state. All glyphs are from the Unicode block-elements
# (U+2580..U+259F) and geometric-shapes (U+25A0..U+25FF) ranges, which every
# decent monospace font covers and which always render as a single column.
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

# Fire color palette: 5 stages of combustion. Per-cell ff_idx = (h + tick) % 5
# rotates through these so each fire cell "breathes" through the colors over
# time. Glyphs come from FIRE_DIR_GLYPHS below — the *direction* the fire is
# spreading is encoded in the glyph itself.
FIRE_PALETTE = [
    (255, 221, 68),   # 0  peak
    (255, 170, 34),   # 1  bright
    (255, 102, 17),   # 2  deep
    (255,  68,  0),   # 3  collapse
    (255, 136, 51),   # 4  haze
]

# Spread-direction-indexed glyph table. Index is `dir_code` 0..9, laid out as
# the 3x3 of spread directions in row-major order, plus a 9th "lightning"
# entry used for cells just struck by lightning:
#
#     0=NW  1=N    2=NE         ◤  ▲  ◥
#     3=W   4=--   5=E    ->    ◀  ▲  ▶          9 = lightning  (white-hot █)
#     6=SW  7=S    8=SE         ◣  ▼  ◢
#
# Code 4 is the no-direction default; code 9 is the special lightning flash.
# Each entry is FOUR glyphs cycled per cell as `(tick + h) & 3`, so neighbor
# cells are out of phase and the field shimmers instead of blinking. Cardinals
# alternate filled-large / outlined-large / filled-small / outlined-small;
# diagonals alternate filled / outlined corner triangles (U+25Fx).
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
# Color override for the lightning flash slot: bright warm-white, ignored by
# the usual FIRE_PALETTE rotation.
LIGHTNING_RGB = (255, 248, 220)

# Single glowing quadrant per cell — reads as "tiny cinder in this corner".
EMBER_CHARS = "\u259d\u2598\u2596\u2597"             # "▝▘▖▗"
EMBER_FG = [(170, 51, 16), (136, 34, 8), (153, 51, 21), (119, 26, 5)]
# Burnt-tree skeletons: same crown silhouette as old growth but in dark sepia.
SCORCHED_CHARS = "\u2599\u259f\u259b\u259c"          # "▙▟▛▜"
SCORCHED_FG = [(34, 24, 18), (28, 20, 14), (38, 27, 20), (30, 22, 16)]
# Lower-eighth blocks for ash — silhouette is at the floor, distinct from
# any tree stage and reads as "settled char on the forest floor".
ASH_CHARS = "\u2581\u2582\u2583\u2581"               # "▁▂▃▁"
ASH_FG = [(58, 50, 42), (48, 40, 33), (66, 56, 46), (45, 38, 32)]
# Mostly blank, with the occasional faint middle-dot for visible "ground".
EMPTY_CHARS = "      \u00b7"                         # 6 spaces + "·"
EMPTY_FG = [(26, 26, 24), (24, 24, 21), (28, 28, 26), (22, 22, 20)]
# Smoke drift on empty cells downwind of any active fire. Sparse braille so
# the smoke trails read as floating particulates rather than solid mass.
SMOKE_CHARS = "\u2801\u2802\u2808\u2810\u2820\u2804\u2806\u2807"  # "⠁⠂⠈⠐⠠⠄⠆⠇"
SMOKE_FG = (60, 55, 48)

WIND_DIRS = {
    "none": (0, 0),
    "n": (0, -1),
    "e": (1, 0),
    "s": (0, 1),
    "w": (-1, 0),
}

# ---------------------------------------------------------------------------
# Precomputed lookup tables. Built once at import; indexed with numpy fancy
# indexing in the per-frame compute path so the inner work is C-speed.
# ---------------------------------------------------------------------------

def _rgb_pack(r, g, b):
    return (int(r) << 16) | (int(g) << 8) | int(b)


def _codepoints(s):
    """Pack a Python string of single-column glyphs into a uint32 array of
    codepoints. We use uint32 because non-ASCII glyphs (e.g. U+2588 = 9608)
    don't fit in uint8."""
    return np.array([ord(c) for c in s], dtype=np.uint32)


_EMPTY_CHARS = _codepoints(EMPTY_CHARS)
_ASH_CHARS = _codepoints(ASH_CHARS)
_EMBER_CHARS = _codepoints(EMBER_CHARS)
_SCORCHED_CHARS = _codepoints(SCORCHED_CHARS)
_SMOKE_CHARS = _codepoints(SMOKE_CHARS)
_EMPTY_RGB = np.array([_rgb_pack(*c) for c in EMPTY_FG], dtype=np.uint32)
_ASH_RGB = np.array([_rgb_pack(*c) for c in ASH_FG], dtype=np.uint32)
_EMBER_RGB = np.array([_rgb_pack(*c) for c in EMBER_FG], dtype=np.uint32)
_SCORCHED_RGB = np.array([_rgb_pack(*c) for c in SCORCHED_FG], dtype=np.uint32)
_SMOKE_RGB = np.uint32(_rgb_pack(*SMOKE_FG))
_LIGHTNING_RGB = np.uint32(_rgb_pack(*LIGHTNING_RGB))

# Fire color base, indexed by ff_idx = (h + tick) % 5.
_FIRE_BASE = np.array([list(c) for c in FIRE_PALETTE], dtype=np.float32)

# Fire glyph lookup, indexed as _FIRE_DIR_CHARS[dir_code, (tick + h) & 3].
# dir_code is the value stored in `dir_grid` for each burning cell (0..9).
_FIRE_DIR_CHARS = np.array(
    [[ord(c) for c in quad] for quad in FIRE_DIR_GLYPHS], dtype=np.uint32
)
# Sentinels stored in dir_grid:
#   DIR_NONE       = 4  ("no spread direction known", e.g. ember leftover)
#   DIR_LIGHTNING  = 9  ("lightning just struck this cell" -> white-hot flash)
DIR_NONE = 4
DIR_LIGHTNING = 9

# TREE_CHARS_LOOKUP[stage_idx, char_idx]  ->  uint32 codepoint
_TREE_CHARS = np.array(
    [[ord(c) for c in chars] for chars, _ in TREE_STAGES], dtype=np.uint32
)
# TREE_RGB_LOOKUP[stage_idx, h % 36]  ->  uint32 packed RGB
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
        "[--wind n|e|s|w|none] [--speed 0..10] [--fps 10..60] [--density 0..1]"
    ),
}


def _build_hash_table(rows, cols):
    """The same per-cell hash the original prototype used; produces a uint8
    pseudo-random pattern that's stable across frames."""
    y, x = np.indices((rows, cols), dtype=np.int32)
    return (((x * 7 + y * 13) ^ (x * 31 + y * 17)) & 0xFF).astype(np.uint8)


def _seed_forest(rng, rows, cols, density):
    """Match the JS prototype: each cell is a tree with given density, age in
    [1, 60); the rest are EMPTY."""
    grid = np.where(
        rng.random((rows, cols)) < density,
        1 + (rng.random((rows, cols)) * 60).astype(np.uint8),
        EMPTY,
    ).astype(np.uint8)
    return grid


def _build_dir_table(spread_p, wdx, wdy):
    """Pre-compute, for each of the 8 neighbor offsets, both the per-direction
    spread probability and the *spread-direction code* that we'll record in
    `dir_grid` when a cell catches fire from that neighbor.

    If the burning neighbor is at offset (dy, dx) from the new cell, the fire
    is moving in direction (-dy, -dx). That spread direction is encoded into
    a single 0..8 index in row-major 3x3 order (see FIRE_DIR_GLYPHS)."""
    table = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            p = spread_p
            if dx == wdx or dy == wdy:
                p = min(1.0, p * 1.6)
            if dx == -wdx or dy == -wdy:
                p *= 0.4
            if abs(dx) + abs(dy) == 2:
                p *= 0.55
            spread_code = (-dy + 1) * 3 + (-dx + 1)  # 0..8
            table.append((dy, dx, float(p), int(spread_code)))
    return table


def _shifted_into(out, src, dy, dx):
    """Set out[y, x] = src[y + dy, x + dx], with off-grid cells = False/0.

    Equivalent to a non-wrapping shift by (-dy, -dx) so the value originally at
    (y + dy, x + dx) lands at (y, x). Boundary cells stay at zero."""
    rows, cols = src.shape
    out[:] = 0
    sy = slice(max(0, dy), rows + min(0, dy))
    sx = slice(max(0, dx), cols + min(0, dx))
    dy_dst = slice(max(0, -dy), rows + min(0, -dy))
    dx_dst = slice(max(0, -dx), cols + min(0, -dx))
    out[dy_dst, dx_dst] = src[sy, sx]


def _step_forest(grid, dir_table, growth_p, lightning_p, rng):
    """Vectorized simulation step.

    The spread step uses the *sequential-OR* form: for each of the 8 neighbor
    directions in iteration order, roll an independent Bernoulli, accept the
    first one that succeeds, and record that direction in `new_dir_grid`.
    This is mathematically equivalent (in distribution over `catch_fire`) to
    the product form `P(catch) = 1 - prod(1 - p_dir)`, but it has the side
    benefit of telling us *which* direction won, which we use to render the
    flame as an arrow pointing in the spread direction.

    Returns (new_grid, new_dir_grid) where new_dir_grid is uint8 0..8 and
    only meaningful for cells that became BURNING this step."""
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

    # Shuffle direction iteration order per step. Sequential-OR with a fixed
    # order would bias the recorded direction toward whichever direction
    # appears earliest in the loop; with a fresh shuffle each step, the
    # recorded direction is fairly weighted by each neighbor's p_dir.
    perm = rng.permutation(len(dir_table)).tolist()
    for idx in perm:
        dy, dx, p, spread_code = dir_table[idx]
        if p <= 0:
            continue
        _shifted_into(nb, is_burning, dy, dx)
        candidate = is_tree & nb & ~catch_fire
        if not candidate.any():
            continue
        rng.random(out=rand_buf, dtype=np.float32)
        ignite = candidate & (rand_buf < p)
        catch_fire |= ignite
        new_dir_grid[ignite] = spread_code

    rand_lightning = rng.random((rows, cols), dtype=np.float32)
    lightning = is_tree & ~catch_fire & (rand_lightning < lightning_p)
    # Lightning hits get a special dir_code so the renderer can draw a
    # white-hot flash for the strike's brief BURNING lifetime.
    new_dir_grid[lightning] = DIR_LIGHTNING

    rand_grow = rng.random((rows, cols), dtype=np.float32)
    empty_grew = is_empty & (rand_grow < growth_p)

    rand_ash_grow = rng.random((rows, cols), dtype=np.float32)
    ash_grew = is_ash & (rand_ash_grow < growth_p * 0.4)

    rand_ash_die = rng.random((rows, cols), dtype=np.float32)
    ash_died = is_ash & ~ash_grew & (rand_ash_die < 0.02)

    nxt = grid.copy()
    # State decay chain: BURNING -> EMBER -> SCORCHED -> ASH. The SCORCHED
    # micro-state lasts one simulation step and shows the burnt skeleton
    # before it dissolves to flat ash on the next step.
    nxt[is_burning] = EMBER
    nxt[is_ember] = SCORCHED
    nxt[is_scorched] = ASH
    # Tree aging: cap at 240. Use uint16 to dodge uint8 overflow at v=255.
    aged = np.minimum(grid.astype(np.uint16) + 1, 240).astype(np.uint8)
    nxt[is_tree] = aged[is_tree]
    nxt[catch_fire] = BURNING
    nxt[lightning] = BURNING
    nxt[empty_grew] = 1
    nxt[ash_grew] = 1
    nxt[ash_died] = EMPTY
    return nxt, new_dir_grid


def _dilate_neighborhood(mask, radius):
    """Boolean dilation of `mask` by an axis-aligned square of given radius
    (so radius=2 yields a 5x5 neighborhood, including the source). Returns
    a fresh array of the same dtype/shape."""
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
    """Unpack a uint32 0xRRGGBB array into three uint8 arrays."""
    r = ((rgb_arr >> 16) & 0xFF).astype(np.uint16)
    g = ((rgb_arr >> 8) & 0xFF).astype(np.uint16)
    b = (rgb_arr & 0xFF).astype(np.uint16)
    return r, g, b


def _pack_rgb(r, g, b):
    """Inverse of _split_rgb. Inputs are clipped to [0, 255]."""
    r = np.minimum(255, r).astype(np.uint32)
    g = np.minimum(255, g).astype(np.uint32)
    b = np.minimum(255, b).astype(np.uint32)
    return (r << 16) | (g << 8) | b


def _compute_frame(grid, dir_grid, hash_table, tick, wdx, wdy, particles):
    """Vectorized "what should each cell look like this frame?" pass.

    Returns parallel arrays:
      char_arr  : uint32 (rows, cols) — codepoint per cell
      rgb_arr   : uint32 (rows, cols) — packed 0xRRGGBB foreground per cell
                  (0 for whitespace cells, where color is irrelevant)

    Layered top-to-bottom:
      1. base render per state (empty / ash / scorched / ember / burning / tree)
      2. smoke replaces empty cells downwind of any active fire
      3. heat-glow halo: warm tint within radius 2 of any burning cell
      4. singed trees: trees adjacent to fire are dimmed and reddened
      5. wind particles: a few bright drifting cells overlaid on top
    """
    h = hash_table
    h32 = h.astype(np.int32)

    char_arr = np.full(grid.shape, 0x20, dtype=np.uint32)
    rgb_arr = np.zeros(grid.shape, dtype=np.uint32)

    # --- 1. Base render per state ------------------------------------------
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
        # Glyph: indexed by per-cell spread direction with a 4-frame cycle.
        # Phase by per-cell hash so neighboring cells are out-of-sync and
        # the field shimmers instead of blinking in unison.
        frame_idx = (h32 + tick) & 3
        char_arr[burning_mask] = _FIRE_DIR_CHARS[dir_grid, frame_idx][burning_mask]
        # Color: rotate through FIRE_PALETTE with per-cell flicker.
        ff_idx = (h32 + tick) % 5
        flicker = 0.75 + (((h32 * 3 + tick * 7) & 0xF).astype(np.float32) / 60.0)
        base = _FIRE_BASE[ff_idx]  # (rows, cols, 3)
        rgb_f = np.minimum(255.0, base * flicker[..., None]).astype(np.uint32)
        burning_rgb = (rgb_f[..., 0] << 16) | (rgb_f[..., 1] << 8) | rgb_f[..., 2]
        rgb_arr[burning_mask] = burning_rgb[burning_mask]
        # Lightning override: cells whose dir_code is DIR_LIGHTNING render
        # white-hot for the duration of their (brief) BURNING lifetime.
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

    # --- 2. Smoke drift (only when there's wind and active fire) -----------
    has_fire = burning_mask.any()
    if has_fire and (wdx != 0 or wdy != 0) and empty_mask.any():
        smoke_mask = np.zeros_like(empty_mask)
        nb = np.empty_like(burning_mask)
        # For each downwind step (1..3) ask: is there a burning cell that
        # would have drifted smoke into this empty cell? "(y,x) sees smoke
        # from (y - wdy*k, x - wdx*k)", i.e. shift burning by (-wdy*k, -wdx*k).
        for k in (1, 2, 3):
            _shifted_into(nb, burning_mask, -wdy * k, -wdx * k)
            smoke_mask |= nb
        smoke_mask &= empty_mask
        if smoke_mask.any():
            smoke_idx = (h32 + tick) % len(_SMOKE_CHARS)
            char_arr[smoke_mask] = _SMOKE_CHARS[smoke_idx][smoke_mask]
            rgb_arr[smoke_mask] = _SMOKE_RGB

    # --- 3. Heat-glow halo: warm tint on cells within radius 2 of fire ----
    if has_fire:
        halo = _dilate_neighborhood(burning_mask, 2) & ~burning_mask
        if halo.any():
            r, g, b = _split_rgb(rgb_arr)
            # Lerp toward (255, 80, 30) by 0.18.
            r = (r * 82 // 100) + (255 * 18 // 100)
            g = (g * 82 // 100) + (80 * 18 // 100)
            b = (b * 82 // 100) + (30 * 18 // 100)
            tinted = _pack_rgb(r, g, b)
            rgb_arr[halo] = tinted[halo]

    # --- 4. Singed trees: trees adjacent to fire are reddened/darkened ----
    if has_fire and tree_mask.any():
        danger = _dilate_neighborhood(burning_mask, 1) & tree_mask
        if danger.any():
            r, g, b = _split_rgb(rgb_arr)
            # Lerp toward (90, 30, 15) by 0.55, plus extra darken on green/blue.
            r = (r * 45 // 100) + (90 * 55 // 100)
            g = (g * 35 // 100) + (30 * 35 // 100)
            b = (b * 35 // 100) + (15 * 35 // 100)
            singed = _pack_rgb(r, g, b)
            rgb_arr[danger] = singed[danger]

    # --- 5. Wind particles overlay ----------------------------------------
    if particles is not None and len(particles) > 0:
        rows, cols = grid.shape
        ys = particles[:, 0].astype(np.int32) % rows
        xs = particles[:, 1].astype(np.int32) % cols
        char_arr[ys, xs] = ord("\u00b7")
        rgb_arr[ys, xs] = (148 << 16) | (148 << 8) | 138

    return char_arr, rgb_arr


def _emit_diff(char_arr, rgb_arr, prev, write):
    """Diff against the previous frame and write only what changed."""
    packed = (char_arr.astype(np.int64) << 24) | rgb_arr.astype(np.int64)
    diff = packed != prev
    parts = [BSU]

    if diff.any():
        prev[:] = packed
        ys, xs = np.nonzero(diff)
        # numpy returns ys/xs in row-major scan order, which is exactly what
        # the cursor-positioning logic below wants.
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
    spread = num(flags.get("spread"), 0.7, 0.05, 1)
    speed = num(flags.get("speed"), 1.0, 0.0, 10.0)
    fps = num_int(flags.get("fps"), 60, 10, 60)
    density = num(flags.get("density"), 0.55, 0, 1)
    wind_key = flags.get("wind")
    if not isinstance(wind_key, str) or wind_key not in WIND_DIRS:
        wind_key = "none"
    wdx, wdy = WIND_DIRS[wind_key]

    rng = np.random.default_rng()
    dir_table = _build_dir_table(spread, wdx, wdy)

    state = {
        "grid": None,
        "dir_grid": None,
        "hash": None,
        "prev": None,
        "particles": None,
        # State *before* the most recent simulation step, kept so we can
        # stagger per-cell visual transitions across the frames between
        # sim ticks (see below). Same shape/dtype as `grid` / `dir_grid`.
        "prev_grid": None,
        "prev_dir_grid": None,
        "frames_since_step": 0,
    }
    needs_resize = [True]

    # Wind particles drift across the screen at the wind direction; they are
    # purely a render overlay (no effect on the simulation). With calm wind
    # we skip them entirely — there's no preferred direction and stationary
    # specks would just look like dust on the screen.
    n_particles = 4 if (wdx != 0 or wdy != 0) else 0

    def do_resize():
        cols, rows = get_size()
        cols = max(20, cols)
        rows = max(8, rows)
        state["grid"] = _seed_forest(rng, rows, cols, density)
        # dir_grid only matters for currently-BURNING cells. A fresh seed has
        # no burning cells, so an all-zero (== NW spread) buffer is fine; the
        # value is overwritten the moment any cell ignites.
        state["dir_grid"] = np.zeros((rows, cols), dtype=np.uint8)
        state["hash"] = _build_hash_table(rows, cols)
        state["prev"] = np.full((rows, cols), -1, dtype=np.int64)
        # Initialize the "previous step" state to match current: the visual
        # interpolation will be a no-op until the first sim step actually
        # produces a difference between prev and current.
        state["prev_grid"] = state["grid"].copy()
        state["prev_dir_grid"] = state["dir_grid"].copy()
        if n_particles:
            state["particles"] = np.column_stack([
                rng.random(n_particles) * rows,
                rng.random(n_particles) * cols,
            ]).astype(np.float32)
        else:
            state["particles"] = None
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
    # Fractional step accumulator. `speed` is a multiplier where 1.0 keeps
    # the historical default pace (one simulation step per ~3 frames). With
    # this accumulator any non-negative speed works: speed=0.0 pauses the
    # sim entirely, speed=0.1 ticks once every ~30 frames, speed=5.0 runs
    # five steps for every three frames, etc.
    DEFAULT_FRAMES_PER_STEP = 3.0
    steps_per_frame = speed / DEFAULT_FRAMES_PER_STEP
    step_accum = 0.0
    # How many render frames we expect between simulation steps. Used as the
    # denominator when staggering per-cell visual transitions across frames.
    # If steps_per_frame >= 1 (speed >= 3 at default frame budget), there are
    # no "in-between" frames and we skip the smoothing path entirely.
    frames_per_step = (1.0 / steps_per_frame) if steps_per_frame > 0 else 0.0
    smooth_transitions = frames_per_step > 1.0

    next_frame = time.monotonic()
    while True:
        if needs_resize[0]:
            needs_resize[0] = False
            do_resize()

        tick += 1
        step_accum += steps_per_frame
        # Catch up the simulation if speed > 1, do nothing if speed == 0.
        # Cap iterations defensively so a freak large delta can't spin here.
        max_steps_this_frame = 8
        steps_this_frame = 0
        stepped = False
        while step_accum >= 1.0 and steps_this_frame < max_steps_this_frame:
            # Snapshot the pre-step state on the first iteration so the visual
            # transition between prev->current can be staggered across the
            # following frames. Subsequent iterations within the same frame
            # (only possible when speed > 3) overwrite intermediate snapshots,
            # which is fine because we disable smoothing in that regime.
            if not stepped:
                state["prev_grid"] = state["grid"].copy()
                state["prev_dir_grid"] = state["dir_grid"].copy()
            state["grid"], state["dir_grid"] = _step_forest(
                state["grid"], dir_table, growth, lightning, rng
            )
            step_accum -= 1.0
            steps_this_frame += 1
            stepped = True

        if stepped:
            state["frames_since_step"] = 0
        else:
            state["frames_since_step"] += 1

        # Advance wind particles per render frame (decoupled from sim speed).
        # Wrap on screen edges so they keep drifting indefinitely.
        if state["particles"] is not None:
            rows_p, cols_p = state["grid"].shape
            particle_speed = 0.5
            state["particles"][:, 0] = (
                state["particles"][:, 0] + wdy * particle_speed
            ) % rows_p
            state["particles"][:, 1] = (
                state["particles"][:, 1] + wdx * particle_speed
            ) % cols_p

        # Stagger per-cell state flips across the frames between sim ticks.
        # Each cell has a deterministic flip threshold flip_at_t in [0, 1)
        # derived from its hash. As "transition fraction" t advances from 0
        # toward 1 between sim ticks, cells with flip_at_t <= t show the new
        # (current) state, the rest still show the previous state. After
        # frames_per_step frames, t reaches 1 and every cell has flipped.
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
            wdx, wdy, state["particles"],
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
