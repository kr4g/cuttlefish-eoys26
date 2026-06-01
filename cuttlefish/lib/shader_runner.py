import signal
import sys
import time

import numpy as np

from .args import num, num_int, parse_flags
from .clock import SharedClock
from .spectral import build_luts
from .terminal import (
    BSU,
    CLEAR_SCREEN,
    ESU,
    HOME,
    RESET,
    enter_fullscreen,
    exit_fullscreen,
    get_size,
    install_exit_handlers,
    move_to,
    require_tty,
)
from .viewport import build_fields, resolve_viewport


COMMON_USAGE = (
    "[--freq 0.5..20] [--amount 0..10] [--sym 1..16] [--complexity 1..12] "
    "[--zoom 0.45..3.5] [--aspect 0.2..2.0] [--speed -3..3] [--fps 10..60] "
    "[--grid-cols N] [--grid-rows N] [--col N] [--row N] [--hostname NAME] "
    "[--tile-cols N] [--tile-rows N] "
    "[--epoch-unix T] [--epoch-offset T] [--color-steps 8..512] "
    "[--emit auto|full|diff] [--diff-threshold 0..1] "
    "[--char-rate 0..4] [--char-steps 8..2048]"
)


def _parse_epoch(val):
    if val is None or val is True:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_optional_int(val, lo, hi):
    if val is None or val is True:
        return None
    try:
        n = int(float(val))
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _parse_int_literal(val):
    if val is None or val is True:
        return None
    try:
        if isinstance(val, str):
            return int(val, 0)
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _color_escape(color, cache):
    esc = cache.get(color)
    if esc is not None:
        return esc
    rr = (color >> 16) & 255
    gg = (color >> 8) & 255
    bb = color & 255
    esc = f"\x1b[38;2;{rr};{gg};{bb}m"
    cache[color] = esc
    return esc


def _char_escape(codepoint, cache):
    out = cache.get(codepoint)
    if out is not None:
        return out
    out = chr(codepoint)
    cache[codepoint] = out
    return out


def _emit_full(codepoints, rgb24):
    rows, cols = codepoints.shape
    parts = [BSU, HOME]
    color_cache = {}
    char_cache = {}
    for r in range(rows):
        last_color = -1
        row_cp = codepoints[r]
        row_rgb = rgb24[r]
        for c in range(cols):
            color = int(row_rgb[c])
            if color != last_color:
                parts.append(_color_escape(color, color_cache))
                last_color = color
            parts.append(_char_escape(int(row_cp[c]), char_cache))
        if r != rows - 1:
            parts.append("\n")
    parts.append(RESET)
    parts.append(ESU)
    sys.stdout.write("".join(parts))
    sys.stdout.flush()


def _emit_diff(codepoints, rgb24, diff):
    parts = [BSU]
    if diff.any():
        ys, xs = np.nonzero(diff)
        chars = codepoints[ys, xs].tolist()
        rgbs = rgb24[ys, xs].tolist()
        ys = ys.tolist()
        xs = xs.tolist()
        color_cache = {}
        char_cache = {}
        last_color = -1
        cur_r = -1
        cur_c = -1
        for y, x, ch, rgb in zip(ys, xs, chars, rgbs):
            if cur_r != y or cur_c != x:
                parts.append(move_to(y + 1, x + 1))
                cur_r = y
                cur_c = x
            if ch == 0x20:
                parts.append(" ")
            else:
                if rgb != last_color:
                    parts.append(_color_escape(int(rgb), color_cache))
                    last_color = rgb
                parts.append(_char_escape(int(ch), char_cache))
            cur_c += 1
    parts.append(ESU)
    sys.stdout.write("".join(parts))
    sys.stdout.flush()


