// ---------- Config ----------
const DATA_URL = 'assets/RoundTableMessages.json';   
const ROUNDS = 10;                 
const MSGS_PER_ROUND = 3;
const START_POINTS = 100;           
const WRONG_COST = 20;              
const HINT_COST = [10, 15, 20];     
const MAX_WRONG = 5;                

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shuffle = a => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const IMG_RE = /\.(png|jpe?g|gif|webp|avif|bmp)(\?|$)/i;

let users = new Map();     
let byAuthor = new Map();  
let rounds = [], idx = 0, cur = null, results = [];
-
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
    $('#app').innerHTML = `Couldn't load <code>${DATA_URL}</code>. Put the export next to index.html and serve over http(s) (GitHub Pages, or <code>python -m http.server</code> locally).<br><small>${esc(e.message)}</small>`;
  }
}

function startGame() {
  const eligible = [...byAuthor].filter(([, v]) => v.length >= MSGS_PER_ROUND).map(([id]) => id);
  rounds = shuffle(eligible).slice(0, ROUNDS).map(id => ({
    answer: users.get(id),
    msgs: shuffle(byAuthor.get(id)).slice(0, MSGS_PER_ROUND).sort((a, b) => a.timestamp.localeCompare(b.timestamp)),
    hints: 0, wrong: 0, guessed: [], done: false, points: 0
  }));
  idx = 0; results = [];
  if (!rounds.length) { $('#app').textContent = 'Not enough messages: need users with at least ' + MSGS_PER_ROUND + ' messages.'; return; }
  showRound();
}

const potential = r => Math.max(0, START_POINTS - r.wrong * WRONG_COST - HINT_COST.slice(0, r.hints).reduce((a, b) => a + b, 0));
const total = () => results.reduce((a, b) => a + b, 0);


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

function topRole(u) {
  return [...u.roles].sort((a, b) => b.position - a.position)[0];
}

function hintHtml(r) {
  const u = r.answer;
  const role = topRole(u);
  const items = [
    ['Date sent', r.msgs.map(m => fmtDate(m.timestamp)).join(', ')],
    ['Username colour', u.color ? `<span class="swatch" style="background:${esc(u.color)}"></span>${esc(u.color)}` : 'Default (no colour)'],
    ['Role', role ? `<span style="color:${esc(role.color || 'inherit')}">${esc(role.name)}</span> (highest role)` : 'No roles']
  ];
  const names = ['date sent', 'username colour', 'role'];
  return items.map(([k, v], i) => i < r.hints
    ? `<div class="hint on"><span class="k">${k}</span><span>${v}</span></div>`
    : i === r.hints && !r.done
      ? `<div class="hint"><button id="hintBtn">Reveal ${names[i]} (−${HINT_COST[i]})</button></div>`
      : `<div class="hint"><span class="k" style="opacity:.5">${k}</span></div>`).join('');
}

function showRound() {
  cur = rounds[idx];
  $('#bar').style.width = (idx / rounds.length * 100) + '%';
  $('#stats').innerHTML = `Round ${idx + 1}/${rounds.length} · Score <b>${total()}</b>`;
  $('#app').className = '';
  $('#app').innerHTML = `
    ${cur.msgs.map(m => `<div class="msg">${renderContent(m)}</div>`).join('')}
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
  q.addEventListener('blur', () => setTimeout(() => $('#list').classList.remove('open'), 120));
  q.addEventListener('keydown', e => { if (e.key === 'Enter') { const f = $('#list div'); if (f) guess(f.dataset.id); } });
  q.focus();
}

function refresh() {
  $('#hints').innerHTML = hintHtml(cur);
  const b = $('#hintBtn'); if (b) b.onclick = () => { cur.hints++; refresh(); };
  $('#cost').textContent = `Worth ${potential(cur)} points · wrong guess −${WRONG_COST}`;
  $('#wrong').innerHTML = cur.guessed.map(id => `<span>${esc(users.get(id).name)}</span>`).join('');
  $('#stats').innerHTML = `Round ${idx + 1}/${rounds.length} · Score <b>${total()}</b>`;
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
  $('#play').remove();
  refresh();
  const u = cur.answer, last = idx === rounds.length - 1;
  $('#result').innerHTML = `<div class="reveal">
    <div>${won ? 'Correct!' : 'Out of guesses. It was:'}</div>
    <div class="who"><img src="${esc(u.avatar)}" alt=""><span>${esc(u.name)} <small style="color:var(--dim)">@${esc(u.username)}</small></span></div>
    <div class="pts ${won ? 'good' : 'bad'}">+${cur.points}</div>
    <button class="primary" id="next">${last ? 'See final score' : 'Next round'}</button></div>`;
  $('#stats').innerHTML = `Round ${idx + 1}/${rounds.length} · Score <b>${total()}</b>`;
  $('#next').onclick = () => last ? showEnd() : (idx++, showRound());
  $('#next').focus();
}

function showEnd() {
  $('#bar').style.width = '100%';
  const max = rounds.length * START_POINTS, sc = total();
  const squares = results.map(p => p >= START_POINTS * .6 ? '🟩' : p > 0 ? '🟨' : '🟥').join('');
  $('#stats').innerHTML = 'Finished';
  $('#app').innerHTML = `<div class="end">
    <div>Final score</div><div class="big">${sc}<small style="font-size:1.2rem;color:var(--dim)"> / ${max}</small></div>
    <div class="rows">${rounds.map((r, i) => `<div><span>${i + 1}. ${esc(r.answer.name)}</span><span>${results[i]} pts</span></div>`).join('')}</div>
    <button id="share">Copy result</button> <button class="primary" id="again">Play again</button></div>`;
  $('#again').onclick = startGame;
  $('#share').onclick = async e => {
    try { await navigator.clipboard.writeText(`Who said it? ${sc}/${max}\n${squares}`); e.target.textContent = 'Copied!'; }
    catch { e.target.textContent = 'Copy failed'; }
  };
}

init();
