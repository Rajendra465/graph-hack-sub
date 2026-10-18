// Codebook live view: shared state, the API, the game loop, the board and the narration line.
// Exposes window.CB, used by panels.js and scenarios.js. Element ids are a contract with the capture scripts.
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const num = (x) => { const n = Number(x); return Number.isFinite(n) ? n : 0; };
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const anim = (fn) => { if (window.gsap && !reduced) fn(window.gsap); };
  const pct = (p) => `${(num(p) * 100).toFixed(1)}%`;
  const ROLE = { Red: 'team', Blue: 'opponent', Civilian: 'neutral', Assassin: 'assassin' };
  const POLL_MS = 400;
  const MAX_POLL_FAILURES = 5;
  const MAX_BLOCKS_SHOWN = 40;
  const TYPE_MS = 16;

  const CB = (window.CB = {
    $, num, esc, anim, reduced, POLL_MS,
    game: null, since: 0, timer: null, polling: false, failures: 0, humanGame: false, over: false,
    partnersInfo: [], queries: [], roles: {},
    hooks: { start: [], end: [] },
  });
  CB.on = (name, fn) => CB.hooks[name].push(fn);
  CB.hideKey = () => CB.humanGame && !CB.over;  // a human guesser must not see the key until the game ends
  const emit = (name, ...args) => CB.hooks[name].forEach((fn) => {
    try { fn(...args); } catch (e) { console.error(e); }
  });

  async function api(path, opts) {
    const r = await fetch(path, opts);
    let j = {};
    try { j = await r.json(); } catch (e) { j = {}; }
    if (!r.ok) throw new Error(j.error || r.statusText || `HTTP ${r.status}`);
    return j;
  }
  CB.api = api;
  CB.post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  // ---------- narration: every event in plain words ----------
  let typing = 0;
  CB.say = function say(text, tone) {
    const el = $('narration');
    el.className = `narration ${tone || ''}`;
    clearInterval(typing);
    if (reduced || !text) {
      el.textContent = text || '';
      return;
    }
    let i = 0;
    el.textContent = '';
    typing = setInterval(() => {
      i += 3;
      el.textContent = text.slice(0, i);
      if (i >= text.length) clearInterval(typing);
    }, TYPE_MS);
  };

  CB.loadPartners = async function loadPartners() {
    const j = await api('/api/partners');
    CB.partnersInfo = j.partners;
    const keepPartner = $('partner').value;
    const keepMemory = $('memory').value;
    $('partner').innerHTML = j.available.map((p) => `<option value="${esc(p)}">${p === 'you' ? 'you (play as guesser)' : esc(p)}</option>`).join('');
    const mem = $('memory');
    mem.innerHTML = '<option value="own">their own</option><option value="everyone">everyone\'s</option>'
      + j.partners.map((p) => `<option value="${esc(p.id)}">${esc(p.id)}'s (swap)</option>`).join('');
    if (keepPartner && j.available.includes(keepPartner)) $('partner').value = keepPartner;
    if (keepMemory && [...mem.options].some((o) => o.value === keepMemory)) mem.value = keepMemory;
  };

  // ---------- the board ----------
  CB.renderBoard = function renderBoard(words, key, human) {
    CB.roles = {};
    $('board').innerHTML = words.map((w, i) => {
      const role = ROLE[key[i]] || 'neutral';
      CB.roles[w] = role;
      return `<div class="tile ${human ? 'clickable' : `keyed ${role}`}" data-w="${esc(w)}"><span>${esc(w.toUpperCase())}</span></div>`;
    }).join('');
    document.querySelectorAll('.tile.clickable').forEach((t) => { t.onclick = () => CB.guess(t.dataset.w); });
    anim((g) => g.from('#board .tile', { y: 14, opacity: 0, duration: 0.35, stagger: 0.015, ease: 'power2.out' }));
  };

  function flip(tile, role) {
    const done = () => {
      tile.classList.remove('target', 'clickable', 'keyed');
      tile.classList.add(`r-${role}`);
      tile.onclick = null;
    };
    if (!window.gsap || reduced) {
      done();
      return;
    }
    window.gsap.timeline()
      .to(tile, { rotateY: 90, duration: 0.18, ease: 'power2.in', onComplete: done })
      .to(tile, { rotateY: 0, duration: 0.26, ease: 'back.out(2)' });
  }

  CB.gameInfo = (seed, partner, readKey, bench, replay) => `Board ${num(seed)} · partner <b>${esc(partner)}</b> · memory <b>${esc(readKey)}</b>`
    + (bench ? ` · same set-up as benchmark game <b>${esc(bench)}</b>${replay ? " (the AI's clues come from the log)" : ''}` : '');

  CB.endStatus = function endStatus(j) {  // plain text: callers set textContent
    if (j.status === 'error') return j.error;
    const s = j.status === 'won' ? `Won in ${num(j.result.turns)} turns` : `Lost (${j.result.assassin ? 'bomb' : 'turn limit or opponent'})`;
    return s + (j.matches_log === true ? ' · matches the benchmark log' : j.matches_log === false ? ' · differs from the benchmark log' : '');
  };

  CB.resetGameView = function resetGameView() {
    clearInterval(CB.timer);
    $('blocks').innerHTML = '';
    $('log').innerHTML = '';
    $('qlist').innerHTML = '';
    CB.queries = [];
    $('clueword').innerHTML = '&nbsp;';
    $('cluemeta').textContent = '';
    $('status').textContent = '';
    $('status').className = 'status';
    $('yourturn').classList.add('hidden');
    $('result').classList.add('hidden');
    $('nodecard').classList.add('hidden');
    $('graphinfo').textContent = 'from FalkorDB';
  };

  CB.showError = function showError(message) {
    $('status').textContent = message;
    $('status').className = 'status error';
    CB.say(message, 'bad');
  };

  // ---------- a game ----------
  let startSeq = 0;
  CB.startGame = async function startGame(body) {
    const seq = ++startSeq;
    CB.resetGameView();
    CB.game = null;
    const j = await CB.post('/api/game', body);
    if (seq !== startSeq) return null;  // a newer start replaced this one while its request was in flight
    CB.game = j.game;
    CB.since = 0;
    CB.failures = 0;
    CB.humanGame = body.partner === 'you';
    CB.over = false;
    CB.renderBoard(j.words, j.key, CB.humanGame);
    $('gameinfo').innerHTML = CB.gameInfo(body.seed, body.partner, j.read_key, j.benchmark_game, j.replay);
    clearInterval(CB.timer);
    CB.timer = setInterval(CB.poll, POLL_MS);
    CB.say(CB.humanGame ? 'Codebook is choosing your first clue from your own memory…'
      : 'Codebook is reading this partner\'s memory in FalkorDB: four kinds of links for every candidate clue…');
    window.CodebookGraph.clear(CB.humanGame ? 'The memory graph appears when the game ends: it would show which card is which.'
      : 'Waiting for the first clue…');
    emit('start', body, j);
    return j;
  };

  async function startFromControls() {
    const body = {
      partner: $('partner').value, memory: $('memory').value, seed: +$('seed').value, clue_giver: $('giver').value,
      learn: $('learn').checked, replay: $('replay').checked, delay: +$('delay').value,
    };
    $('start').disabled = true;  // one start at a time: a double click must not start two games
    try {
      if ((await CB.startGame(body)) && CB.closeDrawer) CB.closeDrawer();
    } catch (e) {
      CB.showError(e.message);
    } finally {
      $('start').disabled = false;
    }
  }

  CB.poll = async function poll() {
    if (!CB.game || CB.polling) return;  // one poll at a time: a slow server must not deliver events twice
    const g = CB.game;
    CB.polling = true;
    try {
      const j = await api(`/api/game/${encodeURIComponent(g)}?since=${CB.since}`);
      if (g !== CB.game) return;
      CB.failures = 0;
      for (const ev of j.events) {
        if (ev.i < CB.since) continue;
        CB.since = ev.i + 1;
        CB.handle(ev);
      }
      if (j.status !== 'running') CB.finish(j);
    } catch (e) {
      CB.failures += 1;
      if (g === CB.game && CB.failures >= MAX_POLL_FAILURES) {
        clearInterval(CB.timer);
        CB.showError(`Lost contact with the live view server: ${e.message}`);
      }
    } finally {
      CB.polling = false;
    }
  };

  CB.finish = function finish(j) {
    if (CB.over) return;  // once per game, however many polls see the end
    CB.over = true;
    clearInterval(CB.timer);
    const text = CB.endStatus(j);
    $('status').textContent = text;
    $('status').className = `status ${j.status}`;
    $('yourturn').classList.add('hidden');
    CB.say(`${text}.`, j.status === 'won' ? 'good' : 'bad');
    anim((g) => g.fromTo('#status', { scale: 1.4, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.5, ease: 'back.out(2.5)' }));
    if (CB.humanGame) CB.loadGraph(null, []);  // safe now: the game is over
    emit('end', j);
  };

  // ---------- events ----------
  let graphSeq = 0;
  CB.loadGraph = async function loadGraph(turn, aim) {
    const g = CB.game;
    const seq = ++graphSeq;
    const query = turn == null ? '' : `?turn=${num(turn)}`;
    try {
      const graph = await api(`/api/game/${encodeURIComponent(g)}/graph${query}`);
      if (g !== CB.game || seq !== graphSeq) return;
      window.CodebookGraph.show(graph, aim);
      $('graphinfo').textContent = `${graph.nodes.length} words · ${graph.links.length} links · ${graph.read_key}`;
    } catch (e) {
      if (g === CB.game && seq === graphSeq) window.CodebookGraph.clear(`Graph unavailable: ${e.message}`);
    }
  };

  function onClue(ev) {
    const o = ev.option;
    // A human guesser must not see which words the clue aims at.
    document.querySelectorAll('.tile').forEach((t) => t.classList.toggle('target', !CB.humanGame && o.targets.includes(t.dataset.w)));
    $('clueword').textContent = `${o.clue.toUpperCase()} · ${num(o.count)}`;
    $('cluemeta').innerHTML = CB.humanGame ? `${num(o.count)} word${o.count === 1 ? '' : 's'} · by ${esc(ev.proposed_by)}`
      : `aiming at <b>${esc(o.targets.join(', ').toUpperCase())}</b> · expected ${num(o.expected_hits)} right · bomb risk ${pct(o.p_assassin)} · by ${esc(ev.proposed_by)}${ev.forced ? ' · <b>forced (all blocked)</b>' : ''}`;
    const row = document.createElement('div');
    row.className = 'turn';
    row.id = `turn-${num(ev.turn)}`;
    row.innerHTML = `<span class="c">${num(ev.turn)}. ${esc(o.clue.toUpperCase())} ${num(o.count)}</span>`;
    $('log').prepend(row);
    anim((g) => g.fromTo('#clueword', { scale: 1.5, opacity: 0, filter: 'blur(8px)' }, { scale: 1, opacity: 1, filter: 'blur(0px)', duration: 0.45, ease: 'back.out(2)' }));
    const who = ev.proposed_by === 'codebook' ? 'Codebook' : ev.proposed_by;
    const word = `${o.clue.toUpperCase()} · ${num(o.count)}`;
    if (CB.humanGame) {
      CB.say(`${who} gives ${word}. Which words does it point to?`);
    } else {
      CB.say(`${who} gives ${word}, aiming at ${o.targets.join(', ').toUpperCase()}. Bomb risk ${pct(o.p_assassin)}.`);
      CB.loadGraph(ev.turn, o.targets);
    }
  }

  function onGuess(ev) {
    const tile = document.querySelector(`.tile[data-w="${CSS.escape(ev.word)}"]`);
    if (tile) flip(tile, ev.role);
    const row = $('log').firstElementChild;
    if (row) row.insertAdjacentHTML('beforeend', `<span class="chip ${esc(ev.role)}">${esc(ev.word.toUpperCase())}</span>`);
    window.CodebookGraph.reveal(ev.word);
    const w = ev.word.toUpperCase();
    const line = {
      team: `${w} ✓ the partner got it.`,
      opponent: `${w} ✗ the other team's card. The turn ends.`,
      neutral: `${w}: a neutral card. The turn ends.`,
      assassin: `${w} ✗ the bomb. Game over.`,
    }[ev.role] || w;
    CB.say(line, ev.role === 'team' ? 'good' : ev.role === 'assassin' ? 'bad' : '');
    if (ev.role === 'assassin') anim((g) => g.fromTo('#gamecard', { x: -12 }, { x: 0, duration: 0.6, ease: 'elastic.out(1, 0.3)' }));
  }

  function onBlock(ev) {
    const path = !CB.hideKey() && ev.path && ev.path.length ? ev.path : null;  // a path ends on the bomb
    const clue = String(ev.clue).toUpperCase();
    $('blocks').insertAdjacentHTML('afterbegin', `<div class="block">Blocked <b>${esc(clue)}</b>${ev.proposed_by !== 'codebook' ? ` (proposed by ${esc(ev.proposed_by)})` : ''}: ${path ? `<b>${esc(path.join(' → '))}</b> reaches the bomb, strength ${num(ev.strength)}` : `the model gives the bomb ${pct(ev.p_assassin)}`}</div>`);
    while ($('blocks').children.length > MAX_BLOCKS_SHOWN) $('blocks').lastElementChild.remove();
    CB.say(`Blocked ${clue}: a ${pct(ev.p_assassin)} chance it leads to the bomb${path ? ` (${path.join(' → ')})` : ''}.`, 'bad');
  }

  CB.handle = function handle(ev) {
    switch (ev.kind) {
      case 'query': if (CB.addQuery) CB.addQuery(ev); break;
      case 'clue': onClue(ev); break;
      case 'guess': onGuess(ev); break;
      case 'block': onBlock(ev); break;
      case 'your_turn':
        $('yourturn').classList.remove('hidden');
        CB.say('Your turn: click the words you think the clue points to, then End turn.');
        break;
      case 'refit':
        $('log').insertAdjacentHTML('afterbegin', `<div class="turn muted">Memory updated: style ${esc(JSON.stringify(ev.style))}, ${num(ev.biased_words)} favourite words</div>`);
        CB.say('The partner\'s memory was refit from this game: its style weights changed.', 'good');
        break;
      case 'proposal_rejected': CB.say(`Codebook's check refused ${String(ev.clue).toUpperCase()}: ${ev.reason}.`, 'bad'); break;
      case 'fallback': CB.say('No usable AI clue this turn, so Codebook gives its own top suggestion.'); break;
      case 'error': CB.showError(ev.error); break;
      default: break;
    }
  };

  CB.guess = async function guess(word) {
    if (!CB.game) return;
    $('yourturn').classList.add('hidden');
    try {
      await CB.post(`/api/game/${encodeURIComponent(CB.game)}/guess`, { word });
    } catch (e) {
      CB.showError(e.message);
    }
  };

  $('start').addEventListener('click', startFromControls);
  $('endturn').addEventListener('click', () => CB.guess(null));
})();
