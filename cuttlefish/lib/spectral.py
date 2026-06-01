import numpy as np


_GLYPHS = np.array([ord(ch) for ch in " .,'`^\":;!~+-=x0*#%@░▒▓█▙▛▜▟"], dtype=np.uint32)
_TWO_PI = np.float32(2.0 * np.pi)


def intensity_to_codepoints(intensity):
    v = np.clip(intensity, 0.0, 1.0).astype(np.float32)
    idx = np.clip((v * (_GLYPHS.size - 1)).astype(np.int32), 0, _GLYPHS.size - 1)
    return _GLYPHS[idx]


def intensity_to_rgb24(intensity):
    v = np.clip(intensity, 0.0, 1.0).astype(np.float32)
    r = ((np.sin(_TWO_PI * (v + np.float32(0.0))) * 0.5 + 0.5) * 255.0).astype(np.uint32)
    g = ((np.sin(_TWO_PI * (v + np.float32(1.0 / 3.0))) * 0.5 + 0.5) * 255.0).astype(np.uint32)
    b = ((np.sin(_TWO_PI * (v + np.float32(2.0 / 3.0))) * 0.5 + 0.5) * 255.0).astype(np.uint32)
    return (r << 16) | (g << 8) | b


def build_luts(steps):
    steps = int(max(8, steps))
    ramp = np.linspace(0.0, 1.0, steps, dtype=np.float32)
    return intensity_to_codepoints(ramp), intensity_to_rgb24(ramp)
