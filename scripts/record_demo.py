"""Record the demo video from the live view: real games, real Cypher, with on-screen captions.

Needs the live view running (`uv run codebook ui`), Google Chrome and ffmpeg:
    uv run --with playwright python scripts/record_demo.py --out demo
Writes demo/codebook-demo.mp4 (1600x900, H.264). Every board is a seed you can replay, and every caption that
quotes a clue or a result reads it from the live view or from the final run's game log.
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
NAMES = {"w2v": "the word2vec bot", "glove": "the GloVe bot", "persona-mirror": "the backwards thinker",
         "persona-leaper": "the two-step jumper"}
LINKS = {"direct": "direct links", "reverse": "backwards links", "chain": "two-step chains",
         "shared": "shared associates"}

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

# The speed menu offers slow/normal/fast; add the requested delay as an option if it is not one of them.
START = """([p, m, s, d, g]) => {
  const delay = document.getElementById('delay');
  if (![...delay.options].some(o => o.value === d)) delay.add(new Option(d + ' s', d));
  document.getElementById('partner').value = p; document.getElementById('memory').value = m;
  document.getElementById('seed').value = s; delay.value = d;
  document.getElementById('giver').value = g; document.getElementById('start').click(); }"""


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=120) as resp:
        return json.load(resp)


def memory_label(mem: str) -> str:
    return "everyone's memory" if mem == "everyone" else f"{NAMES.get(mem, mem)}'s memory"


def compare_caption(seed: int, memories: list[str]) -> str:
    by_memory = get_json(f"/api/suggest?seed={seed}&memories={','.join(memories)}")["by_memory"]
    parts = [f"{memory_label(m)} says {opts[0]['clue'].upper()} {opts[0]['count']}"
             for m, opts in by_memory.items() if opts]
    return f"Same board, {len(parts)} memories, {len(parts)} different clues: " + "; ".join(parts) + "."


def style_caption(pid: str) -> str:
    view = get_json(f"/api/memory/{pid}")
    style = view["style"]
    top, low = max(style, key=style.get), min(style, key=style.get)
    return (f"Each partner's memory is its own graph. After {view['games']} practice games, Codebook learned that "
            f"{NAMES.get(pid, pid)} links words mostly by {LINKS[top]} ({style[top]:.1f}) and least by "
            f"{LINKS[low]} ({style[low]:.1f}). Nobody told it.")


def run_rows(run: str) -> list[dict]:
    path = Path("results/runs") / run / "games.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def logged(rows: list[dict], partner: str, condition: str, seed: int) -> dict | None:
    return next((r for r in rows if r["partner"] == partner and r["condition"] == condition and r["seed"] == seed),
                None)


def outcome(row: dict | None) -> str:
    if row is None:
        return "not in the log"
    if row["won"]:
        return f"won in {row['turns']} turns"
    return "hit the bomb" if row["assassin"] else "lost on the turn limit"


def block_caption(row: dict | None) -> str:
    base = ("A live game with the word2vec bot's own memory. On the right: every Cypher query FalkorDB runs, with "
            "its key, rows and time.")
    blocks = [b for b in (row or {}).get("blocks", []) if len(b.get("path", [])) >= 2]
    if not blocks:
        return base + " Code blocks any clue that reaches the bomb."
    b = blocks[0]
    return (base + f" Watch the block: {b['clue'].upper()} is refused, because in this memory it leads to "
            f"{b['path'][-1].upper()}, the bomb.")


def play_live(page: Page, *, partner: str, memory: str, seed: int, delay: float, caption: str,
              max_s: float, giver: str = "codebook", end_caption: str | None = None) -> dict:
    """Start a game from the page's own controls and let it play on screen."""
    page.goto(f"{BASE}/?tab=queries")
    page.wait_for_function("document.getElementById('partner').options.length > 1")
    page.evaluate(START, [partner, memory, str(seed), str(delay), giver])
    page.evaluate(CAPTION, caption)
    started = time.time()
    while time.time() - started < max_s:
        text = page.inner_text("#status")
        if text and not text.startswith("Server"):
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500)
    status = page.inner_text("#status")
    if end_caption:
        page.evaluate(CAPTION, end_caption.replace("{status}", status or "still playing"))
        page.wait_for_timeout(4500)
    return {"status": status, "seconds": round(time.time() - started, 1)}


