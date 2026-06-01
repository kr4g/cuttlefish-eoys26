import numpy as np


def _hash01(x, y, z, seed):
    n = np.sin(x * 127.1 + y * 311.7 + z * 74.7 + seed * 19.19) * 43758.5453
    return n - np.floor(n)


def value_noise3(x, y, z, seed):
    xi = np.floor(x)
    yi = np.floor(y)
    zi = np.floor(z)
    xf = x - xi
    yf = y - yi
    zf = z - zi

    u = xf * xf * (3.0 - 2.0 * xf)
    v = yf * yf * (3.0 - 2.0 * yf)
    w = zf * zf * (3.0 - 2.0 * zf)

    n000 = _hash01(xi, yi, zi, seed)
    n100 = _hash01(xi + 1.0, yi, zi, seed)
    n010 = _hash01(xi, yi + 1.0, zi, seed)
    n110 = _hash01(xi + 1.0, yi + 1.0, zi, seed)
    n001 = _hash01(xi, yi, zi + 1.0, seed)
    n101 = _hash01(xi + 1.0, yi, zi + 1.0, seed)
    n011 = _hash01(xi, yi + 1.0, zi + 1.0, seed)
    n111 = _hash01(xi + 1.0, yi + 1.0, zi + 1.0, seed)

    x00 = n000 + (n100 - n000) * u
    x10 = n010 + (n110 - n010) * u
    x01 = n001 + (n101 - n001) * u
    x11 = n011 + (n111 - n011) * u
    y0 = x00 + (x10 - x00) * v
    y1 = x01 + (x11 - x01) * v
    return y0 + (y1 - y0) * w


def fbm3(x, y, z, octaves, seed):
    octaves = max(1, int(octaves))
    amp = 0.5
    freq = 1.0
    total = np.zeros_like(x, dtype=np.float32)
    weight = 0.0
    for i in range(octaves):
        n = value_noise3(x * freq, y * freq, z * freq, seed + i * 23)
        total += (n * amp).astype(np.float32)
        weight += amp
        freq *= 2.0
        amp *= 0.5
    return total / np.float32(weight)
