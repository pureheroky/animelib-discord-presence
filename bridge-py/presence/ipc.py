"""Minimal Discord IPC (Rich Presence) client built on the standard library alone.

Wire format: [op:int32le][len:int32le][json]. The channel is a named pipe on
Windows and a unix socket under $XDG_RUNTIME_DIR on Linux.

Important: all channel traffic happens on a single thread. On Windows the pipe
is opened as a synchronous handle, where a blocking ReadFile serialises every
operation on it — a write from another thread would hang until the read
finished. Hence the outbound queue instead of a direct write.
"""

from __future__ import annotations

import json
import os
import queue
import struct
import threading
import time
import uuid

OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 3, 4

_HEADER = struct.Struct("<ii")
_POLL_SEC = 0.05
_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:
    import _winapi
    import msvcrt
else:
    import select
    import socket


def _candidate_paths() -> list[str]:
    if _IS_WINDOWS:
        return [r"\\.\pipe\discord-ipc-%d" % i for i in range(10)]
    base = (
        os.environ.get("XDG_RUNTIME_DIR")
        or os.environ.get("TMPDIR")
        or os.environ.get("TMP")
        or os.environ.get("TEMP")
        or "/tmp"
    )
    subdirs = [
        "",
        "app/com.discordapp.Discord",
        "app/com.discordapp.DiscordCanary",
        "snap.discord",
        "snap.discord-canary",
    ]
    return [os.path.join(base, d, "discord-ipc-%d" % i) for d in subdirs for i in range(10)]


class _Channel:
    """One interface over a named pipe (nt) and a unix socket (posix)."""

    def __init__(self, path: str):
        self.path = path
        if _IS_WINDOWS:
            self._f = open(path, "r+b", buffering=0)
            self._handle = msvcrt.get_osfhandle(self._f.fileno())
        else:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(path)

    def send(self, data: bytes) -> None:
        if _IS_WINDOWS:
            self._f.write(data)
        else:
            self._sock.sendall(data)

    def poll_read(self, timeout: float) -> bytes | None:
        """Data, b'' once the channel closed, or None if nothing arrived in time."""
        if _IS_WINDOWS:
            available = _winapi.PeekNamedPipe(self._handle)[0]
            if not available:
                time.sleep(timeout)
                return None
            return self._f.read(min(available, 65536))
        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            return None
        return self._sock.recv(65536)

    def close(self) -> None:
        try:
            (self._f if _IS_WINDOWS else self._sock).close()
        except OSError:
            pass


class DiscordIPC:
    """Keeps the Discord connection alive and reconnects on its own."""

    def __init__(self, client_id: str, log):
        self.client_id = str(client_id)
        self.log = log
        self.on_ready = lambda user: None
        self.on_disconnect = lambda reason: None
        self.on_rpc_error = lambda data: None
        self.on_handshake_error = lambda code, message: None

        self._chan: _Channel | None = None
        self._out: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._became_ready = False
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._ready.is_set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._supervise, daemon=True)
        self._thread.start()

    def set_activity(self, activity: dict) -> bool:
        return self._enqueue({"cmd": "SET_ACTIVITY",
                              "args": {"pid": os.getpid(), "activity": activity}})

    def clear_activity(self) -> bool:
        return self._enqueue({"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid()}})

    def stop(self) -> None:
        if self.connected:
            self.clear_activity()
            deadline = time.time() + 1.0
            while time.time() < deadline and not self._out.empty():
                time.sleep(0.02)
        self._stopping.set()
        self._drop("shutting down")

    def _enqueue(self, payload: dict) -> bool:
        if not self.connected:
            return False
        payload["nonce"] = str(uuid.uuid4())
        self._out.put((OP_FRAME, payload))
        return True

    def _send_now(self, op: int, payload: dict) -> bool:
        chan = self._chan
        if chan is None:
            return False
        body = json.dumps(payload).encode("utf-8")
        try:
            chan.send(_HEADER.pack(op, len(body)) + body)
            return True
        except OSError as err:
            self._drop(str(err))
            return False

    def _connect(self) -> bool:
        for path in _candidate_paths():
            try:
                self._chan = _Channel(path)
            except OSError:
                continue
            self.log.debug("IPC: connecting over %s" % path)
            return self._send_now(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
        return False

    def _drop(self, reason: str) -> None:
        chan, self._chan = self._chan, None
        was_ready = self._ready.is_set()
        self._ready.clear()
        if chan is not None:
            chan.close()
        while True:
            try:
                self._out.get_nowait()
            except queue.Empty:
                break
        if was_ready and not self._stopping.is_set():
            self.on_disconnect(reason)

    def _supervise(self) -> None:
        attempt = 0
        while not self._stopping.is_set():
            self._became_ready = False
            if self._connect():
                self._io_loop()
                if self._became_ready:
                    attempt = 0
            else:
                self._chan = None
            if self._stopping.is_set():
                return
            delay = min(2 * 2 ** min(attempt, 4), 30)
            attempt += 1
            self.log.debug("Reconnecting in %ds" % delay)
            self._stopping.wait(delay)

    def _io_loop(self) -> None:
        buf = b""
        while not self._stopping.is_set():
            chan = self._chan
            if chan is None:
                return

            while True:
                try:
                    op, payload = self._out.get_nowait()
                except queue.Empty:
                    break
                if not self._send_now(op, payload):
                    return

            try:
                chunk = chan.poll_read(_POLL_SEC)
            except OSError as err:
                self._drop(str(err))
                return
            if chunk is None:
                continue
            if not chunk:
                self._drop("connection closed")
                return

            buf += chunk
            while len(buf) >= 8:
                op, length = _HEADER.unpack(buf[:8])
                if len(buf) < 8 + length:
                    break
                raw, buf = buf[8:8 + length], buf[8 + length:]
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if not self._handle(op, msg):
                    return

    def _handle(self, op: int, msg: dict) -> bool:
        """Returns False when the connection must be torn down."""
        if op == OP_PING:
            self._send_now(OP_PONG, msg)
            return True
        if op == OP_CLOSE:
            code, message = msg.get("code"), msg.get("message", "")
            if code is not None and not self._ready.is_set():
                self.on_handshake_error(code, message)
            self._drop("Discord closed the channel: %s %s" % (code or "?", message))
            return False
        if op != OP_FRAME:
            return True
        if msg.get("cmd") == "DISPATCH" and msg.get("evt") == "READY":
            self._ready.set()
            self._became_ready = True
            self.on_ready((msg.get("data") or {}).get("user"))
        elif msg.get("evt") == "ERROR":
            self.on_rpc_error(msg.get("data") or {})
        return True
