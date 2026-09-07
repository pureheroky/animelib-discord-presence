# AnimeLib → Discord Rich Presence

Shows the anime you are watching on AnimeLib in your Discord status: title,
season and episode, the dub, cover art and a live episode timer.

Firefox only, by design — it is the browser the extension is signed for.

```
Firefox
 └─ extension
     ├─ content script on animelib.*  → works out what is playing
     ├─ frame script in the player    → reports the timecode
     └─ background                    → picks the focused tab, applies settings
             │  native messaging (stdio)
             ▼
     bridge (Python, standard library only)
             │  named pipe \\.\pipe\discord-ipc-0
             ▼
          Discord
```

Firefox starts and stops the bridge itself. There is no port, no token, no
config file, no console window and nothing to launch by hand.

## Install

Two pieces. Firefox cannot reach Discord's local pipe on its own, so the bridge
is a small program the browser launches on demand — the add-on alone will leave
the status blank.

**Requirements:** Firefox 142+, and the Discord **desktop app** running (the web
client exposes no pipe). Nothing else — the bridge ships as a single executable
with Python bundled inside.

1. Download `AnimeLibPresence.exe` and `animelib-presence-<version>.xpi` from
   [Releases](../../releases).
2. Put the executable somewhere permanent — registration records where it is,
   and moving it later breaks the link. Run it once from a terminal:

   ```
   AnimeLibPresence.exe --register
   ```

   It writes the native messaging manifest and a registry value under
   `HKCU\Software\Mozilla\NativeMessagingHosts`. `--unregister` undoes it,
   `--log` prints where the log goes.
3. Open the `.xpi` in Firefox, or drag it onto the window. Firefox asks to allow
   *exchanging messages with programs other than Firefox* — that is the bridge.

Then open an episode. Nothing needs starting by hand: Firefox launches the
bridge when a watch page appears and stops it when the browser closes.

If the status stays blank, open the add-on's preferences. It says in plain words
whether the bridge is missing, whether Discord is connected, and what is on
screen right now.

On Linux and macOS there is no prebuilt binary; run `python bridge-py/run.py
--register` from a checkout instead. Everything else is the same.

## Settings

Everything lives on the extension's options page (`about:addons` → the
extension → Preferences). It shows whether Discord is connected, how many anime
tabs are open, and a **preview of the status exactly as other people see it**.

| | |
| --- | --- |
| Master switch | turn the status off without uninstalling |
| Activity type | Watching / Playing / Listening |
| Timer | time remaining, time elapsed, or none |
| What to show | dub, cover, button, button label |
| Privacy | hide the title — the status says only that you are watching anime |
| Diagnostics | verbose log |

Settings live in the browser and are pushed to the bridge whenever they change.

## How it works

**The content script** does not scrape markup. A companion script running in the
page's own world (`world: "MAIN"`) taps the site's `fetch`/`XHR` and keeps the
`api/anime/...` and `api/episodes/...` responses, which carry the exact title,
episode number, season, cover and dub list the player itself uses. Parsing
`document.title` is a fallback for when the site changes its API.

The timecode comes from a `<video>` element. Some titles play inside a
cross-origin frame (Kodik) that the page cannot read; a separate script inside
that frame reports the position straight to the background, which accepts it
only when the surrounding tab really is AnimeLib.

**The background** decides which tab becomes the status. It knows which tab is
focused and in which window, so the rule is simply: a playing tab outranks a
paused one, a focused tab outranks a background one, and ties go to whichever
was focused last.

**The bridge** owns the one thing that must not be duplicated: a single Discord
connection and a single rate limiter. It writes only on meaningful changes —
episode switch, pause, a seek longer than 5 seconds — with a floor of 4 seconds
between writes. Discord runs the countdown itself, so per-second updates are
pointless.

Two details that are easy to get wrong and are deliberate here:

*All pipe traffic happens on one thread*, with a queue facing the rest of the
program. On Windows the Discord pipe is a synchronous handle, and a blocking
`ReadFile` on a reader thread serialises writes from any other thread — writing
directly made the bridge hang until it timed out.

*Nothing is ever printed to stdout.* Under native messaging stdout carries
length-prefixed frames; one stray `print` corrupts a frame and the browser drops
the connection without a word. The log goes to a file, and `sys.stdout` is
redirected there as a safety net.

## Layout

```
release.py                prepares a version + updates.json
updates.json              generated; what Firefox polls for updates
bridge-py/
  run.py                  entry point; --register / --unregister / host mode
  build.py                packs the bridge into one executable
  presence/ipc.py         Discord IPC client
  presence/nativehost.py  stdio framing
  presence/register.py    native messaging manifest install
  presence/activity.py    activity building + when to rewrite the status
  presence/bridge.py      throttling, Discord state
  presence/logs.py        file logging
  presence/config.py      identity, paths, defaults
extension/
  manifest.json
  background.js           native port, tab election, settings
  content/tap.js          page-world API tap and episode lookup
  content/collector.js    page parsing and reporting
  content/frame.js        player-frame timecode
  options.html/.css/.js   settings and live preview
```

## Building from source

```
python bridge-py/build.py
```

Needs `pip install pyinstaller`, and must run on the platform you are building
for — PyInstaller does not cross-compile. The result lands in `bridge-py/dist/`.

The binary is built windowed, with no console: Firefox starts it in the
background and a console window would flash on screen each time. That is safe
only because the host reads and writes the raw file descriptors instead of
`sys.stdin`/`sys.stdout`, which a windowed build may leave empty. Startup costs
a few seconds while the single-file bundle unpacks itself.

## Releasing

```
python release.py --repo owner/name
cd extension
web-ext lint --self-hosted
web-ext sign --channel=unlisted --api-key=... --api-secret=...
```

`--self-hosted` matters: without it the linter applies the rules for add-ons
Mozilla distributes itself and rejects `update_url`, which is exactly the key a
self-hosted add-on needs.

`release.py` bumps the version, points `update_url` at `updates.json` in the
repository, and records the new version there. Then attach the signed `.xpi` to
a GitHub release tagged `v<version>` and push `updates.json`.

Order matters: `update_url` is part of the signed package, so it must be set
before signing. `updates.json` is a plain file and can be refreshed afterwards.
Firefox polls it and updates silently — but only for clients already running a
version that carries `update_url`, so the first such release is still installed
by hand.

Signing through AMO's unlisted channel is not a store listing: the add-on is
signed and handed back, never published or searchable. Each upload needs a new
version — the same one cannot be signed twice.

The add-on id is fixed at `animelib-presence@pureheroky` and must stay that way:
the native messaging manifest lists it in `allowed_extensions`, and the channel
will not open if it changes.

## Troubleshooting

The options page is the first stop: it reports the connection state and the
error text, if any. The bridge log path comes from `python run.py --log`.

| Symptom | Cause |
| --- | --- |
| "Нет связи с Discord", no error text | Discord is not running |
| An error about the host in the options page | the bridge was never registered, or was moved after registering — run `--register` again |
| `Discord rejected Application ID` | the shared application id was overridden with something invalid |
| Status shows but no timer | the player sits in a frame whose domain is missing from the manifest matches |
| Nothing at all on a watch page | the site changed domains; add it to `content_scripts.matches` |
| Status lingers | the bridge clears it when Firefox closes the channel; it also self-clears after 90 seconds of silence |
