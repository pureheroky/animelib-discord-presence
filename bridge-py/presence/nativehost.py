"""Native messaging transport: [len:uint32le][utf-8 json] over stdin/stdout.

Two Windows-specific hazards handled here:
  * the streams must be binary — text mode would turn a \\n inside a frame into
    \\r\\n and shift every following length prefix;
  * the real stdout handle is grabbed once and handed to the writer, after which
    sys.stdout is redirected to the log by the caller.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import threading

_LEN = struct.Struct("<I")
MAX_MESSAGE = 64 * 1024 * 1024


def open_streams():
    """Returns (stdin_binary, stdout_binary) in binary mode on every platform.

    Taken from the raw file descriptors rather than sys.stdin/sys.stdout: a
    frozen windowed build has no console, and Python may leave those set to
    None or to a dummy writer. The descriptors Firefox hands us are real
    either way.
    """
    if os.name == "nt":
        import msvcrt

        for fd in (0, 1):
            try:
                msvcrt.setmode(fd, os.O_BINARY)
            except OSError:
                pass
    try:
        return os.fdopen(0, "rb", 0), os.fdopen(1, "wb", 0)
    except OSError:
        return sys.stdin.buffer, sys.stdout.buffer


def _read_exact(stream, size: int) -> bytes | None:
    """Pipes hand out short reads; keep pulling until the frame is whole."""
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(stream) -> dict | None:
    """Next message, or None once the browser closed the channel."""
    head = _read_exact(stream, 4)
    if head is None:
        return None
    (length,) = _LEN.unpack(head)
    if length > MAX_MESSAGE:
        raise ValueError("message too large: %d" % length)
    body = _read_exact(stream, length)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


class Writer:
    """Serialises writes: the reader thread and Discord callbacks both reply."""

    def __init__(self, stream):
        self._stream = stream
        self._lock = threading.Lock()
        self._closed = False

    def send(self, payload: dict) -> bool:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with self._lock:
            if self._closed:
                return False
            try:
                self._stream.write(_LEN.pack(len(body)) + body)
                self._stream.flush()
                return True
            except (OSError, ValueError):
                self._closed = True
                return False

    def close(self):
        with self._lock:
            self._closed = True
