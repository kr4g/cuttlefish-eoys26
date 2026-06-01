import time
import unicodedata

import numpy as np

from ..lib.args import num, num_int, parse_flags
from ..lib.shader_runner import run_terminal_animation

try:
    from wcwidth import wcwidth as _wcwidth
except Exception:
    _wcwidth = None


_MASK64 = (1 << 64) - 1
_SAFE_RANGE_CACHE = {}
_EVAL_GLOBALS = {"__builtins__": {}}
_BLOCKED_CP_RANGES = (
    (0x2400, 0x243F),
    (0xFFF9, 0xFFFB),
)
_BLOCKED_NAME_TERMS = (
    "LINE FEED",
    "CARRIAGE RETURN",
    "RETURN SYMBOL",
    "NEXT LINE",
    "NEW LINE",
    "PARAGRAPH SEPARATOR",
    "PILCROW",
    "LINE SEPARATOR",
    "FORM FEED",
    "VERTICAL TABULATION",
    "SYMBOL FOR",
)
_BIT_COLOR_MODES = (
    "bit-spectral-soft",
    "bit-spectral-hard",
    "bit-spectral-neon",
    "bit-spectral-bands",
    "bit-rgb-fold",
    "bit-rgb-interference",
    "bitplanes-plus",
)
_FORMULA_SPECS = [
    ("001", "x ^ y ^ t"),
    ("011", "n & (n >> 8)"),
    ("017", "(r & (r >> 8)) ^ (p & (p >> 8))"),
    ("018", "(n & (n >> 8)) & (r | p)"),
    ("026", "(n ^ (n >> 1)) & ((r ^ (r >> 1)) | (p ^ (p >> 1)))"),
    ("028", "((r >> 1) ^ (r | (r << 1))) ^ ((p >> 1) ^ (p | (p << 1)))"),
    ("032", "((r >> 1) ^ r ^ (r << 1)) ^ ((p >> 1) ^ p ^ (p << 1))"),
    ("037", "((r >> a) & (p >> b)) | ((n >> s) & (q >> c))"),
    ("039", "((r & (r >> a)) | ((r >> b) & ~r)) ^ ((p & (p >> b)) | ((p >> a) & ~p))"),
    ("041", "((r | (r >> a)) & (r ^ (r >> b))) ^ ((p | (p >> b)) & (p ^ (p >> a)))"),
    ("043", "(r >> ((t >> a) & 7)) & (p >> ((t >> b) & 7))"),
    ("060", "xorshift(n) & ((r >> a) | (p >> b))"),
    ("061", "xorshift(r) ^ xorshift(p)"),
    ("064", "(r * (42 & (r >> 10))) ^ (p * (42 & (p >> 10)))"),
    ("065", "(n * 5 & n >> 7) | (n * 3 & n >> 10)"),
    ("066", "((r * 5 & r >> 7) | (r * 3 & r >> 10)) ^ ((p * 5 & p >> 7) | (p * 3 & p >> 10))"),
    ("068", "((r * 9 & r >> 4) | (r * 5 & r >> 7) | (r * 3 & r >> 10)) ^ ((p * 9 & p >> 4) | (p * 5 & p >> 7) | (p * 3 & p >> 10))"),
    ("071", "((n >> 7) | n | (n >> 6)) * 10 + 4 * ((n & (n >> 13)) | (n >> 6))"),
    ("080", "z ^ (z >> a) ^ t"),
    ("081", "z & ((z + t) >> 8)"),
    ("082", "((z + t) >> 4) & ((z + t) >> 8)"),
    ("083", "(z >> s) ^ r ^ p"),
    ("089", "(((x * x - y * y + t) >> 4) & ((x * x - y * y + t) >> 8))"),
    ("097", "~((n & (n >> a)) | ((n >> b) & ~n)) & ((r ^ (r >> 1)) | (p ^ (p >> 1)))"),
    ("100", "((x + t) & (y - t)) ^ ((x - t) | (y + t))"),
    ("106", "((x + (y >> s) + t) & m) * ((y + (x >> s) - t) | a)"),
]
_FORMULAS = [{"id": fid, "code": compile(expr, f"<bitwise-{fid}>", "eval")} for fid, expr in _FORMULA_SPECS]

