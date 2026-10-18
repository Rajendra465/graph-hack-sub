// The tabs: Live Cypher, Partner memory, Compare memories, All queries.
(function () {
  'use strict';
  const CB = window.CB;
  const { $, num, esc, anim } = CB;
  const DEFAULT_STYLE = { direct: 3.0, reverse: 1.5, chain: 1.5, shared: 1.5 };
  const MAX_QUERIES = 300;
  const SHOWN_QUERIES = 60;
  const EXPLAIN = {
    queries: 'Every Cypher query FalkorDB ran for this game, newest first: the memory (key) it read, rows and time.',
    memory: 'What Codebook has learned about this partner: how it links words, against everyone\'s default, and the links it reweighted.',
    compare: 'The clue each memory would give first on this board. Different memories, different clues.',
    all: 'Every query Codebook can run. All of them are Cypher on FalkorDB.',
  };

  let painting = false;
  let slideFirst = false;
  CB.addQuery = function addQuery(q) {
    CB.queries.unshift(q);
    if (CB.queries.length > MAX_QUERIES) CB.queries.length = MAX_QUERIES;
    slideFirst = true;
    if (painting) return;
    painting = true;
    requestAnimationFrame(() => {  // one paint per burst of queries
      painting = false;
      const total = CB.queries.reduce((s, x) => s + num(x.ms), 0);
      $('qsum').textContent = `${CB.queries.length} queries this game · ${total.toFixed(0)} ms in FalkorDB`;
      $('qlist').innerHTML = CB.queries.slice(0, SHOWN_QUERIES).map((x) => `<details class="q"><summary><span class="n">${esc(x.name)}</span><span class="k">${esc(x.key)} · ${x.ro ? 'GRAPH.RO_QUERY' : 'GRAPH.QUERY'}</span><span>${num(x.rows)} rows</span><span>${num(x.ms)} ms</span></summary><pre>${esc(x.cypher)}</pre>${x.params && !CB.hideKey() ? `<pre class="p">${esc(x.params)}</pre>` : ''}</details>`).join('');
      if (slideFirst) anim((g) => g.from('#qlist .q:first-child', { x: 24, opacity: 0, duration: 0.3 }));
      slideFirst = false;
    });
  };

  CB.showMemory = async function showMemory(pid) {
    if (!pid || pid === 'everyone') {
      $('tab-memory').innerHTML = '<div class="muted">Everyone\'s memory is shared and read-only: every partner starts from a copy of it.</div>';
      return;
    }
    try {
      const m = await CB.api(`/api/memory/${encodeURIComponent(pid)}`);
      const max = Math.max(6, ...Object.values(m.style).map(Math.abs));
      const bars = ['direct', 'reverse', 'chain', 'shared'].map((k) => `<span>${k}</span><div class="bar"><i style="width:${Math.max(0, num(m.style[k])) / max * 100}%"></i><s style="left:${DEFAULT_STYLE[k] / max * 100}%"></s></div><span class="m">${num(m.style[k]).toFixed(2)}</span>`).join('');
      $('tab-memory').innerHTML = `
        <div class="stats"><div class="stat"><b>${num(m.games)}</b><span>games</span></div><div class="stat"><b>${num(m.turns)}</b><span>clues</span></div>
        <div class="stat"><b>${num(m.learned_links)}</b><span>links reweighted</span></div><div class="stat"><b>${m.mb == null ? '–' : num(m.mb)}</b><span>MB in FalkorDB</span></div></div>
        <div class="muted">${esc(m.key)} · how this partner links words (orange tick = everyone's default)</div>
        <div class="bars">${bars}</div>
        <table><tr><th>Clue → word</th><th>everyone</th><th>this partner</th><th>hits</th><th>misses</th></tr>
        ${m.links.slice(0, 18).map((l) => `<tr><td>${esc(l.clue)} → ${esc(l.word)}${l.learned ? ' <span class="chip team">new</span>' : ''}</td><td class="m">${num(l.p).toFixed(3)}</td><td class="m">${num(l.pp).toFixed(3)}</td><td>${num(l.hits)}</td><td>${num(l.misses)}</td></tr>`).join('')}</table>
        <p class="muted">Words this partner leans towards: ${m.bias.filter((b) => b.bias > 0).slice(0, 12).map((b) => esc(b.word)).join(', ') || 'none yet'}</p>`;
      anim((g) => g.from('#tab-memory .bar i', { width: 0, duration: 0.8, stagger: 0.08, ease: 'power2.out' }));
    } catch (e) {
      $('tab-memory').innerHTML = `<div class="muted">${esc(e.message)}</div>`;
    }
  };

  CB.compare = async function compare() {
    if (CB.hideKey()) {
      $('cmp').innerHTML = '<div class="muted">Hidden while you play: each memory\'s clues would show which words are yours. It comes back when the game ends.</div>';
      return;
    }
    const typed = ($('cmpmems').value || '').split(',').map((x) => x.trim()).filter(Boolean);
    const mems = typed.length ? typed : ['everyone', ...CB.partnersInfo.map((p) => p.id).filter((id) => !/-at\d+$/.test(id))].slice(0, 4);
    try {
      const j = await CB.api(`/api/suggest?seed=${num(+$('seed').value)}&memories=${mems.map(encodeURIComponent).join(',')}`);
      if (!CB.game && $('partner').value !== 'you') {  // no game on screen: show the board being compared
        const keyName = { team: 'Red', opponent: 'Blue', neutral: 'Civilian', assassin: 'Assassin' };
        CB.renderBoard(j.board.map((w) => w.toLowerCase()), j.roles.map((r) => keyName[r]), false);
        $('gameinfo').innerHTML = `Board ${num(+$('seed').value)} · the key as the clue-giver sees it`;
      }
      $('cmp').innerHTML = `<div class="cols">${Object.entries(j.by_memory).map(([mem, opts]) => `<div class="cmp-col"><h4>${esc(mem)}</h4>${opts.slice(0, 3).map((o, i) => `<div class="opt${i === 0 ? ' top' : ''}"><b>${esc(o.clue.toUpperCase())} ${num(o.count)}</b><br><span class="muted">${esc(o.targets.join(', '))} · exp ${num(o.expected_hits)}</span></div>`).join('')}</div>`).join('')}</div>`;
      anim((g) => g.from('#cmp .cmp-col', { y: 16, opacity: 0, duration: 0.35, stagger: 0.08 }));
    } catch (e) {
      $('cmp').innerHTML = `<div class="muted">${esc(e.message)}</div>`;
    }
  };

  CB.allQueries = async function allQueries() {
    const j = await CB.api('/api/cypher');
    $('tab-all').innerHTML = Object.entries(j).map(([n, t]) => `<details class="q"><summary><span class="n">${esc(n)}</span></summary><pre>${esc(t)}</pre></details>`).join('');
  };

  CB.showTab = function showTab(name) {
    document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
    ['queries', 'memory', 'compare', 'all'].forEach((t) => $(`tab-${t}`).classList.toggle('hidden', t !== name));
    $('tabexplain').textContent = EXPLAIN[name] || '';
  };

  document.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => CB.showTab(b.dataset.tab)));
  $('cmpgo').addEventListener('click', CB.compare);
  CB.on('start', (body) => {
    if (body.partner !== 'you') CB.showMemory(body.memory === 'own' ? body.partner : body.memory);
    CB.compare();
  });
  CB.on('end', () => {
    const p = $('partner').value;
    if (p !== 'you') CB.showMemory($('memory').value === 'own' ? p : $('memory').value);
    if (CB.humanGame) CB.compare();  // hidden while the human played
    CB.loadPartners().catch(() => {});  // a learning game may have added a memory; the page keeps working without it
  });
})();
