# cuttlefish EoYS '26

Terminal animations rendered with truecolor ANSI characters. Each animation
is a self-contained module under `cuttlefish/animations/` and runs until
`Ctrl-C`.

Requires Python 3.9+, `numpy`, and a TTY with 24-bit color.

## Run

```bash
pip install -e .                      # or: pip install numpy

python -m cuttlefish --list
python -m cuttlefish forest-fire
python -m cuttlefish forest-fire --wind 2.5 --bias e --embers 2 --ember-life 1.5
```

## Animations

One animation so far. More on the way.

### `forest-fire`

A regrowing forest plagued by lightning, fire, a swirling wind field, and
flying embers.

| flag               | range                      | default   |
| ------------------ | -------------------------- | --------- |
| `--growth`         | `0..0.05`                  | `0.002`   |
| `--lightning`      | `0..0.001`                 | `0.00001` |
| `--spread`         | `0.05..1`                  | `0.63`    |
| `--density`        | `0..1`                     | `0.33`    |
| `--speed`          | `0..10`                    | `1.0`     |
| `--fps`            | `10..60`                   | `60`      |
| `--wind`           | `0..3`                     | `2.0`     |
| `--turbulence`     | `0..1`                     | `0.4`     |
| `--scale`          | `0.5..4`                   | `3.0`     |
| `--bias`           | `none/n/ne/e/se/s/sw/w/nw` | `none`    |
| `--embers`         | `0..3`                     | `1.25`    |
| `--ember-ignite`   | `0..3`                     | `0.43`    |
| `--ember-life`     | `0.25..4`                  | `2.0`     |
| `--ember-buoyancy` | `0..2`                     | `0.0`     |

`--wind 0` disables wind, smoke, embers, and the canopy tint. The four
`--ember-*` flags are multipliers on in-code base constants, so `1.0`
matches the tuned defaults; `0` disables that ember behavior.

## Adding an animation

Create `cuttlefish/animations/<name>.py` exporting a `meta` dict and a
`run(argv)` callable, then register it in
`cuttlefish/animations/__init__.py`.

```python
meta = {
    "name": "my-anim",
    "description": "one-line description",
    "usage": "[--option N]",
}

def run(argv=None):
    ...
```

Shared helpers in `cuttlefish/lib/`:

- `terminal.py` — ANSI sequences, alt-screen, exit handlers
- `args.py` — `parse_flags`, `num`, `num_int`
