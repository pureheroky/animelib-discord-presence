// Runs in the page's own world (world: "MAIN") so it can patch the site's
// fetch/XHR. The isolated content script cannot: it sees a different window.
//
// Tapping the site's own API is sturdier than scraping markup — it yields the
// exact title, episode number, season, cover and dub list the player uses.
(() => {
  'use strict';

  const WANTED = /\/api\//;

  function forwardData(url, data) {
    if (data) window.postMessage({ __animelibTap: true, url, data }, '*');
  }

  function forward(url, text) {
    let json;
    try {
      json = JSON.parse(text);
    } catch {
      return;
    }
    if (json && json.data) forwardData(url, json.data);
  }

  const nativeFetch = window.fetch;
  if (typeof nativeFetch === 'function') {
    window.fetch = function (...args) {
      const promise = nativeFetch.apply(this, args);
      try {
        const input = args[0];
        const url = typeof input === 'string' ? input : input && input.url;
        if (url && WANTED.test(url)) {
          promise
            .then((res) => {
              res.clone().text().then((t) => forward(url, t)).catch(() => {});
            })
            .catch(() => {});
        }
      } catch {}
      return promise;
    };
  }
  const API = 'https://api.cdnlibs.org';
  let askedFor = null;

  function askForEpisode() {
    const q = new URLSearchParams(location.search);
    const id = q.get('episode') || q.get('ep') || q.get('e');
    if (!id || !/^\d+$/.test(id) || id === askedFor) return;
    askedFor = id;
    nativeFetch(API + '/api/episodes/' + id)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (j && j.data) forwardData('asked:/api/episodes/' + id, j.data);
      })
      .catch(() => {
        askedFor = null;
      });
  }

  setInterval(askForEpisode, 2000);
  askForEpisode();

  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__tapUrl = url;
    return open.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    try {
      const url = this.__tapUrl;
      if (typeof url === 'string' && WANTED.test(url)) {
        this.addEventListener('load', () => {
          try {
            const body =
              this.responseType === '' || this.responseType === 'text'
                ? this.responseText
                : JSON.stringify(this.response);
            forward(url, body);
          } catch {}
        });
      }
    } catch {}
    return send.apply(this, args);
  };
})();
