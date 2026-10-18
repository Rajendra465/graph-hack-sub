# Live view redesign: self-explanatory, animated, with a 3D memory graph

Date: 2026-10-18. Status: design approved in chat (approach A, all three sections), awaiting spec review.

## Goal

A judge who runs `uv run codebook ui`, or watches the demo video, should understand within about 30 seconds what
Codebook does (one memory per partner) and why the graph matters, without reading the README.

## Success criteria

1. **First visit is guided.** A start screen offers four one-click scenarios and a 60-second tour, and every panel
   says what it shows.
2. **Every feature is one click from the start screen:** the bomb-vs-win comparison, the AI handover (replay), play
   as the guesser, compare memories, partner memory, live Cypher and all queries.
3. **The 3D memory graph shows real FalkorDB data** around each clue, lighting up the clue's direct, backwards and
   two-step links and the path to the bomb.
4. **Motion is smooth** (cards flip, the clue slams in, query rows slide in) and respects `prefers-reduced-motion`.
5. **Nothing regresses.** The 54 existing tests pass, every element id the capture script uses still exists, and
   setup stays `uv run codebook ui`.

## Constraints

- One page served by the existing Starlette app, with no build step. Libraries come from jsDelivr, pinned with
  Subresource Integrity:
  - `3d-force-graph@1.80.1` (three.js inside, global `ForceGraph3D`);
  - `gsap@3.15.0` (global `gsap`).
- Same security posture as today: `TrustedHostMiddleware`, same-origin JSON POSTs, read-only queries for every view,
  and `esc()`/`textContent` for every value from the server.
- Keep every element id that `codebook-video/scripts/capture.mjs` and `codebook/scripts/record_demo.py` use:
  `partner memory seed giver learn replay delay start board clueword cluemeta status blocks log yourturn endturn qlist
  cmp cmpmems gameinfo`, plus the classes `.tile[data-w]`, `.tile.r-<role>`, `.tabs button[data-tab]`, `.bars`,
  `.stats`, `.stat` and `#blocks .block`.
- Files stay under about 500 lines each.

## Experience

**Start screen** (an overlay; shown on the first visit, remembered in `localStorage`, reopened from a "Scenarios"
button):

| Card | What it runs | Real data |
|---|---|---|
| Same board, two memories | the word2vec bot on board 6030 with everyone's memory (it hits the bomb), then with its own memory (it wins in 11). A result strip compares the two. | benchmark games `w2v-cold-6030` and `w2v-warm-6030`, repeated move for move |
| Another AI takes over | Claude Sonnet's logged clues with the GloVe bot's memory on board 6030 (wins in 8) | `glove-handover-6030`, replayed with no AI calls |
| Play it yourself | you guess; learning is on, so your own memory forms | a live game, partner `you` |
| Explore a memory | pick a partner; the 3D graph shows its links around board 6030; the Compare tab shows each memory's top clue | `GET /api/graph` and `/api/suggest` |

A **"Take the 60-second tour"** button runs seven coach-mark steps. Each one spotlights an element and shows a
caption with Back/Next: scenarios → board → clue and narration → 3D graph → Live Cypher → Partner memory → Custom game.

**Main screen:**
- **Left column:** the board, the clue banner, a **narration line** and the turn log. The narration line turns game
  events into plain words:
  - `clue` → "Codebook gives CANDY · 1, aiming at CHOCOLATE (bomb risk 0.4%)"
  - `block` → "Blocked BLOW: a 7.4% chance it leads to the bomb"
  - `guess` → "SHIP ✓ the partner got it" or "GAME ✗ the bomb"
  - `end` → "Won in 11 turns · matches the benchmark log"
- **Right column:** the **3D memory graph** on top, with the tabs (Live Cypher, Partner memory, Compare memories, All
  queries) below.
- Every panel has a one-line "what you're seeing" header and an ⓘ tooltip.
- A legend explains the card colours (team, opponent, neutral, bomb) and the graph links (direct, backwards, two-step,
  path to the bomb).
- The old control row becomes a **Custom game** drawer with the same controls and ids.

## The 3D memory graph

**Data: `codebook/graphview.py`.**
`clue_graph(memory, read_key, words, roles, revealed, clue, max_via=30) -> dict` runs three read-only queries on the
memory key:

| Query | Status | Gives |
|---|---|---|
| `CLUE_LINKS` | existing | direct (clue → word) and backwards (word → clue) links to the board |
| `CLUE_CHAINS` | new, index-first | two-step chains clue → via → board word, with the strongest via words (`LIMIT $limit`) |
| `PATH_TO` | existing | the strongest chain from the clue to the bomb |

The new query:

```cypher
MATCH (c:Word) WHERE c.text = $clue
WITH c
MATCH (c)-[r1:ASSOC]->(m:Word)-[r2:ASSOC]->(t:Word)
WHERE t.text IN $board AND m <> c AND t <> c AND m <> t
RETURN m.text AS via, t.text AS word, coalesce(r1.pp, r1.p) * coalesce(r2.pp, r2.p) AS s
ORDER BY s DESC LIMIT $limit
```

