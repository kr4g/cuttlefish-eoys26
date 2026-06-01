# cuttlefish EoYS '26

Terminal animation rendered with truecolor ANSI characters.

Requires Python 3.9+, `numpy`, and a TTY with 24-bit color.

## Run

```bash
pip install -e .                      # or: pip install numpy

python -m cuttlefish --list
python -m cuttlefish bitwise
python -m cuttlefish bitwise --help
```

## App

### `bitwise`

Important flags:

- `--formula-seconds N` random formula interval
- `--vars-seconds N` random vars interval
- `--color-cycle-rate N` color mode cycle/interpolation rate
- `--seed N` deterministic formula/var schedule seed
- `--time-scale N` scalar for bitwise time integer
- `--char-mode ramp|formula`
- `--char-mix 0..1`
- `--char-min N`, `--char-max N`
- `--char-rate 0..4`, `--char-steps 8..2048`
- `--fps 10..60`
- `--emit auto|full|diff`

Shared helpers in `cuttlefish/lib/`:

- `terminal.py` — ANSI sequences, alt-screen, exit handlers
- `args.py` — `parse_flags`, `num`, `num_int`
- `viewport.py` — hostname/grid tile mapping and global coordinate fields
- `clock.py` — monotonic local clock with optional shared epoch anchoring
- `spectral.py` — intensity to spectral color and glyph mapping
- `shader_runner.py` — shared fullscreen loop for `(x, y, t)` effects

## 4x4 Multi-Shell Simulation

```bash
./scripts/simulate_grid_kitty.sh bitwise
./scripts/simulate_grid_iterm2.sh bitwise
```

Useful environment variables for launchers:

- `FPS=60`
- `EPOCH_OFFSET=0`
- `EPOCH_UNIX=<shared unix seconds>` (if unset, launcher captures one shared epoch per run)
- `GRID_COLS=4`, `GRID_ROWS=4`
- `TILE_COLS=120`, `TILE_ROWS=36`

Grid conventions:

- `row=0,col=0` is bottom-left
- `row` increases upward
- `col` increases to the right
