"""Tiny long-flag parser:  --key value   or   --key=value   or   --flag"""

import math


def parse_flags(argv):
    out = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if not a.startswith("--"):
            i += 1
            continue
        if "=" in a:
            key, val = a[2:].split("=", 1)
        else:
            key = a[2:]
            peek = argv[i + 1] if i + 1 < len(argv) else None
            if peek is not None and not peek.startswith("--"):
                val = peek
                i += 1
            else:
                val = True
        out[key] = val
        i += 1
    return out


def num(val, fallback, lo=-math.inf, hi=math.inf):
    if val is None or val is True:
        return fallback
    try:
        n = float(val)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(n):
        return fallback
    return max(lo, min(hi, n))


def num_int(val, fallback, lo=None, hi=None):
    n = num(
        val,
        fallback,
        -math.inf if lo is None else lo,
        math.inf if hi is None else hi,
    )
    return int(n)