def scorecard_text(path: Path) -> str:
    if not path.exists():
        return "Scorecard: see results/ in the repository."
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = []
    for p in data.get("promises", []):
        lines.append(f"{p['n']}. {'kept    ' if p['kept'] else 'not kept'}  {p['promise']}")
    kept = sum(p["kept"] for p in data.get("promises", []))
    return "\n".join(lines) + f"\n\n{kept} / {len(lines)} promises kept, on boards the partners never saw."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo")
    ap.add_argument("--run", default="")
    ap.add_argument("--compare-seed", type=int, default=6042)
    ap.add_argument("--game-seed", type=int, default=6183)
    ap.add_argument("--swap-partner", default="persona-mirror")
    ap.add_argument("--swap-memory", default="persona-leaper")
    ap.add_argument("--swap-seed", type=int, default=6141)
    ap.add_argument("--handover-partner", default="glove")
    ap.add_argument("--handover-giver", default="claude-sonnet")
    ap.add_argument("--handover-seed", type=int, default=6030)
    ap.add_argument("--persistence", default="results/persistence-glove.txt")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run = args.run or Path("results/LATEST_RUN").read_text(encoding="utf-8").strip()
    rows = run_rows(run)
    timings = {}

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

        memories = ["everyone", "w2v", "persona-mirror"]
        caption = compare_caption(args.compare_seed, memories)
        page.goto(f"{BASE}/?tab=compare&seed={args.compare_seed}&memories={','.join(memories)}")
        page.wait_for_selector("#cmp .opt", timeout=60000)
        page.evaluate(CAPTION, caption)
        page.wait_for_timeout(11000)

        caption = style_caption("w2v")
        page.goto(f"{BASE}/?tab=memory&mem=w2v")
        page.wait_for_selector(".bars", timeout=60000)
        page.evaluate(CAPTION, caption)
        page.wait_for_timeout(11000)

        timings["block"] = play_live(page, partner="w2v", memory="own", seed=args.game_seed, delay=0.5, max_s=90,
                                     caption=block_caption(logged(rows, "w2v", "warm", args.game_seed)),
                                     end_caption="The word2vec bot with its own memory: {status}.")

        partner = NAMES.get(args.swap_partner, args.swap_partner)
        timings["swap-own"] = play_live(
            page, partner=args.swap_partner, memory="own", seed=args.swap_seed, delay=0.5, max_s=45,
            caption=f"The swap test, part 1: {partner}, a planted test partner, with its own memory.",
            end_caption="Its own memory: {status}.")
        timings["swap-wrong"] = play_live(
            page, partner=args.swap_partner, memory=args.swap_memory, seed=args.swap_seed, delay=0.5, max_s=60,
            caption=f"Part 2: the same board and the same code, but {memory_label(args.swap_memory)}.",
            end_caption="The wrong memory: {status}. The memory is about this partner, not a better general model.")

        proof = Path(args.persistence)
        body = proof.read_text(encoding="utf-8")[-1400:] if proof.exists() else "(run scripts/persistence_check.sh)"
        page.evaluate(CARD, ["Memory survives a restart", body, True])
        page.evaluate(CAPTION, "We restarted FalkorDB. A fresh process replayed the same games with the same "
                               "fingerprint: the memory came back from the database, not from our process.")
        page.wait_for_timeout(12000)
        page.evaluate(UNCARD)

        hp = args.handover_partner
        plain = logged(rows, hp, "plain", args.handover_seed)
        hand = logged(rows, hp, "handover", args.handover_seed)
        own = (hand or {}).get("clues_by", {}).get(args.handover_giver, 0)
        total = sum((hand or {}).get("clues_by", {}).values())
        timings["handover"] = play_live(
            page, partner=hp, memory="own", seed=args.handover_seed, delay=0.5, max_s=75, giver=args.handover_giver,
            caption=f"Handover: Claude Sonnet now gives the clues to {NAMES.get(hp, hp)}, choosing from its memory "
                    "through Codebook's tools. It holds no database password, and the block still has the final say.",
            end_caption=f"In the benchmark, on this board: Claude Sonnet alone {outcome(plain)}; with "
                        f"{memory_label(hp)} it {outcome(hand)}, {own} of {total} clues its own.")

        page.evaluate(CARD, ["The scorecard", scorecard_text(Path(f"results/{run}.json")), True])
        page.evaluate(CAPTION, "Promises written down before testing, scored by the unmodified Codenames AI "
                               "Competition engine on boards the partners never saw.")
        page.wait_for_timeout(13000)
        page.evaluate(CARD, ["Every partner gets their own codebook.",
                             "Codebook · FalkorDB 6.0.2 · Graph Hacks 2026, Track 02 · open source (MIT)", False])
        page.wait_for_timeout(5000)
        video = page.video.path()
        ctx.close()
        browser.close()

    mp4 = out / "codebook-demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "20", "-movflags", "+faststart", str(mp4)], check=True)
    print(json.dumps(timings))
    print(f"wrote {mp4}")


if __name__ == "__main__":
    main()
