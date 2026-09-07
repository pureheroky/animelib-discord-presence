#!/usr/bin/env python3
"""Prepares a release: version, update URL and the update manifest.

Firefox can update a self-hosted add-on without any store. Two links are needed,
both HTTPS:

  * `update_url` inside the add-on manifest — points at updates.json;
  * `update_link` inside updates.json — points at the signed .xpi.

Order matters. `update_url` is part of the signed package, so it has to be set
*before* signing; updates.json is a plain file and can be refreshed afterwards.

Usage:
    python release.py --repo owner/name [--version 1.2.3] [--branch main]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "extension" / "manifest.json"
UPDATES = ROOT / "updates.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bump(version: str) -> str:
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name on GitHub")
    ap.add_argument("--version", help="explicit version; otherwise the patch number is bumped")
    ap.add_argument("--branch", default="main", help="branch hosting updates.json")
    args = ap.parse_args()

    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        print("--repo must look like owner/name")
        return 1

    manifest = load(MANIFEST)
    addon_id = manifest["browser_specific_settings"]["gecko"]["id"]
    version = args.version or bump(manifest["version"])
    if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        print("version must be digits and dots, e.g. 1.2.3")
        return 1

    raw = "https://raw.githubusercontent.com/%s/%s/updates.json" % (args.repo, args.branch)
    xpi = "https://github.com/%s/releases/download/v%s/animelib-presence-%s.xpi" % (
        args.repo, version, version)

    manifest["version"] = version
    manifest["browser_specific_settings"]["gecko"]["update_url"] = raw
    save(MANIFEST, manifest)

    # Keep older entries: someone may still be sitting on an earlier version.
    updates = load(UPDATES) if UPDATES.exists() else {"addons": {}}
    entries = updates.setdefault("addons", {}).setdefault(addon_id, {}).setdefault("updates", [])
    entries = [e for e in entries if e.get("version") != version]
    entries.append({"version": version, "update_link": xpi})
    entries.sort(key=lambda e: [int(n) for n in e["version"].split(".")])
    updates["addons"][addon_id]["updates"] = entries
    save(UPDATES, updates)

    print("version:      %s" % version)
    print("update_url:   %s" % raw)
    print("update_link:  %s" % xpi)
    print("""
Next:
  1. cd extension && web-ext sign --channel=unlisted --api-key=... --api-secret=...
  2. rename the signed file to animelib-presence-%s.xpi
  3. create GitHub release v%s and attach that .xpi
  4. commit updates.json and manifest.json, push to %s

Note: a client only learns about updates if the version it already runs carries
update_url. The first release that adds it still has to be installed by hand.
""" % (version, version, args.branch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