Response:

```json
{"clue": "candy", "turn": 1, "read_key": "codebook:partner:w2v",
 "nodes": [{"id": "chocolate", "kind": "board", "role": "team", "revealed": true},
           {"id": "candy", "kind": "clue"}, {"id": "sweet", "kind": "via"}],
 "links": [{"source": "candy", "target": "chocolate", "kind": "direct", "s": 0.12}],
 "bomb_path": ["candy", "bar", "game"]}
```

- `kind` is one of `board | clue | via` for nodes, and `direct | reverse | chain | bomb` for links.
- There are at most `max_via` (30) via nodes and 160 links.
- The 25 board words are always present.

**Endpoints** (both GET, both read-only):

- `/api/game/{gid}/graph?turn=N`
  - The game must exist (404 otherwise).
  - `turn` is a positive integer and defaults to the latest clue; 404 if there's no clue yet.
  - Roles come from the game's key, and revealed words from its guess events up to that turn.
- `/api/graph?seed=N&memory=everyone|<partner>&clue=<word>`
  - `seed` is in 0..10^9.
  - `memory` must be `everyone` or an existing partner id (validated by `keys.partner_key`).
  - `clue` is optional (lowercase word, at most 32 characters) and defaults to the memory's top suggestion from `plan()`.
  - Nothing is revealed.
- **Errors:** invalid input returns 400 `{"error": ...}`. A database error returns 503 with a message that doesn't
  leak the address.

**Rendering: `static/graph3d.js`.**
- `ForceGraph3D` with text sprites for labels. Board nodes are coloured by role; unrevealed roles are muted, and
  revealed ones are solid.
- The clue node is large and orange, and via nodes are small.
- Link colours show kind. The clue's chains carry directional particles, and the bomb path pulses red.
- The camera flies to the clue on every new clue. You can drag to orbit and scroll to zoom. Clicking a node shows its
  links in a side card.
- **Fallbacks:** without WebGL, or if the CDN fails, the panel shows the same nodes and links as a ranked 2D list,
  saying why.
- The graph's own queries appear in the Live Cypher tab. The game-graph handler sets the same thread-local game tag
  the game thread uses (`_current.game`) and resets it in `finally`, so those queries join the game's events.

## Motion (GSAP, pinned)

| Element | Animation |
|---|---|
| Cards | flip in 3D (rotateY) to their role colour when revealed; a small tilt on hover |
| Clue banner | scale and blur in |
| Narration | types itself out |
| Live Cypher | new rows slide in, newest first |
| Memory bars | grow from 0 |
| Game end | the result banner drops in |
| Tour | the spotlight eases between targets |

Under `prefers-reduced-motion`: no flips, particles or typing, only instant changes.

## Files

| File | Role | Size |
|---|---|---|
| `static/index.html` | markup: header, start screen, main grid, drawer, tour layer; script and style tags | ~200 lines |
| `static/app.css` | design tokens (light and dark), layout, components, reduced motion | ~450 lines |
| `static/app.js` | state, API client, game loop (start, poll, handle), panels, narration, scenarios | ~500 lines |
| `static/graph3d.js` | the graph wrapper: init, update, highlight, fallback | ~250 lines |
| `static/tour.js` | coach-mark tour | ~150 lines |
| `web.py` | mounts `/static`; adds the two graph routes | |
| `graphview.py` | the graph builder | ~120 lines |
| `cypher.py` | adds `CLUE_CHAINS` | |

## Error handling

- **Graph fetch fails:** the panel shows "Graph unavailable: <reason>" and the game keeps running.
- **Game errors:** shown in the status and the narration.
- **Tour target missing:** the step is skipped.
- **`localStorage` unavailable:** the start screen shows on every visit; wrapped in try/catch.

## Testing

1. **Contract tests** (synthetic graph, `cbtest:` prefix, database 15) for `graphview.clue_graph`:
   - every board word is present with its role;
   - the clue node exists;
   - link kinds are valid;
   - the via cap holds;
   - the bomb path appears when a chain exists;
   - an unknown clue gives the board nodes and no links.
2. **Unit tests** for request validation: turn parsing, the word regex, memory ids, the seed range.
3. **The existing 54 tests** still pass.
4. **Browser smoke test** (puppeteer-core with the installed Chrome, in `codebook-video/scripts/ui_smoke.mjs`):
   - every scenario starts and reaches its end status;
   - the graph canvas renders;
   - the tour runs all seven steps;
   - no console errors;
   - every preserved id exists.
5. **Security review** of the two new endpoints and the page.
6. **Afterwards:** re-capture `docs/img/*.png`, and optionally re-render the demo video from the new UI.

## Out of scope

A React or Vite build, new game features, authentication, a mobile-first layout (a basic responsive stack is enough),
and changes to the benchmark or results.
