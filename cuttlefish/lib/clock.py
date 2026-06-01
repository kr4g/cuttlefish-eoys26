import time


class SharedClock:
    def __init__(self, epoch_unix=None, epoch_offset=0.0):
        now_mono = time.monotonic()
        self._start_mono = now_mono
        if epoch_unix is None:
            self._bias = float(epoch_offset)
            self._anchored = False
        else:
            wall_minus_mono = time.time() - now_mono
            self._bias = wall_minus_mono - float(epoch_unix) + float(epoch_offset)
            self._anchored = True

    def now(self):
        mono = time.monotonic()
        if self._anchored:
            return mono + self._bias
        return (mono - self._start_mono) + self._bias
