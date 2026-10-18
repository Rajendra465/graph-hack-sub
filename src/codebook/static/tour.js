// A coach-mark tour: a spotlight on one element at a time with a caption and Back / Next / Skip.
// window.CodebookTour = { start(steps, onEnd), end(), isOpen() }; steps: [{ el: selector | () => Element, title, text }]
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const PAD = 8;
  let steps = [];
  let at = 0;
  let onEnd = null;

  const target = (step) => (typeof step.el === 'function' ? step.el() : document.querySelector(step.el));
  const visible = (el) => Boolean(el) && el.getBoundingClientRect().width > 0;

  function place(el) {
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    const r = el.getBoundingClientRect();
    Object.assign($('tourspot').style, {
      left: `${r.left - PAD}px`, top: `${r.top - PAD}px`, width: `${r.width + PAD * 2}px`, height: `${r.height + PAD * 2}px`,
    });
    const tip = $('tourtip');
    const below = r.bottom + tip.offsetHeight + 30 < window.innerHeight;
    Object.assign(tip.style, {
      left: `${Math.min(Math.max(16, r.left), window.innerWidth - tip.offsetWidth - 16)}px`,
      top: below ? `${r.bottom + 18}px` : `${Math.max(16, r.top - tip.offsetHeight - 18)}px`,
    });
  }

  function show(i, direction) {
    let j = i;
    while (j >= 0 && j < steps.length && !visible(target(steps[j]))) j += direction;  // skip missing targets
    if (j < 0 || j >= steps.length) {
      end();
      return;
    }
    at = j;
    $('tourstep').textContent = `${j + 1} / ${steps.length} · ${steps[j].title}`;
    $('tourtext').textContent = steps[j].text;
    $('tourback').disabled = j === 0;
    $('tournext').textContent = j === steps.length - 1 ? 'Done' : 'Next';
    place(target(steps[j]));
    if (window.gsap && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.gsap.fromTo('#tourtip', { y: 10, opacity: 0 }, { y: 0, opacity: 1, duration: 0.3 });
    }
  }

  function start(list, done) {
    steps = list;
    onEnd = done || null;
    $('tour').classList.remove('hidden');
    show(0, 1);
  }

  function end() {
    $('tour').classList.add('hidden');
    if (onEnd) onEnd();
  }

  const isOpen = () => !$('tour').classList.contains('hidden');
  $('tournext').addEventListener('click', () => (at >= steps.length - 1 ? end() : show(at + 1, 1)));
  $('tourback').addEventListener('click', () => show(at - 1, -1));
  $('tourskip').addEventListener('click', end);
  document.addEventListener('keydown', (e) => {
    if (!isOpen()) return;
    if (e.key === 'Escape') end();
    if (e.key === 'ArrowRight') $('tournext').click();
    if (e.key === 'ArrowLeft') $('tourback').click();
  });
  window.addEventListener('resize', () => { if (isOpen()) show(at, 1); });
  window.CodebookTour = { start, end, isOpen };
})();
