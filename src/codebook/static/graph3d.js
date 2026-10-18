// The partner's memory around the current clue, in 3D (3d-force-graph on three.js), with a 2D fallback.
// window.CodebookGraph = { mount(el, onPick), show(graph, aim), reveal(word), clear(message), stats() }
(function () {
  'use strict';
  const ROLE = { team: '#7EA2F2', opponent: '#F28C38', neutral: '#8A91AB', assassin: '#FF4D5E' };
  const ROLE_DIM = { team: '#3E5590', opponent: '#8A5426', neutral: '#4A5068', assassin: '#A3303C' };
  const LINK = { direct: '#7EA2F2', reverse: '#9DD3FF', chain: '#D7A6FF', bomb: '#FF4D5E' };
  const FALLBACK_ROWS = 14;
  const FLIGHT_MS = 1200;
  const FIT_PADDING = 40;
  const LINK_DISTANCE = 60;
  const CHARGE = -140;
  const LAYOUT_MS = 2500;  // the layout stops (and the camera frames the clue) after this, however slow the GPU
  const LABELLED_VIAS = 10;  // the strongest via words get labels; the rest show on click
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const idOf = (end) => (end && typeof end === 'object' ? end.id : end);

  let host = null;
  let fg = null;
  let labelLayer = null;
  let labels = new Map();
  let data = { nodes: [], links: [] };
  let mode = 'empty';
  let reason = '';
  let clue = null;
  let onPick = null;
  let flyPending = false;  // fly to the clue once per new graph, not after every drag

  function webgl() {
    try {
      const c = document.createElement('canvas');
      return Boolean(c.getContext('webgl2') || c.getContext('webgl'));
    } catch (e) {
      return false;
    }
  }

  function mount(el, pick) {
    host = el;
    onPick = pick || null;
    if (typeof window.ForceGraph3D !== 'function') reason = 'the 3D library did not load (offline?)';
    else if (!webgl()) reason = 'this browser has no WebGL';
    mode = reason ? 'fallback' : 'empty';
  }

  function nodeColor(n) {
    if (n.kind === 'clue') return '#F2B84B';
    if (n.kind === 'via') return '#C9CEDD';
    return (n.revealed ? ROLE : ROLE_DIM)[n.role] || '#8A91AB';
  }

  function linksOf(id) {
    return data.links
      .filter((l) => idOf(l.source) === id || idOf(l.target) === id)
      .map((l) => ({ from: idOf(l.source), to: idOf(l.target), kind: l.kind, s: l.s }))
      .sort((a, b) => b.s - a.s);
  }

  function fitToClue() {  // frame the clue, its via words, the words it aims at and the path to the bomb
    if (!fg) return;
    const focus = new Set([clue]);
    for (const n of data.nodes) if (n.kind === 'via' || n.aim) focus.add(n.id);
    for (const l of data.links) {
      if (l.kind !== 'bomb') continue;
      focus.add(idOf(l.source));
      focus.add(idOf(l.target));
    }
    const filter = focus.size >= 3 ? (n) => focus.has(n.id) : () => true;
    fg.zoomToFit(reduced ? 0 : FLIGHT_MS, FIT_PADDING, filter);
  }

  function followLabels() {  // HTML labels follow their nodes every frame
    for (const n of data.nodes) {
      const el = labels.get(n.id);
      if (!el || n.x === undefined) continue;
      const p = fg.graph2ScreenCoords(n.x, n.y, n.z);
      el.style.transform = `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px)`;
    }
    requestAnimationFrame(followLabels);
  }

  function ensureGraph() {
    if (fg) return fg;
    host.textContent = '';
    fg = new window.ForceGraph3D(host, { controlType: 'orbit' })
      .backgroundColor('#0A0F24')
      .showNavInfo(false)
      .width(host.clientWidth)
      .height(host.clientHeight)
      .nodeLabel(() => '')
      .nodeVal((n) => (n.kind === 'clue' ? 22 : n.kind === 'board' ? (n.aim ? 10 : 6) : 2.5))
      .nodeColor(nodeColor)
      .nodeOpacity(0.95)
      .nodeResolution(16)
      .linkColor((l) => LINK[l.kind] || '#8A91AB')
      .linkOpacity(0.55)
      .linkWidth((l) => (l.kind === 'bomb' ? 2.6 : l.kind === 'chain' ? 0.6 : 1.4))
      .linkDirectionalParticles((l) => (reduced ? 0 : l.kind === 'bomb' ? 4 : l.kind === 'chain' ? 1 : 2))
      .linkDirectionalParticleWidth((l) => (l.kind === 'bomb' ? 3 : 1.6))
      .linkDirectionalParticleSpeed((l) => 0.004 + Math.min(0.01, (l.s || 0) * 0.05))
      .linkDirectionalParticleColor((l) => LINK[l.kind] || '#FFFFFF')
      .cooldownTicks(120)
      .cooldownTime(LAYOUT_MS)
      .onNodeClick((n) => onPick && onPick(n.id, linksOf(n.id)))
      .onEngineStop(() => {
        if (!flyPending) return;
        flyPending = false;
        fitToClue();
      });
    fg.d3Force('charge').strength(CHARGE);
    fg.d3Force('link').distance(LINK_DISTANCE);
    labelLayer = document.createElement('div');
    labelLayer.className = 'graph-labels';
    host.appendChild(labelLayer);
    new ResizeObserver(() => fg && fg.width(host.clientWidth).height(host.clientHeight)).observe(host);
    requestAnimationFrame(followLabels);
    return fg;
  }

  function labelledVias() {
    const strongest = new Map();
    const onBombPath = new Set();
    for (const l of data.links) {
      for (const end of [idOf(l.source), idOf(l.target)]) {
        strongest.set(end, Math.max(strongest.get(end) || 0, l.s));
        if (l.kind === 'bomb') onBombPath.add(end);
      }
    }
    const top = data.nodes.filter((n) => n.kind === 'via')
      .sort((a, b) => (strongest.get(b.id) || 0) - (strongest.get(a.id) || 0))
      .slice(0, LABELLED_VIAS).map((n) => n.id);
    return new Set([...top, ...onBombPath]);
  }

  function makeLabels() {
    labelLayer.textContent = '';
    labels = new Map();
    const vias = labelledVias();
    for (const n of data.nodes) {
      if (n.kind === 'via' && !vias.has(n.id)) continue;
      const el = document.createElement('span');
      el.className = ['glabel', n.kind, n.role || '', n.revealed ? 'revealed' : '', n.aim ? 'aim' : ''].join(' ');
      el.textContent = n.kind === 'board' ? n.id.toUpperCase() : n.id;
      labelLayer.appendChild(el);
      labels.set(n.id, el);
    }
  }

  function renderFallback(graph) {
    const top = [...graph.links].sort((a, b) => b.s - a.s).slice(0, FALLBACK_ROWS);
    host.innerHTML = `<div class="graph-fallback"><p class="muted">3D view unavailable: ${esc(reason)}. The same links, strongest first:</p>`
      + (top.length
        ? `<ol>${top.map((l) => `<li><b>${esc(idOf(l.source))}</b> → <b>${esc(idOf(l.target))}</b> <span class="k ${esc(l.kind)}">${esc(l.kind)}</span> ${Number(l.s).toFixed(4)}</li>`).join('')}</ol>`
        : '<p>No links for this clue in this memory.</p>')
      + (graph.bomb_path ? `<p class="bombline">Path to the bomb: ${graph.bomb_path.map(esc).join(' → ')}</p>` : '')
      + '</div>';
  }

  function show(graph, aim) {
    if (!host) return;
    const aimed = new Set(aim || []);
    const old = new Map(data.nodes.map((n) => [n.id, n]));
    data = {
      nodes: graph.nodes.map((n) => {
        const o = old.get(n.id);
        return o ? { ...n, aim: aimed.has(n.id), x: o.x, y: o.y, z: o.z } : { ...n, aim: aimed.has(n.id) };
      }),
      links: graph.links.map((l) => ({ ...l })),
    };
    clue = graph.clue;
    if (mode === 'fallback') {
      renderFallback(graph);
      return;
    }
    const g = ensureGraph();
    const note = host.querySelector('.graph-empty');
    if (note) note.remove();
    mode = '3d';
    makeLabels();
    flyPending = true;
    g.graphData(data);
  }

  function reveal(word) {
    const n = data.nodes.find((x) => x.id === word);
    if (!n) return;
    n.revealed = true;
    const el = labels.get(word);
    if (el) el.classList.add('revealed');
    if (fg && mode === '3d') fg.nodeColor(nodeColor);
  }

  function clear(message) {
    if (!host) return;
    data = { nodes: [], links: [] };
    if (fg) {
      fg.graphData(data);
      labelLayer.textContent = '';
      labels = new Map();
    }
    if (mode === 'fallback') host.textContent = '';
    let note = host.querySelector('.graph-empty');
    if (!note) {
      note = document.createElement('p');
      note.className = 'graph-empty';
      host.appendChild(note);
    }
    note.textContent = message;
  }

  function stats() {
    return { mode, nodes: data.nodes.length, links: data.links.length };
  }

  window.CodebookGraph = { mount, show, reveal, clear, stats };
})();