meta = {
    "name": "bitwise",
    "description": "Bitwise formula lab with timed random formula and variable switching.",
    "usage": (
        "[--formula-seconds N] [--vars-seconds N] [--seed N] [--time-scale N] "
        "[--color-cycle-rate N] "
        "[--freq 0.5..20] [--amount 0..10] [--sym 1..16] [--complexity 1..12] "
        "[--zoom 0.45..3.5] [--aspect 0.2..2.0] [--speed -3..3] [--fps 10..60] "
        "[--grid-cols N] [--grid-rows N] [--col N] [--row N] [--hostname NAME] "
        "[--tile-cols N] [--tile-rows N] [--epoch-unix T] [--epoch-offset T] "
        "[--color-steps 8..512] [--emit auto|full|diff] [--diff-threshold 0..1] "
        "[--char-mode ramp|formula] [--char-mix 0..1] [--char-min N] [--char-max N] "
        "[--char-rate 0..4] [--char-steps 8..2048]"
    ),
}


def _wavelength_to_rgb(w):
    if w < 440.0:
        r = (440.0 - w) / 60.0
        g = 0.0
        b = 1.0
    elif w < 490.0:
        r = 0.0
        g = (w - 440.0) / 50.0
        b = 1.0
    elif w < 510.0:
        r = 0.0
        g = 1.0
        b = (510.0 - w) / 20.0
    elif w < 580.0:
        r = (w - 510.0) / 70.0
        g = 1.0
        b = 0.0
    elif w < 645.0:
        r = 1.0
        g = (645.0 - w) / 65.0
        b = 0.0
    else:
        r = 1.0
        g = 0.0
        b = 0.0

    f = 1.0
    if w < 420.0:
        f = 0.3 + 0.7 * ((w - 380.0) / 40.0)
    elif w > 700.0:
        f = 0.3 + 0.7 * ((780.0 - w) / 80.0)

    rr = int(max(0.0, min(255.0, 255.0 * (max(0.0, r * f) ** 0.78))))
    gg = int(max(0.0, min(255.0, 255.0 * (max(0.0, g * f) ** 0.78))))
    bb = int(max(0.0, min(255.0, 255.0 * (max(0.0, b * f) ** 0.78))))
    return rr, gg, bb


_SPECTRAL_LUT = np.array(
    [_wavelength_to_rgb(380.0 + (k * 400.0) / 255.0) for k in range(256)],
    dtype=np.uint32,
)


def _splitmix64(x):
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    z ^= z >> 31
    return z & _MASK64


def _rand_u32(seed, epoch, slot):
    x = (int(seed) & _MASK64) ^ (((int(epoch) + 1) * 0xA0761D6478BD642F) & _MASK64)
    x ^= (((int(slot) + 1) * 0xE7037ED1A0B428DB) & _MASK64)
    return _splitmix64(x) & 0xFFFFFFFF


def _rand_vars(seed, epoch):
    return {
        "a": _rand_u32(seed, epoch, 1) & 15,
        "b": _rand_u32(seed, epoch, 2) & 15,
        "c": _rand_u32(seed, epoch, 3) & 15,
        "d": _rand_u32(seed, epoch, 4) & 31,
        "shift": _rand_u32(seed, epoch, 5) & 15,
        "m": 1 + (_rand_u32(seed, epoch, 6) % 255),
    }


def _xorshift32(v):
    u = np.asarray(v, dtype=np.uint32)
    u ^= u << np.uint32(13)
    u ^= u >> np.uint32(17)
    u ^= u << np.uint32(5)
    return u.view(np.int32)


def _mix8(v, a, b, c, d=0):
    u = np.asarray(v, dtype=np.uint32)
    return (
        u
        ^ (u >> np.uint32(a))
        ^ (u >> np.uint32(b))
        ^ (u << np.uint32(c))
        ^ (u << np.uint32(d))
    ) & np.uint32(255)


def _lerp_u8(a, b, t):
    return np.clip(
        a.astype(np.float32) + (b.astype(np.float32) - a.astype(np.float32)) * np.float32(t),
        0.0,
        255.0,
    ).astype(np.uint32)


