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
python -m cuttlefish forest-fire --wind e --speed 0.5 --density 0.7
```

## Animations

Currently just `forest-fire`. More are on the way.

### `forest-fire`

| flag          | range          | default   |
| ------------- | -------------- | --------- |
| `--growth`    | `0..0.05`      | `0.002`   |
| `--lightning` | `0..0.001`     | `0.00001` |
| `--spread`    | `0.05..1`      | `0.7`     |
| `--wind`      | `none/n/e/s/w` | `none`    |
| `--speed`     | `0..10`        | `1.0`     |
| `--fps`       | `10..60`       | `60`      |
| `--density`   | `0..1`         | `0.55`    |

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
