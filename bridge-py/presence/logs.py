"""File logging.

stdout is the native messaging channel: a single stray print corrupts a frame
mid-flight and the browser silently drops the connection. So nothing ever goes
to stdout, and sys.stdout itself is redirected here as a safety net.
"""

from __future__ import annotations

import sys
import threading
import time

MAX_BYTES = 1_000_000


class Log:
    def __init__(self, path, debug: bool = False):
        self.path = path
        self._debug = debug
        self._lock = threading.Lock()
        self._rotate()

    def _rotate(self):
        try:
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                self.path.replace(self.path.with_suffix(".log.old"))
        except OSError:
            pass

    def set_debug(self, value: bool):
        self._debug = bool(value)

    def _write(self, prefix: str, msg):
        line = "[%s] %s%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), prefix, msg)
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass

    def info(self, msg):
        self._write("", msg)

    def warn(self, msg):
        self._write("! ", msg)

    def error(self, msg):
        self._write("x ", msg)

    def debug(self, msg):
        if self._debug:
            self._write("  · ", msg)

    def capture_stdout(self):
        """Point sys.stdout/stderr at the log so stray prints cannot corrupt stdio."""
        sys.stdout = _LogStream(self, "stdout: ")
        sys.stderr = _LogStream(self, "stderr: ")


class _LogStream:
    def __init__(self, log: Log, prefix: str):
        self._log = log
        self._prefix = prefix

    def write(self, text):
        text = text.rstrip("\r\n")
        if text:
            self._log.warn(self._prefix + text)
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False