def _mode_rgb(mode_idx, value_u):
    if mode_idx == 0:
        k0 = _mix8(value_u, 7, 13, 3)
        k1 = _mix8(value_u, 5, 11, 1, 4)
        q = _mix8(value_u, 3, 17, 2).astype(np.float32) / 255.0
        amp = 0.35 + (_mix8(value_u, 9, 19, 5).astype(np.float32) / 255.0) * 0.65
        a = _SPECTRAL_LUT[k0]
        b = _SPECTRAL_LUT[k1]
        r = np.clip((a[..., 0] + (b[..., 0] - a[..., 0]) * q) * amp, 0.0, 255.0).astype(np.uint32)
        g = np.clip((a[..., 1] + (b[..., 1] - a[..., 1]) * q) * amp, 0.0, 255.0).astype(np.uint32)
        bch = np.clip((a[..., 2] + (b[..., 2] - a[..., 2]) * q) * amp, 0.0, 255.0).astype(np.uint32)
        return r, g, bch
    if mode_idx == 1:
        a = _SPECTRAL_LUT[_mix8(value_u, 3, 9, 1, 6)]
        b = _SPECTRAL_LUT[_mix8(value_u, 5, 15, 2)]
        gate = _mix8(value_u, 8, 16, 4)
        r = (a[..., 0] ^ b[..., 0] ^ gate) & np.uint32(255)
        g = (a[..., 1] ^ b[..., 1] ^ (gate >> np.uint32(1))) & np.uint32(255)
        bch = (a[..., 2] ^ b[..., 2] ^ (np.uint32(255) - gate)) & np.uint32(255)
        return r.astype(np.uint32), g.astype(np.uint32), bch.astype(np.uint32)
    if mode_idx == 2:
        base = _SPECTRAL_LUT[_mix8(value_u, 4, 10, 2, 7)]
        accent = _SPECTRAL_LUT[_mix8(value_u, 6, 14, 1, 5)]
        glow = np.uint32(96) + (_mix8(value_u, 5, 13, 3) & np.uint32(159))
        cut = _mix8(value_u, 3, 17, 6)
        r = np.clip(((base[..., 0] * glow) >> np.uint32(8)) + ((accent[..., 0] * cut) >> np.uint32(9)), 0, 255).astype(np.uint32)
        g = np.clip(((base[..., 1] * glow) >> np.uint32(8)) + ((accent[..., 1] * (np.uint32(255) - cut)) >> np.uint32(9)), 0, 255).astype(np.uint32)
        bch = np.clip(((base[..., 2] * glow) >> np.uint32(8)) + ((accent[..., 2] * cut) >> np.uint32(9)), 0, 255).astype(np.uint32)
        return r, g, bch
    if mode_idx == 3:
        a = _SPECTRAL_LUT[(value_u ^ (value_u >> np.uint32(8))) & np.uint32(255)]
        b = _SPECTRAL_LUT[((value_u >> np.uint32(4)) ^ (value_u >> np.uint32(16))) & np.uint32(255)]
        c = _SPECTRAL_LUT[((value_u >> np.uint32(12)) ^ (value_u >> np.uint32(20))) & np.uint32(255)]
        g0 = (value_u >> np.uint32(0)) & np.uint32(255)
        g1 = (value_u >> np.uint32(8)) & np.uint32(255)
        g2 = (value_u >> np.uint32(16)) & np.uint32(255)
        r = np.clip((a[..., 0] * g0 + b[..., 0] * g1 + c[..., 0] * g2) // np.uint32(384), 0, 255).astype(np.uint32)
        g = np.clip((a[..., 1] * g0 + b[..., 1] * g1 + c[..., 1] * g2) // np.uint32(384), 0, 255).astype(np.uint32)
        bch = np.clip((a[..., 2] * g0 + b[..., 2] * g1 + c[..., 2] * g2) // np.uint32(384), 0, 255).astype(np.uint32)
        return r, g, bch
    if mode_idx == 4:
        return (
            _mix8(value_u, 3, 11, 1, 6).astype(np.uint32),
            _mix8(value_u, 5, 13, 2, 7).astype(np.uint32),
            _mix8(value_u, 7, 15, 3, 4).astype(np.uint32),
        )
    if mode_idx == 5:
        a = _mix8(value_u, 4, 9, 2)
        b = _mix8(value_u, 6, 12, 1, 5)
        c = _mix8(value_u, 8, 14, 3, 7)
        return ((a ^ b) & np.uint32(255), (b ^ c) & np.uint32(255), (c ^ a) & np.uint32(255))
    return (
        (((value_u >> np.uint32(0)) & np.uint32(1)) * np.uint32(64))
        + (((value_u >> np.uint32(3)) & np.uint32(1)) * np.uint32(64))
        + (((value_u >> np.uint32(6)) & np.uint32(1)) * np.uint32(127)),
        (((value_u >> np.uint32(1)) & np.uint32(1)) * np.uint32(64))
        + (((value_u >> np.uint32(4)) & np.uint32(1)) * np.uint32(64))
        + (((value_u >> np.uint32(7)) & np.uint32(1)) * np.uint32(127)),
        (((value_u >> np.uint32(2)) & np.uint32(1)) * np.uint32(64))
        + (((value_u >> np.uint32(5)) & np.uint32(1)) * np.uint32(64))
        + (((value_u >> np.uint32(8)) & np.uint32(1)) * np.uint32(127)),
    )


def _make_mode_order(seed, cycle_idx, avoid_first):
    order = list(range(len(_BIT_COLOR_MODES)))
    order.sort(key=lambda idx: int(_rand_u32(seed, cycle_idx, 100 + idx)))
    if avoid_first is not None and len(order) > 1 and order[0] == avoid_first:
        order[0], order[1] = order[1], order[0]
    return order


def _advance_color_cycle(state, t_base, rate):
    if rate <= 0.0:
        cur = state["order"][state["index"]]
        nxt = state["order"][(state["index"] + 1) % len(state["order"])]
        return cur, nxt, 0.0

    elapsed = t_base * rate
    step = int(np.floor(elapsed))
    phase = float(elapsed - step)
    if step < state["step"]:
        state["cycle"] = 0
        state["order"] = _make_mode_order(state["seed"], 0, None)
        state["index"] = 0
        state["step"] = step
    elif step != state["step"]:
        delta = max(0, step - state["step"])
        for _ in range(delta):
            state["index"] += 1
            if state["index"] >= len(state["order"]) - 1:
                last = state["order"][-1]
                state["cycle"] += 1
                state["order"] = _make_mode_order(state["seed"], state["cycle"], last)
                state["index"] = 0
        state["step"] = step
    cur = state["order"][state["index"]]
    nxt = state["order"][(state["index"] + 1) % len(state["order"])]
    return cur, nxt, phase


def _pack_rgb24(r, g, b):
    return (r.astype(np.uint32) << np.uint32(16)) | (g.astype(np.uint32) << np.uint32(8)) | b.astype(np.uint32)


def _build_safe_codepoints(cmin, cmax):
    safe = []
    for cp in range(cmin, cmax + 1):
        blocked = False
        for lo, hi in _BLOCKED_CP_RANGES:
            if lo <= cp <= hi:
                blocked = True
                break
        if blocked:
            continue
        ch = chr(cp)
        if ch in ("\n", "\r", "\v", "\f", "\t", "\u2028", "\u2029"):
            continue
        cat = unicodedata.category(ch)
        if cat[0] in ("C", "M", "Z"):
            continue
        name = unicodedata.name(ch, "")
        if any(term in name for term in _BLOCKED_NAME_TERMS):
            continue
        if ch.isspace():
            continue
        if not ch.isprintable():
            continue
        if _wcwidth is not None:
            if _wcwidth(ch) != 1:
                continue
        elif unicodedata.east_asian_width(ch) not in ("N", "Na", "H"):
            continue
        safe.append(cp)
    if not safe:
        safe = [0x00B7]
    return np.array(safe, dtype=np.uint32)


def _safe_codepoint_table(cmin, cmax):
    key = (cmin, cmax)
    table = _SAFE_RANGE_CACHE.get(key)
    if table is None:
        table = _build_safe_codepoints(cmin, cmax)
        _SAFE_RANGE_CACHE[key] = table
    return table


def _formula_effect_factory(config):
    state = {
        "formula_epoch": None,
        "var_epoch": None,
        "formula": _FORMULAS[0],
        "vars": _rand_vars(config["seed"], 0),
        "color": {
            "seed": config["seed"],
            "order": _make_mode_order(config["seed"], 0, None),
            "index": 0,
            "step": 0,
            "cycle": 0,
        },
    }

    def effect(_x, _y, ix, iy, t, p):
        t_base = t if t >= 0 else -t

        if config["formula_seconds"] <= 0:
            f_epoch = 0
        else:
            f_epoch = int(np.floor(t_base / config["formula_seconds"]))
        if state["formula_epoch"] != f_epoch:
            f_idx = int(_rand_u32(config["seed"], f_epoch, 0) % len(_FORMULAS))
            state["formula"] = _FORMULAS[f_idx]
            state["formula_epoch"] = f_epoch

        if config["vars_seconds"] <= 0:
            v_epoch = 0
        else:
            v_epoch = int(np.floor(t_base / config["vars_seconds"]))
        if state["var_epoch"] != v_epoch:
            state["vars"] = _rand_vars(config["seed"], v_epoch)
            state["var_epoch"] = v_epoch

        x = np.asarray(ix, dtype=np.int32)
        y = np.asarray(iy, dtype=np.int32)

        vars_cur = state["vars"]
        a = np.int32(vars_cur["a"])
        b = np.int32(vars_cur["b"])
        c = np.int32(vars_cur["c"])
        d = np.int32(vars_cur["d"])
        shift = np.int32(vars_cur["shift"])
        m = np.int32(vars_cur["m"])
        s = np.int32(shift & 15)
        aa = np.int32(a & 7)
        bb = np.int32(b & 7)

        def eval_value(t_i):
            n = np.asarray(x + (y << s) + t_i, dtype=np.int32)
            q = np.asarray((x << aa) + y - t_i, dtype=np.int32)
            r = np.asarray(x + y + (t_i << (aa & 3)), dtype=np.int32)
            p_arr = np.asarray(x - y + (t_i << (bb & 3)), dtype=np.int32)
            z = np.asarray((x * x + y * y) + t_i, dtype=np.int32)
            local = {
                "x": x,
                "y": y,
                "t": t_i,
                "a": a,
                "b": b,
                "c": c,
                "d": d,
                "s": s,
                "m": m,
                "n": n,
                "q": q,
                "r": r,
                "p": p_arr,
                "z": z,
                "xorshift": _xorshift32,
            }
            return np.asarray(eval(state["formula"]["code"], _EVAL_GLOBALS, local), dtype=np.int32).view(np.uint32)

        t_scaled = t * config["time_scale"]
        t_floor = float(np.floor(t_scaled))
        t_frac = float(t_scaled - t_floor)
        t_i0 = np.int32(t_floor)
        value_u0 = eval_value(t_i0)
        value_u1 = eval_value(np.int32(t_floor + 1.0)) if t_frac > 1e-6 else value_u0

        current_mode, next_mode, phase = _advance_color_cycle(state["color"], t_base, config["color_cycle_rate"])
        r00, g00, b00 = _mode_rgb(current_mode, value_u0)
        if phase > 0.0 and next_mode != current_mode:
            r01, g01, b01 = _mode_rgb(next_mode, value_u0)
            rgb0_r = _lerp_u8(r00, r01, phase)
            rgb0_g = _lerp_u8(g00, g01, phase)
            rgb0_b = _lerp_u8(b00, b01, phase)
        else:
            rgb0_r, rgb0_g, rgb0_b = r00, g00, b00

        if t_frac > 1e-6:
            r10, g10, b10 = _mode_rgb(current_mode, value_u1)
            if phase > 0.0 and next_mode != current_mode:
                r11, g11, b11 = _mode_rgb(next_mode, value_u1)
                rgb1_r = _lerp_u8(r10, r11, phase)
                rgb1_g = _lerp_u8(g10, g11, phase)
                rgb1_b = _lerp_u8(b10, b11, phase)
            else:
                rgb1_r, rgb1_g, rgb1_b = r10, g10, b10
            rch = _lerp_u8(rgb0_r, rgb1_r, t_frac)
            gch = _lerp_u8(rgb0_g, rgb1_g, t_frac)
            bch = _lerp_u8(rgb0_b, rgb1_b, t_frac)
        else:
            rch, gch, bch = rgb0_r, rgb0_g, rgb0_b
        rgb24 = _pack_rgb24(rch, gch, bch)

        intensity0 = ((value_u0 & np.uint32(255)).astype(np.float32)) / 255.0
        if t_frac > 1e-6:
            intensity1 = ((value_u1 & np.uint32(255)).astype(np.float32)) / 255.0
            intensity = np.clip(
                intensity0 * np.float32(1.0 - t_frac) + intensity1 * np.float32(t_frac),
                0.0,
                1.0,
            )
        else:
            intensity = intensity0

        mode = str(p.get("char_mode", "formula")).lower()
        if mode not in ("formula", "code", "codes", "numeric", "symbols"):
            return intensity, None, rgb24

        cmin = int(p.get("char_min", 0x2190))
        cmax = int(p.get("char_max", 0x2BFF))
        safe_table = _safe_codepoint_table(cmin, cmax)
        mix = np.clip(float(p.get("char_mix", 1.0)), 0.0, 1.0)
        char_steps = max(8, int(p.get("char_steps", 192)))
        char_rate = max(0.0, float(p.get("char_rate", 0.35)))
        char_scaled = t_base * config["time_scale"] * char_rate
        char_floor = float(np.floor(char_scaled))
        char_frac = float(char_scaled - char_floor)
        char_t0 = np.uint32(int(char_floor) & 0xFFFFFFFF)
        char_src0 = value_u0 ^ (value_u0 >> np.uint32(7)) ^ (value_u0 << np.uint32(9)) ^ char_t0
        char_norm0 = ((char_src0 & np.uint32(0xFFFF)).astype(np.float32)) / 65535.0
        if t_frac > 1e-6:
            char_t1 = np.uint32(int(char_floor + 1.0) & 0xFFFFFFFF)
            char_src1 = value_u1 ^ (value_u1 >> np.uint32(7)) ^ (value_u1 << np.uint32(9)) ^ char_t1
            char_norm1 = ((char_src1 & np.uint32(0xFFFF)).astype(np.float32)) / 65535.0
            char_norm = np.clip(
                char_norm0 * np.float32(1.0 - char_frac) + char_norm1 * np.float32(char_frac),
                0.0,
                1.0,
            )
        else:
            char_norm = char_norm0
        mixed = np.clip(char_norm * mix + intensity * (1.0 - mix), 0.0, 1.0)
        mixed = np.floor(mixed * (char_steps - 1)) / float(char_steps - 1)
        idx = np.clip((mixed * (safe_table.size - 1)).astype(np.int32), 0, safe_table.size - 1)
        codepoints = safe_table[idx]
        return intensity, codepoints, rgb24

    return effect


def run(argv=None):
    if argv is None:
        argv = []
    flags = parse_flags(argv)
    config = {
        "formula_seconds": num(flags.get("formula-seconds"), 120.0, 0.0, 3600.0),
        "vars_seconds": num(flags.get("vars-seconds"), 30.0, 0.0, 3600.0),
        "color_cycle_rate": num(flags.get("color-cycle-rate"), 0.1, 0.0, 0.5),
        "seed": num_int(flags.get("seed"), int(time.time()) & 0x7FFFFFFF, 0, 0x7FFFFFFF),
        "time_scale": num(flags.get("time-scale"), 4.0, 0.1, 65536.0),
    }
    effect = _formula_effect_factory(config)
    defaults = {
        "fps": 60,
        "zoom": 1.8,
        "emit": "auto",
        "color_steps": 64,
        "char_mode": "formula",
        "char_mix": 1.0,
        "char_min": 0x2190,
        "char_max": 0x2BFF,
        "char_rate": 0.05,
        "char_steps": 96,
    }
    return run_terminal_animation(meta, effect, argv, defaults)
