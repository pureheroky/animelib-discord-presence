"""Turns the state posted by the extension into a Discord activity object."""

from __future__ import annotations

import re
import time

LIMIT_DETAILS = LIMIT_STATE = LIMIT_TEXT = 128
LIMIT_BUTTON = 32

_WS = re.compile(r"\s+")


def clamp(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    s = _WS.sub(" ", value).strip()
    if not s:
        return None
    if len(s) < 2:
        return s + " "
    return s[:limit - 1] + "…" if len(s) > limit else s


def is_https(url) -> bool:
    return isinstance(url, str) and url.lower().startswith("https://") and len(url) <= 512


def _num(value):
    """A number or None; strings, None and NaN are all rejected alike."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")) or n < 0:
        return None
    return n


def _fmt_num(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def episode_line(state: dict, with_team: bool = True) -> str:
    """Human-readable episode line. Stays Russian: it is shown in Discord."""
    parts = []
    season = _num(state.get("season"))
    if season is not None and season > 1:
        parts.append("Сезон %s" % _fmt_num(season))

    episode = _num(state.get("episode"))
    if episode is not None:
        total = _num(state.get("totalEpisodes"))
        suffix = " из %s" % _fmt_num(total) if total else ""
        parts.append("%s серия%s" % (_fmt_num(episode), suffix))
    elif state.get("episodeName"):
        parts.append(state["episodeName"])

    if with_team and state.get("team"):
        parts.append(state["team"])
    return " · ".join(parts)


def build_activity(state: dict, cfg: dict) -> dict | None:
    """A ready SET_ACTIVITY payload, or None when there is nothing to show."""
    title = clamp(state.get("title") or state.get("titleAlt"), LIMIT_DETAILS)
    if not title:
        return None

    paused = state.get("status") == "paused"
    activity = {"type": cfg.get("activityType", 3)}   # 3 = Watching

    if cfg.get("titleInHeader", True):
        # Discord keeps a custom activity "name" sent over IPC and prints it as
        # the header, in place of the application name. That frees the details
        # line, so the three lines carry three different things.
        activity["name"] = title
        head = episode_line(state, with_team=False)
        tail = " · ".join(p for p in (state.get("team"), "На паузе" if paused else "") if p)
        if head:
            activity["details"] = clamp(head, LIMIT_DETAILS)
        if tail:
            activity["state"] = clamp(tail, LIMIT_STATE)
        if not head and not tail:
            activity["details"] = "Смотрит на AnimeLib"
    else:
        line = episode_line(state)
        suffix = (" · На паузе" if line else "На паузе") if paused else ""
        activity["details"] = title
        activity["state"] = clamp(line + suffix, LIMIT_STATE) or "Смотрит на AnimeLib"

    position = _num(state.get("position"))
    duration = _num(state.get("duration"))
    mode = cfg.get("timestampMode", "remaining")
    if not paused and mode != "off" and position is not None:
        now = time.time() * 1000
        stamps = {"start": round(now - position * 1000)}
        if mode == "remaining" and duration and duration > position:
            stamps["end"] = round(now + (duration - position) * 1000)
        activity["timestamps"] = stamps

    assets = {}
    cover = state.get("cover") if is_https(state.get("cover")) else cfg.get("fallbackImage")
    if cover:
        assets["large_image"] = cover
        large_text = clamp(state.get("titleAlt") or state.get("title"), LIMIT_TEXT)
        if large_text:
            assets["large_text"] = large_text
    small = cfg.get("pausedImage") if paused else cfg.get("playingImage")
    if small:
        assets["small_image"] = small
        assets["small_text"] = "Пауза" if paused else "Смотрит"
    if assets:
        activity["assets"] = assets

    if cfg.get("showButton") and is_https(state.get("url")):
        label = clamp(cfg.get("buttonLabel") or "Смотреть на AnimeLib", LIMIT_BUTTON)
        activity["buttons"] = [{"label": label, "url": state["url"]}]

    return activity


def needs_update(prev, nxt, seek_tolerance: float = 5.0) -> bool:
    """Discord runs the timer itself, so only rewrite the status when it matters."""
    if prev is None:
        return True
    keys = ("title", "episode", "season", "status", "totalEpisodes", "team", "cover", "url")
    if any(prev["state"].get(k) != nxt["state"].get(k) for k in keys):
        return True
    if nxt["state"].get("status") != "playing":
        return False
    elapsed = (nxt["at"] - prev["at"]) / 1000.0
    expected = (_num(prev["state"].get("position")) or 0.0) + elapsed
    actual = _num(nxt["state"].get("position")) or 0.0
    return abs(actual - expected) > seek_tolerance
