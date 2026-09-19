// Runs inside third-party player frames (Kodik and friends).
//
// Some AnimeLib titles play in a cross-origin frame whose <video> the page
// above cannot touch. Instead of relaying through the page, this script talks
// to the background directly — the background knows which tab the frame
// belongs to and verifies that tab is actually AnimeLib.
(() => {
  'use strict';

  const TICK_MS = 1000;
  let video = null;

  // The player may sit in a nested same-origin frame or behind a shadow root,
  // so a flat querySelectorAll is not enough.
  function deepVideos(root, out = [], depth = 0) {
    if (!root || depth > 4 || typeof root.querySelectorAll !== 'function') return out;
    try {
      root.querySelectorAll('video').forEach((v) => out.push(v));
    } catch {}
    try {
      root.querySelectorAll('iframe').forEach((f) => {
        let doc = null;
        try {
          doc = f.contentDocument;
        } catch {}
        if (doc) deepVideos(doc, out, depth + 1);
      });
    } catch {}
    try {
      root.querySelectorAll('*').forEach((el) => {
        if (el.shadowRoot) deepVideos(el.shadowRoot, out, depth + 1);
      });
    } catch {}
    return out;
  }

  const usable = (v) => !!v && Number.isFinite(v.duration) && v.duration > 0;

  function findVideo() {
    // Same trap as on the page above: keep looking until an element that knows
    // its duration shows up, instead of latching onto a placeholder.
    if (video && video.isConnected && usable(video)) return video;
    const found = deepVideos(document);
    // The real episode is the longest track, not a preview or an ad.
    found.sort((a, b) => (b.duration || 0) - (a.duration || 0));
    video = found[0] || null;
    return video;
  }

  setInterval(() => {
    const v = findVideo();
    if (!v) return;
    browser.runtime
      .sendMessage({
        type: 'framePlayer',
        position: v.currentTime,
        duration: v.duration,
        paused: v.paused || v.ended || v.readyState < 2,
      })
      .catch(() => {});
  }, TICK_MS);
})();
