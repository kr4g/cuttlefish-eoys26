import atexit
import os
import signal
import sys

ESC = "\x1b["

RESET = ESC + "0m"
HIDE_CURSOR = ESC + "?25l"
SHOW_CURSOR = ESC + "?25h"
CLEAR_SCREEN = ESC + "2J"
CLEAR_LINE = ESC + "2K"
HOME = ESC + "H"
ENTER_ALT_SCREEN = ESC + "?1049h"
EXIT_ALT_SCREEN = ESC + "?1049l"

# Synchronized output (DEC private mode 2026). Supported by kitty, iTerm2,
# alacritty, foot, wezterm, contour, ghostty. Ignored on terminals that don't
# know it. Bracket each frame with BSU/ESU to eliminate tearing.
BSU = ESC + "?2026h"
ESU = ESC + "?2026l"


def fg(r, g, b):
    return f"{ESC}38;2;{r};{g};{b}m"


def bg(r, g, b):
    return f"{ESC}48;2;{r};{g};{b}m"


def move_to(row, col):
    return f"{ESC}{row};{col}H"


def get_size():
    try:
        sz = os.get_terminal_size(sys.stdout.fileno())
        return sz.columns, sz.lines
    except OSError:
        return 80, 24


def require_tty():
    if not sys.stdout.isatty():
        sys.stderr.write(
            "cuttlefish animations need to render to a TTY. "
            "Run them directly in a terminal (no pipes / redirects).\n"
        )
        sys.exit(1)


def enter_fullscreen():
    sys.stdout.write(ENTER_ALT_SCREEN + HIDE_CURSOR + CLEAR_SCREEN + HOME)
    sys.stdout.flush()


def exit_fullscreen():
    sys.stdout.write(RESET + SHOW_CURSOR + EXIT_ALT_SCREEN)
    sys.stdout.flush()


def install_exit_handlers(cleanup):
    """Run `cleanup()` exactly once on SIGINT/SIGTERM/SIGHUP, uncaught
    exceptions, or normal interpreter shutdown. Returns a callable that can
    be invoked to trigger the same cleanup explicitly."""
    cleaned = [False]

    def do_cleanup():
        if cleaned[0]:
            return
        cleaned[0] = True
        try:
            cleanup()
        except Exception:
            pass

    def sig_handler(_signum, _frame):
        do_cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, sig_handler)

    prev_excepthook = sys.excepthook

    def excepthook(exc_type, exc_value, exc_tb):
        do_cleanup()
        prev_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = excepthook
    atexit.register(do_cleanup)
    return do_cleanup
