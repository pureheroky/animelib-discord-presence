"""Installs the native messaging host manifest so Firefox can launch us.

Firefox finds the host by name: on Windows through a registry value under
HKCU\\Software\\Mozilla\\NativeMessagingHosts, elsewhere through a JSON file in
a well-known directory.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .config import EXTENSION_ID, HOST_NAME, data_dir, frozen, host_manifest_path


def _host_command() -> str:
    """Absolute path Firefox will execute."""
    if frozen():
        return str(Path(sys.executable).resolve())

    entry = Path(__file__).resolve().parents[1] / "run.py"
    if os.name == "nt":
        shim = data_dir() / "run-host.cmd"
        shim.write_text(
            "@echo off\r\n\"%s\" \"%s\" %%*\r\n" % (sys.executable, entry),
            encoding="utf-8",
        )
        return str(shim)
    shim = data_dir() / "run-host.sh"
    shim.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, entry),
                    encoding="utf-8")
    shim.chmod(0o755)
    return str(shim)


def _manifest() -> dict:
    return {
        "name": HOST_NAME,
        "description": "AnimeLib -> Discord Rich Presence bridge",
        "path": _host_command(),
        "type": "stdio",
        "allowed_extensions": [EXTENSION_ID],
    }


def _firefox_host_dirs() -> list[Path]:
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Mozilla" / "NativeMessagingHosts"]
    return [Path.home() / ".mozilla" / "native-messaging-hosts"]


def register() -> list[str]:
    """Installs the manifest. Returns human-readable lines about what happened."""
    manifest = _manifest()
    done = []

    if os.name == "nt":
        import winreg

        path = host_manifest_path()
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            r"Software\Mozilla\NativeMessagingHosts\%s" % HOST_NAME,
            0,
            winreg.KEY_WRITE,
        )
        with key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(path))
        done.append("manifest: %s" % path)
        done.append(r"registry: HKCU\Software\Mozilla\NativeMessagingHosts\%s" % HOST_NAME)
    else:
        for directory in _firefox_host_dirs():
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / ("%s.json" % HOST_NAME)
            path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            done.append("manifest: %s" % path)

    done.append("launches: %s" % manifest["path"])
    done.append("allowed extension: %s" % EXTENSION_ID)
    return done


def unregister() -> list[str]:
    done = []
    if os.name == "nt":
        import winreg

        try:
            winreg.DeleteKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Mozilla\NativeMessagingHosts\%s" % HOST_NAME,
            )
            done.append("registry key removed")
        except FileNotFoundError:
            done.append("registry key was not there")
        path = host_manifest_path()
        if path.exists():
            path.unlink()
            done.append("manifest removed: %s" % path)
    else:
        for directory in _firefox_host_dirs():
            path = directory / ("%s.json" % HOST_NAME)
            if path.exists():
                path.unlink()
                done.append("manifest removed: %s" % path)
    return done or ["nothing to remove"]
