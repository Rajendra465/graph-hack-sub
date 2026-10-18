// The start screen, the four scenarios, the custom-game drawer, the tour steps, tooltips, deep links and start-up.
(function () {
  'use strict';
  const CB = window.CB;
  const { $, num, esc, anim } = CB;
  const SEEN = 'codebook.seen-start';
  const BOARD = 6030;  // the benchmark board every scripted scenario uses
  const BETWEEN_GAMES_MS = 1600;
  const TIP_WIDTH = 340;

  // ---------- overlays ----------
  function openScenarios() {
    $('scenarios').classList.remove('hidden');
    anim((g) => g.from('#scenarios .scenario', { y: 30, opacity: 0, duration: 0.45, stagger: 0.07, ease: 'power3.out' }));
  }
  function closeScenarios() {
    $('scenarios').classList.add('hidden');
    try { localStorage.setItem(SEEN, '1'); } catch (e) { /* storage blocked: the start screen shows again next visit */ }
  }
  function openDrawer() {
    $('custom').classList.add('open');
    $('custom').setAttribute('aria-hidden', 'false');
  }
  function closeDrawer() {
    $('custom').classList.remove('open');
    $('custom').setAttribute('aria-hidden', 'true');
  }
  CB.closeDrawer = closeDrawer;

  function setControls(v) {
    if (v.partner) $('partner').value = v.partner;
    if (v.memory) $('memory').value = v.memory;
    if (v.seed !== undefined) $('seed').value = v.seed;
    if (v.giver) $('giver').value = v.giver;
    $('learn').checked = Boolean(v.learn);
    $('replay').checked = Boolean(v.replay);
  }

  // ---------- scenarios ----------
  let next = null;   // the second step of a two-game scenario
  let current = 0;   // bumped by every scenario or custom game, so a stale step never fires
  CB.on('end', (j) => {
    const step = next;
    next = null;
    if (step) step(j);
  });
  function cancelSteps() {
    next = null;
    current += 1;
  }

  async function run(body) {
    cancelSteps();
    const mine = current;
    try {
      const j = await CB.startGame(body);
      return mine === current ? j : null;  // something else started while this one was starting
    } catch (e) {
      if (mine === current) CB.showError(e.message);
      return null;
    }
  }

  function showResult(rows) {
    $('result').innerHTML = rows.map(([label, text, status]) => `<div class="res ${esc(status)}"><span>${esc(label)}</span><b>${esc(text)}</b></div>`).join('');
    $('result').classList.remove('hidden');
    anim((g) => g.from('#result .res', { y: 20, opacity: 0, duration: 0.4, stagger: 0.12, ease: 'back.out(2)' }));
    CB.say('Same board, same bot, same code. Only the memory changed.', 'good');
  }

  const W2V = { partner: 'w2v', seed: BOARD, clue_giver: 'codebook', learn: false, replay: false, delay: 0.55 };
  const SCENARIOS = {
    async memories() {
      setControls({ partner: 'w2v', memory: 'everyone', seed: BOARD, giver: 'codebook' });
      if (!(await run({ ...W2V, memory: 'everyone' }))) return;
      const mine = current;
      CB.say('First, everyone\'s memory: the shared graph every partner starts from.');
      next = (a) => {
        const lineA = $('status').textContent;
        setTimeout(async () => {
          if (mine !== current) return;  // something else started meanwhile
          setControls({ partner: 'w2v', memory: 'own', seed: BOARD, giver: 'codebook' });
          if (!(await run({ ...W2V, memory: 'own' }))) return;
          CB.say('Same board, same bot. Now its own memory: the copy that learned how it thinks.');
          next = (b) => showResult([['Everyone\'s memory', lineA, a.status], ['Its own memory', $('status').textContent, b.status]]);
        }, BETWEEN_GAMES_MS);
      };
    },
    async handover() {
      setControls({ partner: 'glove', memory: 'own', seed: BOARD, giver: 'claude-sonnet', replay: true });
      const started = await run({ partner: 'glove', memory: 'own', seed: BOARD, clue_giver: 'claude-sonnet', learn: false, replay: true, delay: 0.8 });
      if (started) CB.say('Claude Sonnet gives the clues, choosing from the GloVe bot\'s memory through Codebook\'s tools. Its clues come from the benchmark log; the game runs live.');
    },
    async play() {
      const seed = 7000 + Math.floor(Math.random() * 1000);
      setControls({ partner: 'you', memory: 'own', seed, giver: 'codebook', learn: true });
      await run({ partner: 'you', memory: 'own', seed, clue_giver: 'codebook', learn: true, replay: false, delay: 0.3 });
    },
    async explore() {
      cancelSteps();
      setControls({ partner: 'w2v', memory: 'own', seed: BOARD, giver: 'codebook' });
      CB.resetGameView();
      CB.game = null;
      CB.humanGame = false;
      $('cmpmems').value = 'everyone,w2v,glove';
      CB.showTab('compare');
      CB.say('Exploring the word2vec bot\'s memory around board 6030: the clue it would give, and the links behind it. Drag the graph to turn it.');
      await CB.compare();
      try {
        const graph = await CB.api(`/api/graph?seed=${BOARD}&memory=w2v`);
        $('clueword').textContent = graph.clue.toUpperCase();
        $('cluemeta').textContent = 'the clue this memory would give first';
        window.CodebookGraph.show(graph, []);
        $('graphinfo').textContent = `${graph.nodes.length} words · ${graph.links.length} links · ${graph.read_key}`;
      } catch (e) {
        window.CodebookGraph.clear(`Graph unavailable: ${e.message}`);
      }
      CB.showMemory('w2v');
    },
  };

  // ---------- the tour ----------
  const TOUR = [
    { el: '#openScenarios', title: 'Start here', text: 'Four one-click scenarios. Each one is a real game on the real FalkorDB memory.' },
    { el: '#board', title: 'The board', text: 'Codenames: 25 words. The coloured bars are the key only the clue-giver sees: blue our team, orange the other team, grey neutral, red the bomb.' },
    { el: () => document.querySelector('.clue'), title: 'The clue', text: 'Codebook gives one word and a number. It chose this clue by reading this partner\'s own memory.' },
    { el: '#narration', title: 'What just happened', text: 'Every event in plain words: the clue, each guess, and every clue the code blocked because it could lead to the bomb.' },
    { el: '#graph3d', title: 'The memory, live', text: 'The partner\'s memory around the clue, straight from FalkorDB: direct links, backwards links, two-step chains, and in red any path to the bomb. Drag to turn it.' },
    { el: '#tabscard', title: 'Every query', text: 'Live Cypher lists every query FalkorDB ran for this game. Partner memory shows what Codebook learned. Compare shows the clue each memory would give.' },
    { el: '#openCustom', title: 'Your own game', text: 'Any partner, any memory, any board. The same board seed always deals the same board.' },
  ];
  async function startTour() {
    closeScenarios();
    if (!CB.game && !$('board').children.length) await SCENARIOS.explore();  // give the tour something to point at
    window.CodebookTour.start(TOUR);
  }

  // ---------- small helpers ----------
  function showNode(id, links) {
    $('nodecard').innerHTML = `<b>${esc(id.toUpperCase())}</b><span class="muted"> · ${links.length} link${links.length === 1 ? '' : 's'} here</span>`
      + `<ul>${links.slice(0, 8).map((l) => `<li>${esc(l.from)} → ${esc(l.to)} <span class="k ${esc(l.kind)}">${esc(l.kind)}</span> ${num(l.s).toFixed(3)}</li>`).join('')}</ul>`;
    $('nodecard').classList.remove('hidden');
  }

  function tooltips() {
    const tip = $('tooltip');
    document.querySelectorAll('[data-tip]').forEach((el) => {
      const show = () => {
        tip.textContent = el.dataset.tip;
        tip.classList.remove('hidden');
        const r = el.getBoundingClientRect();
        tip.style.left = `${Math.max(16, Math.min(window.innerWidth - TIP_WIDTH, r.left))}px`;
        tip.style.top = `${r.bottom + 8}px`;
      };
      const hide = () => tip.classList.add('hidden');
      el.addEventListener('mouseenter', show);
      el.addEventListener('focus', show);
      el.addEventListener('mouseleave', hide);
      el.addEventListener('blur', hide);
    });
  }

  // Deep links: ?game=<id> replays a game's events, ?tab=memory&mem=w2v, ?tab=compare&seed=6042&memories=a,b
  async function fromUrl(q) {
    if (q.get('seed')) $('seed').value = q.get('seed');
    if (q.get('memories')) $('cmpmems').value = q.get('memories');
    if (q.get('game')) {
      CB.game = q.get('game');
      CB.since = 0;
      CB.over = false;
      const j = await CB.api(`/api/game/${encodeURIComponent(CB.game)}?since=0`);
      $('partner').value = j.partner;
      $('seed').value = j.seed;
      CB.humanGame = j.partner === 'you';
      CB.renderBoard(j.words, j.key, CB.humanGame);
      $('gameinfo').innerHTML = CB.gameInfo(j.seed, j.partner, j.read_key, j.benchmark_game, j.replay);
      for (const ev of j.events) {
        CB.since = ev.i + 1;
        CB.handle(ev);
      }
      if (j.status !== 'running') CB.finish(j);
      else CB.timer = setInterval(CB.poll, CB.POLL_MS);
    }
    if (q.get('mem')) await CB.showMemory(q.get('mem'));
    if (q.get('tab') === 'compare') await CB.compare();
    if (q.get('tab')) CB.showTab(q.get('tab'));
  }

  function wire() {
    document.querySelectorAll('.scenario').forEach((b) => b.addEventListener('click', () => {
      closeScenarios();
      const scenario = SCENARIOS[b.dataset.scenario];
      if (scenario) scenario();
    }));
    $('openScenarios').addEventListener('click', openScenarios);
    $('closeScenarios').addEventListener('click', () => {
      closeScenarios();
      if (!CB.game) CB.compare();
    });
    $('openCustom').addEventListener('click', openDrawer);
    $('closeCustom').addEventListener('click', closeDrawer);
    $('start').addEventListener('click', cancelSteps);  // a custom game replaces any scenario in progress
    $('openTour').addEventListener('click', startTour);
    $('tourbtn').addEventListener('click', startTour);
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (!$('scenarios').classList.contains('hidden')) closeScenarios();
      closeDrawer();
    });
    tooltips();
  }

  async function init() {
    const q = new URLSearchParams(window.location.search);
    window.CodebookGraph.mount($('graph3d'), showNode);
    CB.showTab('queries');
    wire();
    try {
      await CB.loadPartners();
      await CB.allQueries();
      await fromUrl(q);
    } catch (e) {
      $('gameinfo').textContent = `Server error: ${e.message}`;
    }
    let seen = false;
    try { seen = localStorage.getItem(SEEN) === '1'; } catch (e) { seen = false; }
    if (!seen && [...q.keys()].length === 0) openScenarios();
  }

  init();
})();
