"""Record the demo video from the live view: real games, real Cypher, with on-screen captions.

Needs the live view running (`uv run codebook ui`), Google Chrome and ffmpeg:
    uv run --with playwright python scripts/record_demo.py --out demo
Writes demo/codebook-demo.mp4 (1600x900, H.264). Every board is a seed you can replay.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:7811"
W, H = 1600, 900

CAPTION = """(text) => {
  let el = document.getElementById('demo-caption');
  if (!el) {
    el = document.createElement('div'); el.id = 'demo-caption';
    Object.assign(el.style, {position: 'fixed', left: '0', right: '0', bottom: '0', padding: '18px 44px',
      background: 'rgba(21,26,46,0.94)', color: '#F4EFE4', font: '600 25px "Nunito Sans", Arial, sans-serif',
      lineHeight: '1.35', zIndex: '9999', borderTop: '3px solid #7EA2F2'});
    document.body.appendChild(el);
  }
  el.textContent = text;
}"""

CARD = """([title, body, mono]) => {
  let el = document.getElementById('demo-card');
  if (!el) { el = document.createElement('div'); el.id = 'demo-card'; document.body.appendChild(el); }
  Object.assign(el.style, {position: 'fixed', inset: '0', background: '#151A2E', color: '#F4EFE4', zIndex: '9998',
    display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 120px', gap: '28px'});
  const esc = s => String(s).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
  el.innerHTML = `<div style="font:700 64px Rubik, Arial, sans-serif;letter-spacing:-1px">${esc(title)}</div>` +
    (mono ? `<pre style="font:20px/1.5 'JetBrains Mono', monospace;color:#9DB8F5;background:#1F2640;border-radius:16px;padding:24px 28px;white-space:pre-wrap;margin:0">${esc(body)}</pre>`
          : `<div style="font:500 30px/1.45 'Nunito Sans', Arial, sans-serif;color:#C9CEDD;max-width:1300px">${esc(body)}</div>`);
}"""

UNCARD = "() => { const el = document.getElementById('demo-card'); if (el) el.remove(); }"


def post_game(body: dict) -> str:
    req = urllib.request.Request(f"{BASE}/api/game", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["game"]


def game_state(gid: str) -> dict:
    with urllib.request.urlopen(f"{BASE}/api/game/{gid}?since=0", timeout=30) as resp:
        return json.load(resp)


def play_live(page: Page, *, partner: str, memory: str, seed: int, delay: float, caption: str,
              max_s: float, giver: str = "codebook", end_caption: str | None = None) -> dict:
    """Start a game from the page's own controls and let it play on screen."""
    page.goto(f"{BASE}/?tab=queries")
    page.wait_for_function("document.getElementById('partner').options.length > 1")
    page.evaluate("""([p, m, s, d, g]) => {
        document.getElementById('partner').value = p; document.getElementById('memory').value = m;
        document.getElementById('seed').value = s; document.getElementById('delay').value = d;
        document.getElementById('giver').value = g; document.getElementById('start').click(); }""",
                  [partner, memory, str(seed), str(delay), giver])
    page.evaluate(CAPTION, caption)
    started = time.time()
    while time.time() - started < max_s:
        text = page.inner_text("#status")
        if text and not text.startswith("Server"):
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500)
    if end_caption:
        page.evaluate(CAPTION, end_caption.format(status=page.inner_text("#status")))
        page.wait_for_timeout(3500)
    return {"status": page.inner_text("#status")}


def scorecard_text(path: Path) -> str:
    if not path.exists():
        return "Scorecard: see results/ in the repository."
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = []
    for p in data.get("promises", []):
        lines.append(f"{p['n']}. {'kept    ' if p['kept'] else 'not kept'}  {p['promise']}")
    kept = sum(p["kept"] for p in data.get("promises", []))
    return "\n".join(lines) + f"\n\n{kept} / 4 promises kept, on boards the partners never saw."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo")
    ap.add_argument("--game-seed", type=int, default=6183)
    ap.add_argument("--swap-partner", default="persona-mirror")
    ap.add_argument("--swap-memory", default="persona-leaper")
    ap.add_argument("--swap-seed", type=int, default=6141)
    ap.add_argument("--handover-seed", type=int, default=8200)
    ap.add_argument("--results", default="")
    ap.add_argument("--persistence", default="results/persistence-w2v.txt")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=["--force-dark-mode"])
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(out),
                                  record_video_size={"width": W, "height": H}, color_scheme="dark")
        page = ctx.new_page()

        page.goto(f"{BASE}/")
        page.evaluate(CARD, ["Codebook", "An AI teammate that learns how you think, remembers it next session, "
                             "and can hand that memory to another AI. Every partner gets their own memory: "
                             "a graph in FalkorDB.", False])
        page.wait_for_timeout(6000)

        page.goto(f"{BASE}/?tab=compare&seed=6042&memories=everyone,w2v,persona-mirror")
        page.wait_for_selector("#cmp .opt", timeout=60000)
        page.evaluate(CAPTION, "Same board, three memories, three different clues. Everyone's memory says SKY 2; "
                               "the word2vec bot's memory says MIDDLE 1; a partner who thinks backwards gets PLACE 3.")
        page.wait_for_timeout(12000)

        page.goto(f"{BASE}/?tab=memory&mem=w2v")
        page.wait_for_selector(".bars", timeout=60000)
        page.evaluate(CAPTION, "Each partner's memory is its own graph. After 20 practice games, Codebook learned that "
                               "the word2vec bot links words by shared associates (2.0), not the way people do.")
        page.wait_for_timeout(13000)

        play_live(page, partner="w2v", memory="own", seed=args.game_seed, delay=0.5, max_s=40,
                  caption="A live game with the bot's own memory. On the right: every Cypher query FalkorDB runs, "
                          "with its key, rows and time. Code blocks any clue that reaches the bomb.")

        play_live(page, partner=args.swap_partner, memory="own", seed=args.swap_seed, delay=0.25, max_s=30,
                  caption="The swap test, part 1: a planted partner who thinks backwards, with its own memory.",
                  end_caption="Its own memory: {status}.")
        play_live(page, partner=args.swap_partner, memory=args.swap_memory, seed=args.swap_seed, delay=0.25,
                  max_s=35, caption="Part 2: the same board and code, but the wrong partner's memory.",
                  end_caption="The wrong memory: {status}. The memory is about this partner.")

        proof = Path(args.persistence)
        body = proof.read_text(encoding="utf-8")[-1400:] if proof.exists() else "(run scripts/persistence_check.sh)"
        page.evaluate(CARD, ["Memory survives a restart", body, True])
        page.evaluate(CAPTION, "We restarted FalkorDB. A fresh process replayed the same games with the same "
                               "fingerprint: the memory came back from the database, not from our process.")
        page.wait_for_timeout(13000)
        page.evaluate(UNCARD)

        play_live(page, partner="w2v", memory="own", seed=args.handover_seed, delay=0.2, max_s=45,
                  giver="claude-sonnet",
                  caption="Handover: Claude now gives the clues, choosing from this partner's memory. It holds no "
                          "database password, and the block still has the final say.")

        page.evaluate(CARD, ["The scorecard", scorecard_text(Path(args.results)) if args.results else
                             "Results in the repository.", True])
        page.evaluate(CAPTION, "Promises written down before testing, scored by the unmodified Codenames AI "
                               "Competition engine on boards the partners never saw.")
        page.wait_for_timeout(14000)
        page.evaluate(CARD, ["Every partner gets their own codebook.",
                             "Codebook · FalkorDB 6.0.2 · Graph Hacks 2026, Track 02 · open source (MIT)", False])
        page.wait_for_timeout(5000)
        video = page.video.path()
        ctx.close()
        browser.close()

    mp4 = out / "codebook-demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "20", "-movflags", "+faststart", str(mp4)], check=True)
    print(f"wrote {mp4}")


if __name__ == "__main__":
    main()
