"""Turns state from the extension into a Discord activity, with throttling.

Tab election lives in the extension now: the background page knows which tab is
focused, which is a far better signal than anything guessable from a content
script. What stays here is the part that must not be duplicated per tab —
one Discord connection and one rate limiter.
"""

from __future__ import annotations

import threading
import time

from .activity import build_activity, needs_update
from .config import merged_settings
from .ipc import DiscordIPC

IDLE_TIMEOUT_SEC = 90


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return None if n != n else n


def _text(value, limit=300):
    return value[:limit] if isinstance(value, str) else ""


def normalize(raw: dict) -> dict:
    return {
        "status": "paused" if raw.get("status") == "paused" else "playing",
        "title": _text(raw.get("title")),
        "titleAlt": _text(raw.get("titleAlt")),
        "episode": _num(raw.get("episode")),
        "season": _num(raw.get("season")),
        "episodeName": _text(raw.get("episodeName")),
        "totalEpisodes": _num(raw.get("totalEpisodes")),
        "position": _num(raw.get("position")),
        "duration": _num(raw.get("duration")),
        "team": _text(raw.get("team"), 120),
        "cover": _text(raw.get("cover"), 512),
        "url": _text(raw.get("url"), 512),
    }


class Bridge:
    def __init__(self, log, writer):
        self.log = log
        self.writer = writer
        self.cfg = merged_settings()

        self._lock = threading.RLock()
        self._sent = None
        self._latest = None
        self._last_sent_at = 0.0
        self._pending: threading.Timer | None = None
        self._idle: threading.Timer | None = None

        self.ipc = DiscordIPC(self.cfg["clientId"], log)
        self.ipc.on_ready = self._on_ready
        self.ipc.on_disconnect = self._on_disconnect
        self.ipc.on_rpc_error = lambda d: log.warn(
            "Discord rejected the request: %s %s" % (d.get("code"), d.get("message"))
        )
        self.ipc.on_handshake_error = self._on_handshake_error
        self._reported_bad_id = False

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self):
        self.log.info("Native host started, connecting to Discord…")
        self.ipc.start()

    def shutdown(self):
        self.log.info("Channel closed, clearing the status…")
        self._clear()
        self.ipc.stop()

    def _on_ready(self, user):
        name = (user or {}).get("username") or "unknown user"
        self.log.info("Discord connected (%s)" % name)
        self.writer.send({"type": "ready", "user": name})
        with self._lock:
            if self._latest:
                self._push()

    def _on_disconnect(self, reason):
        self.log.warn("Discord went away: %s" % reason)
        self.writer.send({"type": "status", "discord": False, "reason": reason})

    def _on_handshake_error(self, code, message):
        if code != 4000:
            self.log.warn("Discord refused the connection: %s %s" % (code, message))
            return
        if self._reported_bad_id:
            return
        self._reported_bad_id = True
        text = "Discord rejected Application ID %s: %s" % (self.cfg["clientId"], message)
        self.log.error(text)
        self.writer.send({"type": "error", "code": code, "message": text})

    # ── messages from the extension ──────────────────────────────────────
    def on_settings(self, incoming: dict):
        with self._lock:
            self.cfg = merged_settings(incoming)
            self.log.set_debug(bool(self.cfg.get("debug")))
            self.log.debug("settings updated: %s" % sorted(incoming))
            if self._latest:
                self._sent = None
                self._maybe_push()

    def on_presence(self, raw: dict):
        state = normalize(raw)
        if not state["title"] and not state["titleAlt"]:
            self.log.debug("Skipping: the extension sent no title")
            return
        with self._lock:
            self._latest = {"state": state, "at": time.time() * 1000}
            self._arm_idle()
            self._maybe_push()

    def on_clear(self):
        with self._lock:
            if self._sent:
                self.log.info("Nothing is playing — clearing the status")
            self._clear()

    def status(self) -> dict:
        with self._lock:
            return {
                "type": "status",
                "discord": self.ipc.connected,
                "watching": self._sent["state"]["title"] if self._sent else None,
            }

    def _cancel(self, attr):
        timer = getattr(self, attr)
        if timer is not None:
            timer.cancel()
            setattr(self, attr, None)

    def _arm_idle(self):
        self._cancel("_idle")
        self._idle = threading.Timer(IDLE_TIMEOUT_SEC, self._on_idle)
        self._idle.daemon = True
        self._idle.start()

    def _on_idle(self):
        with self._lock:
            if self._sent:
                self.log.warn("No word from the extension for a while — clearing")
            self._clear()

    def _clear(self):
        with self._lock:
            self._cancel("_pending")
            self._cancel("_idle")
            self._latest = None
            if not self._sent:
                return
            self._sent = None
        if self.ipc.connected:
            self.ipc.clear_activity()

    def _maybe_push(self):
        """Throttles writes to Discord. Called under self._lock."""
        if not self.ipc.connected or not self._latest:
            return
        if not needs_update(self._sent, self._latest, self.cfg["seekToleranceSec"]):
            return
        gap = self.cfg["minUpdateIntervalMs"] / 1000.0
        since = time.time() - self._last_sent_at
        if since >= gap:
            self._push()
        elif self._pending is None:
            self._pending = threading.Timer(gap - since, self._push_later)
            self._pending.daemon = True
            self._pending.start()

    def _push_later(self):
        with self._lock:
            self._pending = None
            self._push()

    def _push(self):
        """Called under self._lock."""
        if not self._latest or not self.ipc.connected:
            return
        activity = build_activity(self._latest["state"], self.cfg)
        if not activity or not self.ipc.set_activity(activity):
            return
        self._sent = self._latest
        self._last_sent_at = time.time()
        self.log.info("> %s — %s" % (activity["details"], activity["state"]))