def run_terminal_animation(meta, effect_fn, argv=None, defaults=None):
    if argv is None:
        argv = []
    if defaults is None:
        defaults = {}

    if "-h" in argv or "--help" in argv:
        out = sys.stdout
        out.write(f"{meta['name']} - {meta['description']}\n")
        out.write("Usage:\n")
        out.write(f"  python -m cuttlefish {meta['name']} {meta.get('usage', COMMON_USAGE)}\n")
        return 0

    flags = parse_flags(argv)
    if "help" in flags:
        out = sys.stdout
        out.write(f"{meta['name']} - {meta['description']}\n")
        out.write("Usage:\n")
        out.write(f"  python -m cuttlefish {meta['name']} {meta.get('usage', COMMON_USAGE)}\n")
        return 0

    char_min_raw = _parse_int_literal(flags.get("char-min"))
    char_max_raw = _parse_int_literal(flags.get("char-max"))
    params = {
        "freq": num(flags.get("freq"), defaults.get("freq", 7.0), 0.5, 20.0),
        "amount": num(flags.get("amount"), defaults.get("amount", 3.0), 0.0, 10.0),
        "sym": num(flags.get("sym"), defaults.get("sym", 7.0), 1.0, 16.0),
        "complexity": num_int(flags.get("complexity"), defaults.get("complexity", 5), 1, 12),
        "char_mode": str(flags.get("char-mode") or defaults.get("char_mode", "ramp")).lower(),
        "char_mix": num(flags.get("char-mix"), defaults.get("char_mix", 1.0), 0.0, 1.0),
        "char_min": max(33, min(0x10FFFD, defaults.get("char_min", 0x2190) if char_min_raw is None else char_min_raw)),
        "char_max": max(33, min(0x10FFFD, defaults.get("char_max", 0x2BFF) if char_max_raw is None else char_max_raw)),
        "char_rate": num(flags.get("char-rate"), defaults.get("char_rate", 0.35), 0.0, 4.0),
        "char_steps": num_int(flags.get("char-steps"), defaults.get("char_steps", 192), 8, 2048),
    }
    if params["char_max"] < params["char_min"]:
        params["char_max"] = params["char_min"]
    fps = num_int(flags.get("fps"), defaults.get("fps", 60), 10, 60)
    speed = num(flags.get("speed"), defaults.get("speed", 1.0), -3.0, 3.0)
    zoom = num(flags.get("zoom"), defaults.get("zoom", 1.0), 0.45, 3.5)
    aspect = num(flags.get("aspect"), defaults.get("aspect", 0.5), 0.2, 2.0)
    tile_cols = _parse_optional_int(flags.get("tile-cols"), 8, 2000)
    tile_rows = _parse_optional_int(flags.get("tile-rows"), 4, 1200)
    color_steps = num_int(flags.get("color-steps"), defaults.get("color_steps", 64), 8, 512)
    emit_mode = str(flags.get("emit") or defaults.get("emit", "auto")).lower()
    if emit_mode not in ("auto", "full", "diff"):
        emit_mode = "auto"
    diff_threshold = num(flags.get("diff-threshold"), defaults.get("diff_threshold", 0.35), 0.0, 1.0)
    epoch_unix = _parse_epoch(flags.get("epoch-unix"))
    epoch_offset = num(flags.get("epoch-offset"), defaults.get("epoch_offset", 0.0), -1_000_000.0, 1_000_000.0)

    viewport = resolve_viewport(flags)
    clock = SharedClock(epoch_unix=epoch_unix, epoch_offset=epoch_offset)
    frame_dt = 1.0 / fps
    glyph_lut, rgb_lut = build_luts(color_steps)

    require_tty()
    enter_fullscreen()
    cleanup = install_exit_handlers(exit_fullscreen)

    resized = [False]
    prev_w = -1
    prev_h = -1
    fields = None
    prev_state = None
    next_frame = time.monotonic()

    prev_sigwinch = None
    if hasattr(signal, "SIGWINCH"):
        prev_sigwinch = signal.getsignal(signal.SIGWINCH)

        def _on_resize(_signum, _frame):
            resized[0] = True

        signal.signal(signal.SIGWINCH, _on_resize)

    try:
        while True:
            cols, lines = get_size()
            if cols < 2 or lines < 2:
                time.sleep(0.05)
                continue

            if resized[0] or cols != prev_w or lines != prev_h or fields is None:
                prev_w = cols
                prev_h = lines
                fields = build_fields(
                    cols,
                    lines,
                    viewport,
                    zoom=zoom,
                    aspect=aspect,
                    tile_cols=tile_cols,
                    tile_rows=tile_rows,
                )
                resized[0] = False
                prev_state = None
                sys.stdout.write(CLEAR_SCREEN)

            x, y, ix, iy = fields
            t = clock.now() * speed
            out = effect_fn(x, y, ix, iy, t, params)
            custom_codepoints = None
            custom_rgb = None
            if isinstance(out, tuple):
                intensity = out[0]
                if len(out) > 1:
                    custom_codepoints = out[1]
                if len(out) > 2:
                    custom_rgb = out[2]
            else:
                intensity = out
            safe = np.clip(np.nan_to_num(intensity, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
            idx = np.clip((safe * (color_steps - 1)).astype(np.int32), 0, color_steps - 1)
            if custom_codepoints is None:
                codepoints = glyph_lut[idx]
            else:
                codepoints = np.asarray(custom_codepoints, dtype=np.uint32)
            if custom_rgb is None:
                rgb24 = rgb_lut[idx]
            else:
                rgb24 = np.asarray(custom_rgb, dtype=np.uint32)
            frame_state = (codepoints.astype(np.int64) << 24) | rgb24.astype(np.int64)

            if emit_mode == "full":
                _emit_full(codepoints, rgb24)
                prev_state = None
            else:
                if prev_state is None:
                    _emit_full(codepoints, rgb24)
                    prev_state = frame_state.copy()
                else:
                    diff = frame_state != prev_state
                    if emit_mode == "diff":
                        _emit_diff(codepoints, rgb24, diff)
                    else:
                        changed = float(np.count_nonzero(diff)) / float(diff.size)
                        if changed > diff_threshold:
                            _emit_full(codepoints, rgb24)
                        else:
                            _emit_diff(codepoints, rgb24, diff)
                    prev_state[:] = frame_state

            next_frame += frame_dt
            sleep_for = next_frame - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_frame = time.monotonic()
    except KeyboardInterrupt:
        return 0
    finally:
        if prev_sigwinch is not None and hasattr(signal, "SIGWINCH"):
            signal.signal(signal.SIGWINCH, prev_sigwinch)
        cleanup()


def run_shader_animation(meta, effect_fn, argv=None, defaults=None):
    return run_terminal_animation(meta, effect_fn, argv, defaults)
