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
python -m cuttlefish forest-fire --wind 1.5 --turbulence 0.7 --bias e --speed 0.5 --density 0.7
```

## Animations

### `forest-fire`

A regrowing forest plagued by lightning, fire, a swirling wind field, and
flying embers.

Wind is a divergence-free 2D flow field (curl of two sinusoidal harmonics in
`(x, y, t)`) rather than a single direction. The field biases per-cell fire
spread toward whichever way it's locally flowing, advects smoke trails,
faintly tints live forest cells along the flow lines so the field is visible
even without a fire, and carries hot embers ejected from burning cells —
which then have a probability of igniting any tree they land on.

#### Core knobs

| flag           | range                                | default     |
| -------------- | ------------------------------------ | ----------- |
| `--growth`     | `0..0.05`                            | `0.002`     |
| `--lightning`  | `0..0.001`                           | `0.00001`   |
| `--spread`     | `0.05..1`                            | `0.6`       |
| `--speed`      | `0..10`                              | `1.0`       |
| `--fps`        | `10..60`                             | `60`        |
| `--density`    | `0..1`                               | `0.43`      |

#### Wind / flow field

| flag           | range                                | default   |
| -------------- | ------------------------------------ | --------- |
| `--wind`       | `0..3` (overall flow strength)       | `1.0`     |
| `--turbulence` | `0..1` (rate of field churn)         | `0.3`     |
| `--bias`       | `none/n/ne/e/se/s/sw/w/nw`           | `none`    |
| `--scale`      | `0.5..4` (size of dominant swirls)   | `3.0`     |

`--wind 0` is calm: no flow field, no smoke, no embers, no tint, and the
spread step skips the per-cell alignment work — same cost as before.

#### Embers (active when `--wind > 0` and `--embers > 0`)

All four are *multipliers* on the in-code base constants (`EMBER_SPAWN_P`,
`EMBER_IGNITE_P`, `EMBER_LIFE_DECAY`, `EMBER_BUOYANCY`); raise to amplify,
lower (or `0`) to dampen. The defaults below are the tuned-for-feel values,
not necessarily `1.0`.

| flag                | range          | default | meaning                                              |
| ------------------- | -------------- | ------- | ---------------------------------------------------- |
| `--embers`          | `0..3`         | `1.0`   | spark spawn rate (`0` = no embers ever)              |
| `--ember-ignite`    | `0..3`         | `0.33`  | per-spark ignition probability when on a tree        |
| `--ember-life`      | `0.25..4`      | `2.5`   | lifetime multiplier (higher = more reach, more in flight) |
| `--ember-buoyancy`  | `0..2`         | `0.0`   | upward drift (`0` = ride only the wind)              |

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

Shared helpers live in `cuttlefish/lib/`:

- `terminal.py` — ANSI sequences, alt-screen, raw output, exit handlers
- `args.py` — `parse_flags`, `num`, `num_int`
