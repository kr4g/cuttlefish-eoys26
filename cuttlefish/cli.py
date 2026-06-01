import sys

from .animations import animations

ALIASES = {}


def _print_list(out=sys.stdout):
    out.write("cuttlefish - terminal animations\n\n")
    out.write("Usage:\n")
    out.write("  python -m cuttlefish <name> [options]   run an animation\n")
    out.write("  python -m cuttlefish --list             list available animations\n\n")
    out.write("Available:\n")
    if not animations:
        out.write("  (none yet)\n")
    else:
        pad = max(len(n) for n in animations)
        for name, anim in animations.items():
            m = anim.meta
            out.write(f"  {name.ljust(pad)}  {m['description']}\n")
            if m.get("usage"):
                out.write(f"  {' ' * pad}  {m['usage']}\n")


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "-l", "--list"):
        _print_list()
        return 0

    name = ALIASES.get(argv[0], argv[0])
    anim = animations.get(name)
    if anim is None:
        sys.stderr.write(f"unknown animation: {name}\n\n")
        _print_list(sys.stderr)
        return 1

    result = anim.run(argv[1:])
    return 0 if result is None else int(result)


def main_entry():
    """Console-script entry point used by `pyproject.toml`."""
    sys.exit(main(sys.argv[1:]))
