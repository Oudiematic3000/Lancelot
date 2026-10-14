// ---------- Config ----------
const DATA_URL = 'assets/RoundTableMessages_filtered.json';
const ROUNDS = 10;
const MSGS_PER_ROUND = 3;                         // 1 shown at start, up to 2 more via hint
const START_POINTS = 100;
const WRONG_COST = 20;
const HINT_COST = { date: 10, msg: 10, colour: 15 };
const MAX_WRONG = 5;
const IMG_LOAD_TIMEOUT = 8000;                    // ms before an image counts as broken

// ---------- Helpers ----------
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shuffle = a => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const IMG_RE = /\.(png|jpe?g|gif|webp|avif|bmp)(\?|$)/i;

let users = new Map();
let byAuthor = new Map();
let queue = [], pending = null;
let rounds = [], idx = 0, cur = null, results = [];

// ---------- Data ----------
async function init() {
  try {
    const raw = await (await fetch(DATA_URL)).json();
    const msgs = Array.isArray(raw) ? raw : raw.messages;
    for (const m of msgs) {
      const a = m.author;
      if (!a || a.isBot) continue;
      users.set(a.id, {
        id: a.id, name: a.nickname || a.name, username: a.name, color: a.color || null,
        roles: a.roles || [], avatar: a.avatarUrl
      });
      const ok = ['Default', 'Reply'].includes(m.type) && ((m.content || '').trim() || (m.attachments || []).length);
      if (ok) (byAuthor.get(a.id) || byAuthor.set(a.id, []).get(a.id)).push(m);
    }
    startGame();
  } catch (e) {
    $('#app').innerHTML = `Couldn't load <code>${DATA_URL}</code>. Serve over http(s) (GitHub Pages, or <code>python -m http.server</code> locally).<br><small>${esc(e.message)}</small>`;
  }
}

// ---------- Attachment checking (rerolls messages whose images 404) ----------
const okCache = new Map();
const loadImg = url => new Promise(res => {
  const img = new Image();
  const t = setTimeout(() => res(false), IMG_LOAD_TIMEOUT);
  img.onload = () => { clearTimeout(t); res(true); };
  img.onerror = () => { clearTimeout(t); res(false); };
  img.src = url;
});
async function msgOk(m) {
  if (okCache.has(m.id)) return okCache.get(m.id);
  const imgs = (m.attachments || []).filter(a => IMG_RE.test(a.fileName || a.url || ''));
  const ok = (await Promise.all(imgs.map(a => loadImg(a.url)))).every(Boolean);
  okCache.set(m.id, ok);
  return ok;
}

// Builds one round: picks an author, then 3 of their messages whose images all load.
// Authors that can't supply 3 working messages are skipped.
async function buildRound(q) {
  while (q.length) {
    const id = q.pop();
    const good = [];
    for (const m of shuffle(byAuthor.get(id))) {
      if (await msgOk(m)) good.push(m);
      if (good.length === MSGS_PER_ROUND) break;
    }
    if (good.length === MSGS_PER_ROUND) {
      return { answer: users.get(id), msgs: good, date: false, colour: false, extra: 0, wrong: 0, guessed: [], done: false, points: 0 };
    }
  }
  return null;
}

function startGame() {
  queue = shuffle([...byAuthor].filter(([, v]) => v.length >= MSGS_PER_ROUND).map(([id]) => id));
  rounds = []; results = []; idx = 0;
  pending = buildRound(queue);
  loadRound();
}

async function loadRound() {
  const app = $('#app');
  app.className = 'center'; app.textContent = 'Loading round…';
  const r = await pending;
  if (!r) {
    if (!results.length) { app.textContent = 'Not enough messages with working attachments.'; return; }
    return showEnd();
  }
  rounds[idx] = r; cur = r;
  pending = idx < ROUNDS - 1 ? buildRound(queue) : null;   // prefetch next round while playing
  showRound();
}

