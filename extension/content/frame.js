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

  function findVideo() {
    if (video && video.isConnected) return video;
    const found = Array.from(document.querySelectorAll('video'));
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
