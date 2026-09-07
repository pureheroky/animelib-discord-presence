// Isolated-world script on AnimeLib pages: works out what is playing and
// reports it to the background. Which tab actually wins is decided there —
// the background knows which one is focused.
(() => {
  'use strict';

  const TICK_MS = 2000;
  const HEARTBEAT_MS = 8000;   
  const DRIFT_SEC = 3;         

  const cache = {
    anime: new Map(),
    episodesByAnime: new Map(),
    episodeById: new Map(),
    lastAnimeKey: null,
  };

  window.addEventListener('message', (event) => {
    if (event.source !== window) return;
    const msg = event.data;
    if (!msg || msg.__animelibTap !== true) return;
    remember(msg.url, msg.data);
  });

  function looksLikeTitle(d) {
    return !!d && !Array.isArray(d) && typeof d === 'object'
      && !!(d.rus_name || d.eng_name || d.name)
      && !!(d.cover || d.slug_url || d.items_count);
  }

  function looksLikeEpisode(d) {
    return !!d && !Array.isArray(d) && typeof d === 'object'
      && d.number != null
      && (d.anime_id != null || d.item_id != null || Array.isArray(d.players));
  }

  function rememberTitle(data) {
    const key = data.slug_url || data.slug || String(data.id ?? '');
    if (!key) return;
    cache.anime.set(key, data);
    if (data.id != null) cache.anime.set(String(data.id), data);
    cache.lastAnimeKey = key;
  }

  function rememberEpisodes(list) {
    for (const ep of list) {
      if (ep && ep.id != null) cache.episodeById.set(String(ep.id), ep);
    }
    const first = list[0];
    const animeId = first && (first.anime_id ?? first.item_id);
    if (list.length > 1 && animeId != null) {
      cache.episodesByAnime.set(String(animeId), list);
    }
  }

  function remember(url, data) {
    if (Array.isArray(data)) {
      if (data.length && looksLikeEpisode(data[0])) rememberEpisodes(data);
      return;
    }
    if (looksLikeEpisode(data)) {
      rememberEpisodes([data]);
      for (const key of ['anime', 'item', 'media']) {
        if (looksLikeTitle(data[key])) rememberTitle(data[key]);
      }
      return;
    }
    if (looksLikeTitle(data)) rememberTitle(data);
  }

  const num = (v) => {
    const n = Number(String(v).replace(',', '.'));
    return Number.isFinite(n) ? n : undefined;
  };

  function animeKey() {
    const m = location.pathname.match(/\/anime\/([^/?#]+)/i);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function isWatchPage() {
    if (/\/(watch|episode|player)/i.test(location.href)) return true;
    if (!/\/anime\//i.test(location.pathname)) return false;
    const v = currentVideo();
    return !!v && Number.isFinite(v.duration) && v.duration > 60;
  }

  function episodeIdFromUrl() {
    const q = new URLSearchParams(location.search);
    for (const k of ['episode', 'ep', 'e', 'episode_id']) {
      const v = q.get(k);
      if (v && /^\d+$/.test(v)) return v;
    }
    const m = location.pathname.match(/\/watch\/(\d+)/);
    return m ? m[1] : null;
  }

  // The page title is SEO-shaped: "<name> смотреть онлайн. Серия 8 • AnimeLIB".
  //
  // Note: \b is ASCII-only in JavaScript, so it never matches the edge of a
  // Cyrillic word — every boundary below is spelled out with real separators.
  const TITLE_SEP = /\s*[|•·]\s*|\s+[—–]\s+|\s+\/\s+/;
  const TITLE_STOP = /(?:^|[\s,.:;(-])(?:смотреть|онлайн|бесплатно|watch|online)(?:[\s,.:;)]|$)/i;

  function parseTitleInfo() {
    const raw = document.title || '';
    // The number and the word come in either order: "8 серия" and "Серия 8".
    const ep = raw.match(/(\d+(?:[.,]\d+)?)\s*(?:-?я\s*)?(?:сери[яи]|эпизод|episode)/i)
      || raw.match(/(?:сери[яи]|эпизод|episode)\s*[№#]?\s*(\d+(?:[.,]\d+)?)/i);
    const se = raw.match(/(\d+)\s*(?:сезон|season)/i)
      || raw.match(/(?:сезон|season)\s*[№#]?\s*(\d+)/i);

    let name = raw.split(TITLE_SEP)[0] || '';
    const stop = name.match(TITLE_STOP);
    if (stop) name = name.slice(0, stop.index);

    name = name
      .replace(/^(?:смотреть|watch)\s+/i, '')
      .replace(/^(?:аниме|anime)\s+/i, '')
      .replace(/[\s,—–-]*\d+(?:[.,]\d+)?\s*(?:-?я\s*)?(?:сери[яи]|эпизод|episode)/gi, ' ')
      .replace(/[\s,—–-]*(?:сери[яи]|эпизод|episode)\s*[№#]?\s*\d+/gi, ' ')
      .replace(/[\s,—–-]*\d+\s*(?:сезон|season)/gi, ' ')
      .replace(/[\s,—–-]*(?:сезон|season)\s*[№#]?\s*\d+/gi, ' ')
      .replace(/\s{2,}/g, ' ')
      .replace(/[\s,.:;—–-]+$/, '')
      .trim();

    return { name, episode: ep ? num(ep[1]) : undefined, season: se ? num(se[1]) : undefined };
  }

  function lookupAnime() {
    const key = animeKey();
    if (key && cache.anime.has(key)) return cache.anime.get(key);
    const id = key && key.match(/^(\d+)/);
    if (id && cache.anime.has(id[1])) return cache.anime.get(id[1]);
    if (cache.lastAnimeKey) return cache.anime.get(cache.lastAnimeKey);
    return null;
  }

  const teamCache = new Map();
  function pickTeam(ep) {
    if (!ep) return '';
    const players = Array.isArray(ep.players) ? ep.players : [];
    const named = players.map((p) => p && p.team && p.team.name).filter(Boolean);
    if (!named.length) return '';

    const q = new URLSearchParams(location.search);
    const wanted = q.get('team_id') || q.get('team');
    if (wanted) {
      const hit = players.find(
        (p) => p && p.team && (String(p.team.id) === wanted || p.team.slug === wanted),
      );
      if (hit) return hit.team.name;
    }
    if (named.length === 1) return named[0];
    const cacheKey = ep.id + '|' + (wanted || '');
    if (teamCache.has(cacheKey)) return teamCache.get(cacheKey);
    const text = document.body ? document.body.innerText : '';
    const shown = named.find((n) => text.includes(n)) || '';
    teamCache.set(cacheKey, shown);
    return shown;
  }

  function resolveEpisode(anime, fallback) {
    const id = episodeIdFromUrl();
    let ep = id ? cache.episodeById.get(id) : null;
    if (!ep && anime && anime.id != null) {
      const list = cache.episodesByAnime.get(String(anime.id));
      if (list && fallback.episode != null) {
        ep = list.find((e) => num(e.number) === fallback.episode) || null;
      }
    }
    if (!ep) {
      return { episode: fallback.episode, season: fallback.season, episodeName: '', team: '' };
    }
    return {
      episode: num(ep.number) ?? fallback.episode,
      season: num(ep.season) ?? fallback.season,
      episodeName: typeof ep.name === 'string' ? ep.name : '',
      team: pickTeam(ep),
    };
  }

  function totalEpisodes(anime) {
    if (!anime) return undefined;
    const list = cache.episodesByAnime.get(String(anime.id));
    if (list && list.length) return list.length;
    const c = anime.items_count;
    if (typeof c === 'number') return c;
    if (c && typeof c === 'object') return num(c.uploaded ?? c.total ?? c.count);
    return undefined;
  }

  function animeId() {
    const key = animeKey();
    const m = key && key.match(/^(\d+)/);
    return m ? m[1] : null;
  }

  function coverFromDom() {
    const id = animeId();
    if (!id) return '';
    const needle = '/uploads/anime/' + id + '/';
    const urls = [];
    const push = (u) => {
      if (typeof u === 'string' && u.startsWith('https://')) urls.push(u);
    };
    try {
      document.querySelectorAll('img[src], img[srcset], [style*="background-image"]')
        .forEach((el) => {
          push(el.currentSrc || el.src);
          const set = el.getAttribute && el.getAttribute('srcset');
          if (set) set.split(',').forEach((part) => push(part.trim().split(/\s+/)[0]));
          const style = el.getAttribute && el.getAttribute('style');
          const m = style && style.match(/url\((['"]?)(https:\/\/[^)'"]+)\1\)/);
          if (m) push(m[2]);
        });
    } catch {}
    const hit = urls.find((u) => u.includes(needle));
    return hit ? hit.replace(/_thumb(\.[a-z]+)(\?|$)/i, '$1$2') : '';
  }

  function coverUrl(anime) {
    const c = anime && anime.cover;
    const fromApi = c && (c.default || c.md || c.thumbnail);
    if (/^https:\/\//.test(fromApi || '')) return fromApi;

    const og = document.querySelector('meta[property="og:image"]');
    const meta = og && og.content;
    if (/^https:\/\//.test(meta || '')) return meta;

    return coverFromDom();
  }

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

  let video = null;
  function currentVideo() {
    if (video && video.isConnected) return video;
    const found = deepVideos(document);
    if (!found.length) {
      video = null;
      return null;
    }
    found.sort((a, b) => (b.duration || 0) - (a.duration || 0));
    video = found[0];
    for (const evt of ['play', 'pause', 'seeked', 'ended', 'loadedmetadata']) {
      video.addEventListener(evt, () => tick(true), { passive: true });
    }
    return video;
  }

  function buildState() {
    if (!isWatchPage()) return null;
    const v = currentVideo();
    const anime = lookupAnime();
    const fromTitle = parseTitleInfo();
    const ep = resolveEpisode(anime, fromTitle);

    const title = (anime && (anime.rus_name || anime.name || anime.eng_name)) || fromTitle.name;
    if (!title) return null;

    const local = v
      ? {
          duration: Number.isFinite(v.duration) ? v.duration : undefined,
          position: Number.isFinite(v.currentTime) ? v.currentTime : undefined,
          playing: !v.paused && !v.ended && v.readyState >= 2,
        }
      : null;

    return {
      status: !local ? 'playing' : local.playing ? 'playing' : 'paused',
      hasLocalPlayer: !!local,
      title,
      titleAlt: (anime && (anime.name || anime.eng_name)) || '',
      episode: ep.episode,
      season: ep.season,
      episodeName: ep.episodeName,
      totalEpisodes: totalEpisodes(anime),
      team: ep.team,
      position: local ? local.position : undefined,
      duration: local ? local.duration : undefined,
      cover: coverUrl(anime),
      url: location.href.split('#')[0],
    };
  }

  let lastKey = null;
  let lastSentAt = 0;
  let lastPos = 0;
  let announced = false;

  function post(message) {
    browser.runtime.sendMessage(message).catch(() => {});
  }

  function tick(force = false) {
    const state = buildState();

    if (!state) {
      if (announced) {
        announced = false;
        lastKey = null;
        post({ type: 'idle' });
      }
      return;
    }

    const now = Date.now();
    const key = JSON.stringify([
      state.title, state.episode, state.season, state.status,
      state.totalEpisodes, state.team,
    ]);
    const drifted =
      state.status === 'playing' &&
      Number.isFinite(state.position) &&
      Math.abs(state.position - (lastPos + (now - lastSentAt) / 1000)) > DRIFT_SEC;

    if (!force && key === lastKey && !drifted && now - lastSentAt < HEARTBEAT_MS) return;

    lastKey = key;
    lastSentAt = now;
    lastPos = Number.isFinite(state.position) ? state.position : 0;
    announced = true;
    post({ type: 'presence', state });
  }

  setInterval(() => tick(false), TICK_MS);
  window.addEventListener('pagehide', () => post({ type: 'idle' }));

  for (const method of ['pushState', 'replaceState']) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      setTimeout(() => tick(true), 400);
      return result;
    };
  }
  window.addEventListener('popstate', () => setTimeout(() => tick(true), 400));
})();