// ---------- Scoring ----------
const potential = r => Math.max(0, START_POINTS - r.wrong * WRONG_COST
  - (r.date ? HINT_COST.date : 0) - (r.colour ? HINT_COST.colour : 0) - r.extra * HINT_COST.msg);
const total = () => results.reduce((a, b) => a + b, 0);

// ---------- Rendering ----------
function renderContent(m) {
  let t = esc(m.content || '');
  t = t.replace(/&lt;(a?):(\w+):(\d+)&gt;/g, (_, an, name, id) =>
    `<img class="emoji" alt=":${name}:" title=":${name}:" src="https://cdn.discordapp.com/emojis/${id}.${an ? 'gif' : 'png'}?size=48">`);
  t = t.replace(/&lt;@&amp;\d+&gt;/g, '<span class="mention">@role</span>')
       .replace(/&lt;@!?\d+&gt;/g, '<span class="mention">@someone</span>')
       .replace(/&lt;#\d+&gt;/g, '<span class="mention">#channel</span>')
       .replace(/\n/g, '<br>');
  const att = (m.attachments || []).map(a => {
    const src = esc(a.url || '');
    return IMG_RE.test(a.fileName || a.url || '')
      ? `<img class="att" loading="lazy" src="${src}" alt="attachment" onerror="this.outerHTML='<span class=file>image unavailable</span>'">`
      : `<span class="file">📎 ${esc(a.fileName || 'attachment')}</span>`;
  }).join('');
  return t + att;
}

const fmtDate = ts => new Date(ts).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });

const msgHtml = m => `<div class="msg"><div class="when" style="display:${cur.date ? 'block' : 'none'}">${fmtDate(m.timestamp)}</div>${renderContent(m)}</div>`;

function hintHtml(r) {
  const left = MSGS_PER_ROUND - 1 - r.extra;
  const btn = (id, label, off) => `<button id="${id}" ${off ? 'disabled' : ''}>${label}</button>`;
  let h = `<div class="hint" style="flex-wrap:wrap">`
    + btn('hDate', r.date ? 'Date shown' : `Reveal date (−${HINT_COST.date})`, r.date || r.done)
    + btn('hMsg', left ? `Another message (−${HINT_COST.msg})` : 'No more messages', !left || r.done)
    + btn('hCol', r.colour ? 'Colour shown' : `Reveal colour (−${HINT_COST.colour})`, r.colour || r.done)
    + `</div>`;
  if (r.colour) {
    const c = r.answer.color;
    h += `<div class="hint on"><span class="k">Username colour</span><span>${c ? `<span class="swatch" style="background:${esc(c)}"></span>${esc(c)}` : 'Default (no colour)'}</span></div>`;
  }
  return h;
}

function showRound() {
  $('#bar').style.width = (idx / ROUNDS * 100) + '%';
  $('#app').className = '';
  $('#app').innerHTML = `
    <div id="msgs">${cur.msgs.slice(0, 1 + cur.extra).map(msgHtml).join('')}</div>
    <div class="hints" id="hints"></div>
    <div id="play">
      <div class="search">
        <input id="q" type="text" placeholder="Search for a user…" autocomplete="off" aria-label="Search users">
        <div class="list" id="list"></div>
      </div>
      <div class="cost" id="cost"></div>
      <div class="wrong" id="wrong"></div>
    </div>
    <div id="result"></div>`;
  refresh();
  const q = $('#q');
  q.addEventListener('input', renderList);
  q.addEventListener('focus', renderList);
  q.addEventListener('blur', () => setTimeout(() => { const l = $('#list'); if (l) l.classList.remove('open'); }, 120));
  q.addEventListener('keydown', e => { if (e.key === 'Enter') { const f = $('#list div[data-id]'); if (f) guess(f.dataset.id); } });
  q.focus();
}

