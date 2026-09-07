// Owns the single native-messaging connection to the bridge and decides which
// tab gets to be the status.
//
// Election lives here on purpose: only the background knows which tab is
// focused, in which window. Content scripts can only guess from visibility.
'use strict';

const HOST_NAME = 'com.pureheroky.animelib_presence';
const STALE_MS = 12000;
const FRAME_FRESH_MS = 5000;
const ANIMELIB_RE = /^https:\/\/([a-z0-9-]+\.)?(ani|anime)lib\.(org|me|top|social)\//i;

const DEFAULTS = {
  enabled: true,
  onlyWhenFocused: true,
  titleInHeader: true,
  activityType: 3,
  timestampMode: 'remaining',
  showButton: true,
  buttonLabel: 'Смотреть на AnimeLib',
  showTeam: true,
  showCover: true,
  hideTitle: false,
  debug: false,
};

const HOST_KEYS = ['titleInHeader', 'activityType', 'timestampMode', 'showButton', 'buttonLabel', 'debug'];

let settings = { ...DEFAULTS };
const tabs = new Map();
const framePlayers = new Map();
let focusedTabId = null;

let port = null;
let hostState = { discord: false, user: null, error: null };
let lastSentKey = null;
let reconnectAt = 0;

browser.action.onClicked.addListener(() => browser.runtime.openOptionsPage());

function connect() {
  if (port) return port;
  if (Date.now() < reconnectAt) return null;
  try {
    port = browser.runtime.connectNative(HOST_NAME);
  } catch (err) {
    hostState = { discord: false, user: null, error: String(err) };
    reconnectAt = Date.now() + 10000;
    return null;
  }
  port.onMessage.addListener(onHostMessage);
  port.onDisconnect.addListener((p) => {
    const err = p.error || browser.runtime.lastError;
    hostState = {
      discord: false,
      user: null,
      error: err ? err.message || String(err) : null,
    };
    port = null;
    lastSentKey = null;
    reconnectAt = Date.now() + (hostState.error ? 15000 : 2000);
  });

  send({ type: 'hello', version: browser.runtime.getManifest().version });
  pushSettings();
  return port;
}

function send(message) {
  const p = connect();
  if (!p) return false;
  try {
    p.postMessage(message);
    return true;
  } catch {
    port = null;
    return false;
  }
}

function onHostMessage(msg) {
  if (msg.type === 'ready') {
    hostState = { discord: true, user: msg.user, error: null };
  } else if (msg.type === 'status') {
    hostState = { ...hostState, discord: !!msg.discord };
  } else if (msg.type === 'error') {
    hostState = { ...hostState, error: msg.message };
  }
}

function pushSettings() {
  const payload = {};
  for (const key of HOST_KEYS) payload[key] = settings[key];
  send({ type: 'settings', settings: payload });
}

async function loadSettings() {
  const stored = await browser.storage.local.get(DEFAULTS);
  settings = { ...DEFAULTS, ...stored };
}

browser.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  for (const [key, change] of Object.entries(changes)) {
    if (key in DEFAULTS) settings[key] = change.newValue;
  }
  pushSettings();
  lastSentKey = null;
  elect();
});

browser.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.type === 'getStatus') {
    return Promise.resolve({
      ...hostState,
      tabs: tabs.size,
      showing: currentWinner() ? currentWinner().state.title : null,
      cover: currentWinner() ? !!currentWinner().state.cover : null,
      state: currentWinner() ? dress(currentWinner().state) : null,
      settings,
    });
  }

  const tab = sender.tab;
  if (!tab) return;

  if (msg.type === 'framePlayer') {
    if (!ANIMELIB_RE.test(tab.url || '')) return;
    framePlayers.set(tab.id, {
      position: Number(msg.position),
      duration: Number(msg.duration),
      paused: !!msg.paused,
      at: Date.now(),
    });
    elect();
    return;
  }

  if (msg.type === 'presence') {
    const previous = tabs.get(tab.id);
    tabs.set(tab.id, {
      state: msg.state,
      at: Date.now(),
      lastFocusedAt: previous ? previous.lastFocusedAt : 0,
    });
    elect();
    return;
  }

  if (msg.type === 'idle') {
    tabs.delete(tab.id);
    framePlayers.delete(tab.id);
    elect();
  }
});

browser.tabs.onRemoved.addListener((tabId) => {
  tabs.delete(tabId);
  framePlayers.delete(tabId);
  elect();
});

browser.tabs.onActivated.addListener(({ tabId }) => {
  focusedTabId = tabId;
  const entry = tabs.get(tabId);
  if (entry) entry.lastFocusedAt = Date.now();
  elect();
});

browser.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === browser.windows.WINDOW_ID_NONE) return;
  const [active] = await browser.tabs.query({ active: true, windowId });
  if (!active) return;
  focusedTabId = active.id;
  const entry = tabs.get(active.id);
  if (entry) entry.lastFocusedAt = Date.now();
  elect();
});

function merged(tabId, entry) {
  const state = { ...entry.state };
  if (!state.hasLocalPlayer) {
    const frame = framePlayers.get(tabId);
    if (frame && Date.now() - frame.at < FRAME_FRESH_MS) {
      state.position = frame.position;
      state.duration = frame.duration;
      state.status = frame.paused ? 'paused' : 'playing';
    }
  }
  return state;
}

function rank(tabId, state) {
  return (state.status === 'playing' ? 2 : 0) + (tabId === focusedTabId ? 1 : 0);
}

function currentWinner() {
  const now = Date.now();
  const candidates = [];
  for (const [tabId, entry] of tabs) {
    if (now - entry.at > STALE_MS) continue;
    if (settings.onlyWhenFocused && tabId !== focusedTabId) continue;
    const state = merged(tabId, entry);
    candidates.push({ tabId, state, entry, rank: rank(tabId, state) });
  }
  if (!candidates.length) return null;
  candidates.sort(
    (a, b) =>
      b.rank - a.rank ||
      b.entry.lastFocusedAt - a.entry.lastFocusedAt ||
      b.entry.at - a.entry.at,
  );
  return candidates[0];
}

function dress(state) {
  const out = { ...state };
  if (!settings.showTeam) out.team = '';
  if (!settings.showCover) out.cover = '';
  if (settings.hideTitle) {
    out.title = 'Аниме';
    out.titleAlt = '';
    out.episode = undefined;
    out.season = undefined;
    out.episodeName = '';
    out.totalEpisodes = undefined;
    out.team = '';
    out.cover = '';
    out.url = '';
  }
  return out;
}

function elect() {
  if (!settings.enabled) {
    if (lastSentKey !== null) {
      lastSentKey = null;
      send({ type: 'clear' });
    }
    return;
  }

  const winner = currentWinner();
  if (!winner) {
    if (lastSentKey !== null) {
      lastSentKey = null;
      send({ type: 'clear' });
    }
    return;
  }

  const state = dress(winner.state);
  const key = JSON.stringify([
    winner.tabId, state.title, state.episode, state.season,
    state.status, state.team, Math.round(state.position || 0),
  ]);
  if (key === lastSentKey) return;
  lastSentKey = key;
  send({ type: 'presence', state });
}

setInterval(elect, 5000);

async function initFocus() {
  try {
    const [active] = await browser.tabs.query({ active: true, lastFocusedWindow: true });
    if (active) focusedTabId = active.id;
  } catch {}
}

Promise.all([loadSettings(), initFocus()]).then(elect);
