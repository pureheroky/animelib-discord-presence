'use strict';

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

const CHECKBOXES = ['enabled', 'onlyWhenFocused', 'titleInHeader', 'showButton', 'showTeam',
                    'showCover', 'hideTitle', 'debug'];
const SELECTS = ['activityType', 'timestampMode'];
const TEXTS = ['buttonLabel'];

let settings = { ...DEFAULTS };

const SAMPLE = {
  title: 'Re:Zero. Жизнь с нуля в альтернативном мире',
  season: 4, episode: 15, totalEpisodes: 15, team: 'AniLibria.TV',
  position: 462, duration: 1440, status: 'playing',
  cover: browser.runtime.getURL('icons/extension.jpg'),
  url: 'https://animelib.org/',
};

const APP_NAME = 'AnimeLib';
const VERBS = { 3: 'Watching', 0: 'Playing', 2: 'Listening to' };

let liveState = null;

const el = (id) => document.getElementById(id);

function episodeLine(s, withTeam = true) {
  const parts = [];
  if (s.season > 1) parts.push('Сезон ' + s.season);
  if (s.episode != null) {
    parts.push(s.episode + ' серия' + (s.totalEpisodes ? ' из ' + s.totalEpisodes : ''));
  }
  if (withTeam && s.team) parts.push(s.team);
  return parts.join(' · ');
}

const clock = (t) => {
  t = Math.max(0, Math.round(t));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h ? h + ':' + pad(m) + ':' + pad(sec) : pad(m) + ':' + pad(sec);
};

// Mirrors dress() in background.js: live state arrives already filtered, but the
// sample does not, and a toggle that changes nothing on screen is useless.
function dressed(state) {
  const out = { ...state };
  if (!settings.showTeam) out.team = '';
  if (!settings.showCover) out.cover = '';
  if (settings.hideTitle) {
    out.title = 'Аниме';
    out.episode = undefined;
    out.season = undefined;
    out.totalEpisodes = undefined;
    out.team = '';
    out.cover = '';
    out.url = '';
  }
  return out;
}

function renderPreview() {
  const live = liveState;
  const s = dressed(live || SAMPLE);
  el('pvSource').textContent = live
    ? 'Сейчас в Discord — вживую.'
    : 'Пример: пока ничего не играет.';

  const paused = s.status === 'paused';
  const verb = VERBS[settings.activityType] || 'Watching';

  // Same split as build_activity() in the bridge.
  if (settings.titleInHeader) {
    const head = episodeLine(s, false);
    const tail = [s.team, paused ? 'На паузе' : ''].filter(Boolean).join(' · ');
    el('pvHead').textContent = verb + ' ' + (s.title || '');
    el('pvDetails').textContent = head || (tail ? '' : 'Смотрит на AnimeLib');
    el('pvState').textContent = tail;
  } else {
    const line = episodeLine(s);
    const suffix = paused ? (line ? ' · На паузе' : 'На паузе') : '';
    el('pvHead').textContent = verb + ' ' + APP_NAME;
    el('pvDetails').textContent = s.title || '';
    el('pvState').textContent = (line + suffix) || 'Смотрит на AnimeLib';
  }

  const cover = el('pvCover');
  cover.style.backgroundImage = s.cover ? 'url("' + s.cover + '")' : 'none';
  el('pvBadge').hidden = true;

  const timed = !paused && settings.timestampMode !== 'off'
    && Number.isFinite(s.duration) && s.duration > 0 && Number.isFinite(s.position);
  el('pvBar').hidden = !timed;
  el('pvTimes').hidden = !timed;
  if (timed) {
    const done = Math.min(1, Math.max(0, s.position / s.duration));
    el('pvFill').style.width = (done * 100).toFixed(1) + '%';
    el('pvLeft').textContent = clock(s.position);
    el('pvRight').textContent = settings.timestampMode === 'remaining'
      ? clock(s.duration)
      : clock(s.duration - s.position) + ' left';
  }

  el('pvButton').textContent =
    settings.showButton && s.url ? settings.buttonLabel || '' : '';
}

function renderStatus(info) {
  const dot = el('dot');
  const line = el('statusLine');
  const hint = el('statusHint');

  if (!info) {
    dot.className = 'dot';
    line.textContent = 'Фоновая страница не отвечает';
    hint.textContent = 'Попробуй перезагрузить расширение';
    return;
  }
  if (info.discord) {
    dot.className = 'dot ok';
    line.textContent = 'Discord подключён' + (info.user ? ' — ' + info.user : '');
    hint.textContent = info.showing
      ? 'Сейчас в статусе: ' + info.showing +
        ' · обложка ' + (info.cover ? 'поймана' : 'НЕ поймана')
      : 'Вкладок с аниме: ' + info.tabs;
    return;
  }
  dot.className = 'dot bad';
  // Firefox reports a missing host as "No such native application <name>",
  // which says nothing useful to someone who just installed the add-on.
  const missingHost = /no such native application|not found|не найден/i.test(info.error || '');
  if (missingHost) {
    line.textContent = 'Мост не установлен';
    hint.textContent = 'Расширение — только половина. Скачай мост и выполни один раз: '
      + 'python run.py --register, затем перезагрузи эту страницу.';
    return;
  }
  line.textContent = 'Нет связи с Discord';
  hint.textContent = info.error || 'Проверь, что Discord запущен';
}

async function refreshStatus() {
  try {
    const info = await browser.runtime.sendMessage({ type: 'getStatus' });
    liveState = (info && info.state) || null;
    renderStatus(info);
    renderPreview();
  } catch {
    renderStatus(null);
  }
}

async function save(key, value) {
  settings[key] = value;
  await browser.storage.local.set({ [key]: value });
  renderPreview();
}

async function init() {
  settings = { ...DEFAULTS, ...(await browser.storage.local.get(DEFAULTS)) };

  for (const id of CHECKBOXES) {
    el(id).checked = !!settings[id];
    el(id).addEventListener('change', (e) => save(id, e.target.checked));
  }
  for (const id of SELECTS) {
    el(id).value = String(settings[id]);
    el(id).addEventListener('change', (e) =>
      save(id, id === 'activityType' ? Number(e.target.value) : e.target.value));
  }
  for (const id of TEXTS) {
    el(id).value = settings[id] || '';
    el(id).addEventListener('input', (e) => save(id, e.target.value));
  }

  renderPreview();
  refreshStatus();
  setInterval(refreshStatus, 3000);
}

init();