function refresh() {
  $('#hints').innerHTML = hintHtml(cur);
  const on = (id, fn) => { const b = $(id); if (b && !b.disabled) b.onclick = () => { fn(); refresh(); }; };
  on('#hDate', () => { cur.date = true; document.querySelectorAll('#msgs .when').forEach(e => e.style.display = 'block'); });
  on('#hMsg', () => { cur.extra++; $('#msgs').insertAdjacentHTML('beforeend', msgHtml(cur.msgs[cur.extra])); });
  on('#hCol', () => { cur.colour = true; });
  const cost = $('#cost'); if (cost) cost.textContent = `Worth ${potential(cur)} points · wrong guess −${WRONG_COST}`;
  const wrong = $('#wrong'); if (wrong) wrong.innerHTML = cur.guessed.map(id => `<span>${esc(users.get(id).name)}</span>`).join('');
  $('#stats').innerHTML = `Round ${idx + 1}/${ROUNDS} · Score <b>${total()}</b>`;
}

function renderList() {
  const term = $('#q').value.trim().toLowerCase();
  const list = [...users.values()]
    .filter(u => !cur.guessed.includes(u.id) && (!term || u.name.toLowerCase().includes(term) || u.username.toLowerCase().includes(term)))
    .sort((a, b) => a.name.localeCompare(b.name)).slice(0, 50);
  const el = $('#list');
  el.innerHTML = list.map(u => `<div data-id="${u.id}"><img src="${esc(u.avatar)}" alt="" loading="lazy"><span>${esc(u.name)} <small>@${esc(u.username)}</small></span></div>`).join('')
    || '<div style="cursor:default">No matching users</div>';
  el.classList.add('open');
  el.querySelectorAll('div[data-id]').forEach(d => d.onmousedown = e => { e.preventDefault(); guess(d.dataset.id); });
}

function guess(id) {
  if (cur.done || cur.guessed.includes(id)) return;
  if (id === cur.answer.id) return finish(true);
  cur.guessed.push(id); cur.wrong++;
  $('#q').value = ''; $('#list').classList.remove('open');
  if (cur.wrong >= MAX_WRONG || potential(cur) <= 0) return finish(false);
  refresh();
}

function finish(won) {
  cur.done = true;
  cur.points = won ? potential(cur) : 0;
  results.push(cur.points);
  refresh();
  $('#play').remove();
  const u = cur.answer, last = idx === ROUNDS - 1;
  $('#result').innerHTML = `<div class="reveal">
    <div>${won ? 'Correct!' : 'Out of guesses. It was:'}</div>
    <div class="who"><img src="${esc(u.avatar)}" alt=""><span>${esc(u.name)} <small style="color:var(--dim)">@${esc(u.username)}</small></span></div>
    <div class="pts ${won ? 'good' : 'bad'}">+${cur.points}</div>
    <button class="primary" id="next">${last ? 'See final score' : 'Next round'}</button></div>`;
  $('#stats').innerHTML = `Round ${idx + 1}/${ROUNDS} · Score <b>${total()}</b>`;
  $('#next').onclick = () => { if (last) return showEnd(); idx++; loadRound(); };
  $('#next').focus();
}

function showEnd() {
  $('#bar').style.width = '100%';
  const n = results.length, max = n * START_POINTS, sc = total();
  const squares = results.map(p => p >= START_POINTS * .6 ? '🟩' : p > 0 ? '🟨' : '🟥').join('');
  $('#stats').innerHTML = 'Finished';
  $('#app').className = '';
  $('#app').innerHTML = `<div class="end">
    <div>Final score</div><div class="big">${sc}<small style="font-size:1.2rem;color:var(--dim)"> / ${max}</small></div>
    <div class="rows">${rounds.slice(0, n).map((r, i) => `<div><span>${i + 1}. ${esc(r.answer.name)}</span><span>${results[i]} pts</span></div>`).join('')}</div>
    <button id="share">Copy result</button> <button class="primary" id="again">Play again</button></div>`;
  $('#again').onclick = startGame;
  $('#share').onclick = async e => {
    try { await navigator.clipboard.writeText(`Knightle ${sc}/${max}\n${squares}`); e.target.textContent = 'Copied!'; }
    catch { e.target.textContent = 'Copy failed'; }
  };
}

init();