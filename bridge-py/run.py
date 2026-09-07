#!/usr/bin/env python3
"""AnimeLib -> Discord Rich Presence native messaging host.

Firefox launches this on its own when the extension opens a port; there is
nothing to start by hand. Run it with --register once to make Firefox aware
of it.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from presence import config, nativehost, register as reg
from presence.bridge import Bridge
from presence.logs import Log

VERSION = "2.0.0"


def _cli(argv: list[str]) -> int:
    command = argv[0]
    if command in ("--register", "-r"):
        print("Registering the native messaging host for Firefox…")
        for line in reg.register():
            print("  " + line)
        print("\nDone. Install the extension, then open an episode on AnimeLib.")
        print("Log: %s" % config.log_path())
        return 0
    if command in ("--unregister", "-u"):
        for line in reg.unregister():
            print("  " + line)
        return 0
    if command in ("--version", "-v"):
        print(VERSION)
        return 0
    if command in ("--log", "-l"):
        print(config.log_path())
        return 0
    print(__doc__)
    print("  --register    tell Firefox about this host")
    print("  --unregister  undo that")
    print("  --log         print the log file path")
    print("  --version     print the version")
    return 0 if command in ("--help", "-h") else 1


def _serve() -> int:
    """Native messaging mode: stdin/stdout belong to Firefox."""
    stdin, stdout = nativehost.open_streams()
    log = Log(config.log_path())
    log.capture_stdout()

    writer = nativehost.Writer(stdout)
    bridge = Bridge(log, writer)
    bridge.start()

    try:
        while True:
            try:
                message = nativehost.read_message(stdin)
            except (ValueError, UnicodeDecodeError) as err:
                log.error("Broken frame from the extension: %s" % err)
                break
            if message is None:
                log.info("Firefox closed the channel")
                break

            kind = message.get("type")
            if kind == "presence":
                bridge.on_presence(message.get("state") or {})
            elif kind == "clear":
                bridge.on_clear()
            elif kind == "settings":
                bridge.on_settings(message.get("settings") or {})
            elif kind == "hello":
                log.info("Extension connected, version %s" % message.get("version"))
                writer.send({"type": "hello", "version": VERSION})
                writer.send(bridge.status())
            elif kind == "status":
                writer.send(bridge.status())
            else:
                log.debug("Unknown message type: %r" % kind)
    except Exception:
        log.error("Host crashed:\n%s" % traceback.format_exc())
        return 1
    finally:
        bridge.shutdown()
        writer.close()
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0].startswith("-"):
        return _cli(argv)
    return _serve()


if __name__ == "__main__":
    sys.exit(main())
