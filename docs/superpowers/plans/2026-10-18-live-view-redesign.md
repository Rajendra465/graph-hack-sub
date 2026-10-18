# Live view redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Codebook's live view so a first-time visitor understands it unaided: scenario cards, a 60-second
tour, plain-English narration, motion, and a 3D graph of the partner's real FalkorDB memory around each clue.

**Architecture:**
- **Back end:** a new module `graphview.py` builds a clue's neighbourhood (nodes and links) from three read-only
  Cypher queries on one memory key. Two GET endpoints in `web.py` serve it: one per game turn, one per seeded board.
- **Front end:** the page stays static (no build step) but is split into focused files under `/static`. It uses
  `3d-force-graph` for the 3D view and GSAP for motion, both pinned with Subresource Integrity.
- **Compatibility:** every element id the capture and recording scripts use is preserved.

**Tech Stack:** Python 3.12, Starlette 1.8 (`StaticFiles`, `TestClient` with httpx), FalkorDB 6.0.2 Cypher,
vanilla JS (ES2020), `3d-force-graph@1.80.1` (three.js inside), `gsap@3.15.0`, pytest, puppeteer-core with the
installed Chrome.

**Spec:** `docs/superpowers/specs/2026-10-18-live-view-redesign-design.md`

## Global Constraints

- No build step. Setup stays `uv run codebook ui`.
- Libraries are loaded only from jsDelivr, pinned with SRI:
  - `https://cdn.jsdelivr.net/npm/3d-force-graph@1.80.1/dist/3d-force-graph.min.js`
    `sha384-i98VDQKdpyVrtyuFn0fjUWJBLBmxnqHqOANcvYe9HLJUgT2wPixa4ZkLd7Dh3VEk`
  - `https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js`
    `sha384-XmJ9SoHtVOHoQUcKvFAzVXwdkKo1Ie3bhmSoIAkcdsHGaIrVJIkmozyq0FJeb/Ly`
- **Preserved ids** (the capture scripts set these and call `document.getElementById("start").click()`):
  `partner memory seed giver learn replay delay start board clueword cluemeta status blocks log yourturn endturn
  qlist cmp cmpmems gameinfo`. Never make the drawer that holds them `inert`.
- **Preserved classes:** `.tile[data-w]`, `.tile.r-<role>`, `.tabs button[data-tab]`, `.bars`, `.stats`, `.stat`,
  `#blocks .block`, `#cmp .opt`.
- Every graph query is read-only (`ro_query`). The graph endpoints are GET only. Server values reach the page only
  through `esc()` or `textContent`.
- **Graph limits:** at most 30 via words (plus any on the bomb path) and 160 links. The 25 board words are always
  nodes.
- **Request bounds:**
  - `seed`: 0..10^9;
  - `turn`: 1..100;
  - a word matches `[a-z][a-z'-]{0,31}`;
  - partner ids are checked by `keys.partner_key`.
- `prefers-reduced-motion` turns off flips, particles, typing and camera flights.
- Each static file stays at about 500 lines or fewer, and each function under about 50 lines.
- Commits end with the session's attribution lines; git author `Codebook <sarpal465@gmail.com>`.

## Review Focus

1. **A clue with no links in that memory** (rare or unknown word): the graph shows the 25 board nodes and the clue,
   with no links and no error. Pinned by `test_an_unknown_clue_gives_the_board_and_no_links` (Task 1).
2. **The CDN is blocked or the judge is offline:** games still play, and the graph panel shows a ranked 2D list that
   says why. Pinned by smoke check 6 (Task 5).
3. **Exploring a memory that doesn't exist yet** (e.g. `memory=you` before any human game): 400 with "no memory
   for 'you'", never a crash. Pinned by `test_board_graph_refuses_a_missing_memory` and
   `test_board_graph_route_refuses_bad_requests` (Task 2).
4. **Malformed query strings** (`clue=../x`, `seed=abc`, `memory=W2V!`, `turn=0`): 400 before any query runs.
   Pinned by `test_graph_request_refuses_bad_input` and `test_turn_is_optional_and_bounded` (Task 1), and by
   `test_board_graph_route_refuses_bad_requests` and `test_game_graph_route_answers_404_and_400` (Task 2).
5. **A human guesser must never see the key.** That covers the clue's targets in the meta line, and the graph, which
   colours words by role and draws the path to the bomb. The graph appears only once the game ends. Pinned by smoke
   check 5 (Task 5).

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/codebook/cypher.py` | modify | add `CLUE_CHAINS` (index-first two-step chains) and register it in `ALL` |
| `src/codebook/graphview.py` | create | `clue_graph()` plus request parsing (`parse_word`, `parse_turn`, `parse_graph_request`, `GraphRequest`) |
| `src/codebook/web.py` | modify | `LiveApp.game_graph`, `LiveApp.board_graph`, two routes, and the `/static` mount |
| `src/codebook/static/index.html` | rewrite | markup only: top bar, two columns, start screen, drawer, tour layer, script tags |
| `src/codebook/static/app.css` | create | design tokens, layout, board, graph, tabs, overlays, tour, reduced motion |
| `src/codebook/static/graph3d.js` | create | `window.CodebookGraph`: the 3D graph, labels, node card and 2D fallback |
| `src/codebook/static/tour.js` | create | `window.CodebookTour`: coach marks |
| `src/codebook/static/app.js` | create | `window.CB`: state, API, game loop, board, narration, event handling |
| `src/codebook/static/panels.js` | create | tabs: Live Cypher, Partner memory, Compare, All queries |
| `src/codebook/static/scenarios.js` | create | start screen, four scenarios, drawer, tour steps, tooltips, deep links, init |
| `tests/unit/test_graphview_params.py` | create | request parsing |
| `tests/contract/test_graphview.py` | create | `clue_graph` and the two `LiveApp` graph methods on the synthetic graph |
| `tests/contract/test_web_routes.py` | create | the graph routes and the static files, over HTTP |
| `scripts/record_demo.py` | modify (line 193) | open `/?tab=queries` so the new start screen doesn't cover the recording |
| `../codebook-video/scripts/ui_smoke.mjs` | create | browser smoke test of every scenario, the tour, the fallback and the preserved ids |
| `../codebook-video/scripts/readme_shots.mjs` | create | re-capture `docs/img/*.png` from the new UI |

Script load order (index.html): gsap → 3d-force-graph → graph3d.js → tour.js → app.js → panels.js → scenarios.js.
All commands below run from `C:\Users\sarpa\Desktop\ps5\codebook` unless a step says otherwise.

---

### Task 1: Graph data from the memory (`CLUE_CHAINS` + `graphview.py`)

**Files:**
- Modify: `src/codebook/cypher.py` (after the `CLUE_LINKS` block, line 111; the `ALL` dict, line 238)
- Create: `src/codebook/graphview.py`
- Test: `tests/unit/test_graphview_params.py`, `tests/contract/test_graphview.py`

**Interfaces:**
- Consumes:
  - `Db.ro_query(key, cypher, params, name=...) -> QueryResult`, which has `.rows` and `.records()` (a list of
    dicts keyed by column);
  - `Memory.db`;
  - `Memory.path_to(key, clue, target) -> tuple[list[str], float] | None`;
  - `keys.partner_key(pid) -> str` (raises `BadPartnerId`, a `ValueError`);
  - `C.CLUE_LINKS` (columns `word, s, kind`, where kind 0 = clue→word and 1 = word→clue).
- Produces:
  - `clue_graph(memory, read_key, words, roles, revealed, clue, *, max_via=30) -> dict` with keys
    `clue, read_key, nodes, links, bomb_path`;
  - `GraphRequest(seed: int, memory_of: str, clue: str | None)`;
  - `parse_word(str) -> str`, `parse_turn(str | None) -> int | None`, `parse_graph_request(Mapping) -> GraphRequest`;
  - `C.CLUE_CHAINS` (columns `via, word, s`).

- [ ] **Step 1: Write the failing unit tests**

**File:** `tests/unit/test_graphview_params.py`

```python
"""Request parsing for the graph endpoints: bad input is refused before any query runs."""

import pytest

from codebook.graphview import GraphRequest, parse_graph_request, parse_turn, parse_word


def test_turn_is_optional_and_bounded():
    assert parse_turn(None) is None
    assert parse_turn("") is None
    assert parse_turn("3") == 3
    for bad in ("0", "-1", "101", "x", "1.5"):
        with pytest.raises(ValueError):
            parse_turn(bad)


def test_words_are_single_lowercase_words():
    assert parse_word(" Candy ") == "candy"
    for bad in ("", "a b", "../x", "x;y", "drop)", "w" * 40, "1abc"):
        with pytest.raises(ValueError):
            parse_word(bad)


def test_graph_request_defaults_to_board_6030_and_everyones_memory():
    assert parse_graph_request({}) == GraphRequest(6030, "everyone", None)
    assert parse_graph_request({"seed": "6001", "memory": "w2v", "clue": "Boat"}) == GraphRequest(6001, "w2v", "boat")


@pytest.mark.parametrize("params", [{"seed": "-1"}, {"seed": "abc"}, {"seed": str(10**9 + 1)}, {"memory": "../etc"},
                                    {"memory": "W2V!"}, {"clue": "two words"}])
def test_graph_request_refuses_bad_input(params):
    with pytest.raises(ValueError):
        parse_graph_request(params)
```

- [ ] **Step 2: Write the failing contract tests**

**File:** `tests/contract/test_graphview.py`

```python
"""The 3D view's graph comes from real read-only queries on a memory (database index 15, synthetic data)."""

from __future__ import annotations

import pytest

from codebook import keys
from codebook.board import BoardView
from codebook.graphview import clue_graph
from codebook.harness import board_for_seed
from codebook.memory import Memory

pytestmark = pytest.mark.contract
KINDS = {"direct", "reverse", "chain", "bomb"}


def _board() -> BoardView:
    words, key = board_for_seed(5000)
    return BoardView.from_harness(words, key)


def _linked_clue(population, board: BoardView) -> str:
    """The clue word with the most direct links into this board."""
    q = ("MATCH (c:Word)-[:ASSOC]->(w:Word) WHERE c.clue AND w.text IN $board AND NOT c.text IN $board "
         "RETURN c.text, count(w) AS n ORDER BY n DESC, c.text LIMIT 1")
    return population.ro_query(keys.POPULATION, q, {"board": list(board.words)}).rows[0][0]


def _bomb_clue(population, board: BoardView) -> str | None:
    """A clue word with a chain of one or two links to this board's bomb."""
    q = ("MATCH (c:Word)-[:ASSOC*1..2]->(a:Word {text: $bomb}) WHERE c.clue AND NOT c.text IN $board "
         "RETURN DISTINCT c.text LIMIT 1")
    rows = population.ro_query(keys.POPULATION, q, {"bomb": board.assassin, "board": list(board.words)}).rows
    return rows[0][0] if rows else None


def _graph(population, clue: str, *, revealed=frozenset(), max_via: int = 30) -> tuple[BoardView, dict]:
    board = _board()
    graph = clue_graph(Memory(population), keys.POPULATION, board.words, board.roles, revealed, clue, max_via=max_via)
    return board, graph


def test_every_board_word_is_a_node_with_its_role(population):
    board = _board()
    _, g = _graph(population, _linked_clue(population, board), revealed={board.words[0]})
    nodes = {n["id"]: n for n in g["nodes"]}
    for w, r in zip(board.words, board.roles):
        assert nodes[w]["kind"] == "board" and nodes[w]["role"] == r
    assert nodes[board.words[0]]["revealed"] is True
    assert nodes[board.words[1]]["revealed"] is False
    assert nodes[g["clue"]]["kind"] == "clue"


def test_links_are_typed_and_point_at_nodes(population):
    board = _board()
    _, g = _graph(population, _linked_clue(population, board))
    ids = {n["id"] for n in g["nodes"]}
    assert g["links"], "a clue linked to the board must have links"
    for link in g["links"]:
        assert link["kind"] in KINDS
        assert link["source"] in ids and link["target"] in ids
        assert link["s"] > 0
    assert {link["kind"] for link in g["links"]} & {"direct", "reverse"}
    linked = {link["source"] for link in g["links"]} | {link["target"] for link in g["links"]}
    assert all(n["id"] in linked for n in g["nodes"] if n["kind"] == "via"), "no via word without a link"


def test_the_via_words_are_capped(population):
    board = _board()
    _, g = _graph(population, _linked_clue(population, board), max_via=1)
    on_bomb_path = set((g["bomb_path"] or [])[1:-1])
    assert len({n["id"] for n in g["nodes"] if n["kind"] == "via"} - on_bomb_path) <= 1
    assert len(g["links"]) <= 160


def test_the_path_to_the_bomb_is_marked(population):
    board = _board()
    clue = _bomb_clue(population, board)
    if clue is None:
        pytest.skip("no clue in the synthetic graph reaches this board's bomb")
    _, g = _graph(population, clue)
    assert g["bomb_path"][0] == clue and g["bomb_path"][-1] == board.assassin
    assert any(link["kind"] == "bomb" for link in g["links"])


def test_an_unknown_clue_gives_the_board_and_no_links(population):
    board, g = _graph(population, "zzznotaword")
    assert len([n for n in g["nodes"] if n["kind"] == "board"]) == len(board.words)
    assert g["links"] == [] and g["bomb_path"] is None


def test_a_clue_on_the_board_is_refused(population):
    board = _board()
    with pytest.raises(ValueError):
        clue_graph(Memory(population), keys.POPULATION, board.words, board.roles, set(), board.words[0])
```

- [ ] **Step 3: Run the tests and see them fail**

Run: `uv run pytest -q tests/unit/test_graphview_params.py tests/contract/test_graphview.py`
Expected: an ERROR at collection, `ModuleNotFoundError: No module named 'codebook.graphview'`.

- [ ] **Step 4: Add the query.** In `src/codebook/cypher.py`, insert this block directly after the `CLUE_LINKS = """…"""` block (before the `# Block:` comment above `PATH_TO`):

```python
# The live view's 3D graph: two-step chains from one clue to the board, with the word in between.
# Index-first: bind the clue by its indexed text before expanding (the 6.0.2 planner note above DIRECT).
CLUE_CHAINS = """
MATCH (c:Word) WHERE c.text = $clue
WITH c
MATCH (c)-[r1:ASSOC]->(m:Word)-[r2:ASSOC]->(t:Word)
WHERE t.text IN $board AND m <> c AND t <> c AND m <> t
RETURN m.text AS via, t.text AS word, coalesce(r1.pp, r1.p) * coalesce(r2.pp, r2.p) AS s
ORDER BY s DESC LIMIT $limit
"""
```

Then, in the `ALL` dict, add a new line directly after `    "clue_links": CLUE_LINKS,`:

```python
    "clue_chains": CLUE_CHAINS,
```

- [ ] **Step 5: Write the module**

**File:** `src/codebook/graphview.py`

```python
"""The memory around one clue, as nodes and links for the live view's 3D graph.

Three read-only queries on one memory key: the clue's direct and backwards links to the board (CLUE_LINKS), its
strongest two-step chains (CLUE_CHAINS) and its strongest chain to the bomb (PATH_TO). The request parsing for the
two graph endpoints lives here too, so it is tested without a server.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from codebook import cypher as C
from codebook import keys
from codebook.db import Db
from codebook.memory import Memory

MAX_VIA = 30
MAX_LINKS = 160
MAX_SEED = 10**9
MAX_TURN = 100
DEFAULT_SEED = 6030  # the benchmark board the live view's scenarios use
_WORD = re.compile(r"[a-z][a-z'-]{0,31}")

Links = dict[tuple[str, str, str], float]  # (source, target, kind) -> strength


@dataclass(frozen=True)
class GraphRequest:
    """A checked /api/graph request: which board, whose memory, and (optionally) which clue."""

    seed: int
    memory_of: str  # "everyone" or a partner id
    clue: str | None


def parse_word(value: str) -> str:
    """One lowercase word, as clues and board words are; anything else is refused."""
    word = str(value).strip().lower()
    if not _WORD.fullmatch(word):
        raise ValueError(f"not a single word: {value!r}")
    return word


def parse_turn(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        turn = int(value)
    except ValueError:
        raise ValueError("turn must be a whole number") from None
    if not 1 <= turn <= MAX_TURN:
        raise ValueError(f"turn must be between 1 and {MAX_TURN}")
    return turn


def parse_graph_request(params: Mapping[str, str]) -> GraphRequest:
    try:
        seed = int(params.get("seed", str(DEFAULT_SEED)))
    except ValueError:
        raise ValueError("seed must be a whole number") from None
    if not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be between 0 and {MAX_SEED}")
    memory_of = str(params.get("memory", "everyone"))
    if memory_of != "everyone":
        keys.partner_key(memory_of)  # raises ValueError for a malformed partner id
    clue = params.get("clue")
    return GraphRequest(seed, memory_of, parse_word(clue) if clue else None)


def _keep(links: Links, source: str, target: str, kind: str, s: float) -> None:
    """Keep the strongest link per (source, target, kind)."""
    key = (source, target, kind)
    if s > links.get(key, 0.0):
        links[key] = s


def _add_links(db: Db, read_key: str, clue: str, board: list[str], links: Links) -> None:
    """Direct (clue -> word) and backwards (word -> clue) links between the clue and the board."""
    rows = db.ro_query(read_key, C.CLUE_LINKS, {"clue": clue, "board": board}, name="graph_clue_links").records()
    for row in rows:
        s = float(row["s"] or 0.0)
        if s <= 0:
            continue
        if row["kind"] == 0:
            _keep(links, clue, row["word"], "direct", s)
        else:
            _keep(links, row["word"], clue, "reverse", s)


def _add_chains(db: Db, read_key: str, clue: str, board: list[str], max_via: int, links: Links,
                vias: list[str]) -> None:
    """Two-step chains clue -> via -> board word, with at most `max_via` via words that aren't on the board."""
    params = {"clue": clue, "board": board, "limit": max_via * 4}
    for row in db.ro_query(read_key, C.CLUE_CHAINS, params, name="graph_chains").records():
        via, word, s = row["via"], row["word"], float(row["s"] or 0.0)
        if s <= 0:
            continue
        if via not in board and via not in vias:
            if len(vias) >= max_via:
                continue
            vias.append(via)
        _keep(links, clue, via, "chain", s)
        _keep(links, via, word, "chain", s)


def clue_graph(memory: Memory, read_key: str, words: Sequence[str], roles: Sequence[str], revealed: Collection[str],
               clue: str, *, max_via: int = MAX_VIA) -> dict:
    """Nodes and links around `clue` in the memory at `read_key`, for a board of `words` with `roles`."""
    board = [w.lower() for w in words]
    if clue in board:
        raise ValueError("the clue can't be a word on the board")
    links: Links = {}
    vias: list[str] = []
    _add_links(memory.db, read_key, clue, board, links)
    _add_chains(memory.db, read_key, clue, board, max_via, links, vias)
    bomb = next((w for w, r in zip(board, roles) if r == "assassin"), None)
    found = memory.path_to(read_key, clue, bomb) if bomb else None
    bomb_path = [str(w) for w in found[0]] if found else None
    for a, b in zip(bomb_path or [], (bomb_path or [])[1:]):
        for w in (a, b):
            if w != clue and w not in board and w not in vias:
                vias.append(w)
        _keep(links, a, b, "bomb", found[1])
    ranked = sorted(links.items(), key=lambda item: (item[0][2] != "bomb", -item[1]))[:MAX_LINKS]
    linked = {end for (a, b, _kind), _s in ranked for end in (a, b)}
    nodes = [{"id": w, "kind": "board", "role": r, "revealed": w in revealed} for w, r in zip(board, roles)]
    nodes.append({"id": clue, "kind": "clue"})
    nodes.extend({"id": v, "kind": "via"} for v in vias if v in linked)
    return {"clue": clue, "read_key": read_key, "nodes": nodes, "bomb_path": bomb_path,
            "links": [{"source": a, "target": b, "kind": k, "s": round(s, 8)} for (a, b, k), s in ranked]}
```

- [ ] **Step 6: Run the tests and see them pass**

Run: `uv run pytest -q tests/unit/test_graphview_params.py tests/contract/test_graphview.py`
Expected: all pass. `test_the_path_to_the_bomb_is_marked` may SKIP only if the synthetic graph has no such chain.

- [ ] **Step 7: Commit**

```bash
git add src/codebook/cypher.py src/codebook/graphview.py tests/unit/test_graphview_params.py tests/contract/test_graphview.py
git commit -m "feat: graph view data, a clue's links, chains and bomb path from one memory"
```

---

### Task 2: Graph endpoints and the `/static` mount

**Files:**
- Modify: `src/codebook/web.py` (imports at lines 23-30; `LiveApp` after `suggest()`, line 288; routes at line 354)
- Test: `tests/contract/test_graphview.py` (append), `tests/contract/test_web_routes.py` (create)

**Interfaces:**
- Consumes:
  - from Task 1: `clue_graph`, `GraphRequest`, `parse_graph_request`, `parse_turn`;
  - existing: `LiveGame`, `_current`, `BoardView.from_harness`, `board_for_seed`, `plan`, and `Option.clue`.
- Produces:
  - `LiveApp.game_graph(gid: str, turn: int | None) -> dict`: Task 1's dict plus `turn`. Raises `LookupError` if
    there's no game or clue.
  - `LiveApp.board_graph(req: GraphRequest) -> dict`: Task 1's dict plus `seed`. Raises `ValueError` if there's no
    memory, and `LookupError` if there's no clue.
  - `GET /api/game/{gid}/graph?turn=N` and `GET /api/graph?seed=&memory=&clue=`. Both return 200 with the JSON
    above, or 400/404/503 with `{"error"}`.
  - `GET /static/<file>`.

- [ ] **Step 1: Write the failing `LiveApp` tests.** In `tests/contract/test_graphview.py`:
  - change `from codebook.graphview import clue_graph` to `from codebook.graphview import GraphRequest, clue_graph`;
  - add `from codebook.web import LiveApp, LiveGame` after the `codebook.memory` import;
  - then append:

```python
def test_board_graph_uses_the_memorys_top_clue(population, test_settings):
    g = LiveApp(test_settings).board_graph(GraphRequest(5000, "everyone", None))
    assert g["seed"] == 5000
    assert len([n for n in g["nodes"] if n["kind"] == "board"]) == 25
    assert g["clue"] not in _board().words and any(n["kind"] == "clue" for n in g["nodes"])


def test_board_graph_refuses_a_missing_memory(population, test_settings):
    with pytest.raises(ValueError, match="no memory"):
        LiveApp(test_settings).board_graph(GraphRequest(5000, "nobody-here", None))


def test_game_graph_uses_the_board_as_it_stood_and_joins_the_live_feed(population, test_settings):
    live = LiveApp(test_settings)
    words, key = board_for_seed(5000)
    board = BoardView.from_harness(words, key)
    clue = _linked_clue(population, board)
    game = LiveGame("live-test-1", "glove", "everyone", keys.POPULATION, 5000, "watch", False, "codebook", 0.0,
                    words, key)
    live.games[game.gid] = game
    game.add({"kind": "clue", "turn": 1, "clue": clue})
    game.add({"kind": "guess", "word": board.words[0], "role": board.roles[0]})
    game.add({"kind": "clue", "turn": 2, "clue": clue})

    def revealed(g: dict) -> set[str]:
        return {n["id"] for n in g["nodes"] if n.get("revealed")}

    first = live.game_graph(game.gid, 1)
    latest = live.game_graph(game.gid, None)
    assert first["turn"] == 1 and revealed(first) == set()
    assert latest["turn"] == 2 and revealed(latest) == {board.words[0]}
    assert any(e["kind"] == "query" and e["name"].startswith("graph_") for e in game.since(0))
    with pytest.raises(LookupError):
        live.game_graph(game.gid, 9)
    with pytest.raises(LookupError):
        live.game_graph("no-such-game", None)
```

- [ ] **Step 2: Write the failing route tests**

**File:** `tests/contract/test_web_routes.py`

```python
"""The graph endpoints over HTTP (database index 15, synthetic data): good requests answer, bad ones get a 4xx."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from codebook.web import create_app

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def client(population, test_settings) -> TestClient:
    return TestClient(create_app(test_settings), base_url="http://127.0.0.1")  # a host TrustedHostMiddleware allows


def test_board_graph_route_returns_the_graph(client):
    r = client.get("/api/graph", params={"seed": "5000", "memory": "everyone"})
    assert r.status_code == 200
    body = r.json()
    assert body["seed"] == 5000
    assert len([n for n in body["nodes"] if n["kind"] == "board"]) == 25


@pytest.mark.parametrize("params", [{"clue": "../x"}, {"seed": "abc"}, {"memory": "W2V!"}, {"memory": "nobody-here"}])
def test_board_graph_route_refuses_bad_requests(client, params):
    r = client.get("/api/graph", params={"seed": "5000", **params})
    assert r.status_code == 400
    assert "error" in r.json()


def test_game_graph_route_answers_404_and_400(client):
    assert client.get("/api/game/no-such-game/graph").status_code == 404
    assert client.get("/api/game/no-such-game/graph", params={"turn": "0"}).status_code == 400
```

- [ ] **Step 3: Run them and see them fail**

Run: `uv run pytest -q tests/contract/test_graphview.py tests/contract/test_web_routes.py`
Expected: FAIL. The `LiveApp` tests fail with `AttributeError: 'LiveApp' object has no attribute 'board_graph'`,
and the route tests get 404 for `/api/graph`.

- [ ] **Step 4: Imports.** In `src/codebook/web.py`:
  - replace `from starlette.routing import Route` with:

    ```python
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles
    ```

  - after `from codebook.evaluate import benchmark_game_id`, add:

    ```python
    from codebook.graphview import GraphRequest, clue_graph, parse_graph_request, parse_turn
    ```

- [ ] **Step 5: `LiveApp` methods.** Add these three methods directly after `LiveApp.suggest()`:

```python
    # ---------- the 3D memory graph ----------
    def game_graph(self, gid: str, turn: int | None) -> dict:
        """The memory around one of a game's clues, with the board as it stood when the clue was given."""
        game = self.games.get(gid)
        if game is None:
            raise LookupError("no such game")
        events = game.since(0)
        clues = [e for e in events if e.get("kind") == "clue" and (turn is None or e.get("turn") == turn)]
        if not clues:
            raise LookupError("no clue yet" if turn is None else f"no clue for turn {turn}")
        clue = clues[-1]
        revealed = {e["word"] for e in events if e.get("kind") == "guess" and e["i"] < clue["i"]}
        board = BoardView.from_harness(game.words, game.key)
        previous = getattr(_current, "game", None)
        _current.game = game  # the graph's queries join this game's Live Cypher feed
        try:
            graph = clue_graph(self.memory, game.read_key, board.words, board.roles, revealed, clue["clue"])
        finally:
            _current.game = previous
        return {**graph, "turn": clue["turn"]}

    def board_graph(self, req: GraphRequest) -> dict:
        """The memory around a clue on a seeded board: the given clue, or this memory's top suggestion."""
        words, key = board_for_seed(req.seed)
        board = BoardView.from_harness(words, key)
        read_key = keys.POPULATION if req.memory_of == "everyone" else keys.partner_key(req.memory_of)
        if not self.db.exists(read_key):
            raise ValueError(f"no memory for {req.memory_of!r}")
        clue = req.clue or self._top_clue(read_key, board, req.seed)
        return {**clue_graph(self.memory, read_key, board.words, board.roles, set(), clue), "seed": req.seed}

    def _top_clue(self, read_key: str, board: BoardView, seed: int) -> str:
        model = self.memory.model(read_key)
        options = plan(board, self.memory.features(read_key, board, model).rows, model, seed=seed)
        if not options:
            raise LookupError("this memory has no clue for this board")
        return options[0].clue
```

- [ ] **Step 6: Routes.** In `create_app()`, directly before `routes = [`, add:

```python
    def graph_response(build):
        try:
            return ok(build())
        except DbError:
            return ok({"error": "the memory database is unavailable"}, 503)
        except LookupError as exc:
            return ok({"error": str(exc)}, 404)
        except ValueError as exc:
            return ok({"error": str(exc)}, 400)

    def game_graph(request: Request):
        return graph_response(lambda: live.game_graph(request.path_params["gid"],
                                                      parse_turn(request.query_params.get("turn"))))

    def board_graph(request: Request):
        return graph_response(lambda: live.board_graph(parse_graph_request(request.query_params)))
```

Then add these three entries at the end of the `routes = [...]` list, after `Route("/api/suggest", suggest),`:

```python
        Route("/api/game/{gid}/graph", game_graph),
        Route("/api/graph", board_graph),
        Mount("/static", app=StaticFiles(directory=STATIC), name="static"),
```

- [ ] **Step 7: Run the tests and see them pass**

Run: `uv run pytest -q`
Expected: every test passes (the 54 existing ones and the new ones).

- [ ] **Step 8: Commit**

```bash
git add src/codebook/web.py tests/contract/test_graphview.py tests/contract/test_web_routes.py
git commit -m "feat: graph endpoints for a game turn and a seeded board; serve /static"
```

---

### Task 3: The page shell (`index.html` + `app.css`)

**Files:**
- Rewrite: `src/codebook/static/index.html`
- Create: `src/codebook/static/app.css`

**Interfaces:**
- Produces:
  - **DOM ids used by later tasks:** the preserved list plus `openScenarios openTour openCustom scenarios
    closeScenarios tourbtn custom closeCustom graph3d graphinfo nodecard narration result tabscard tabexplain
    gamecard tour tourspot tourtip tourstep tourtext tourback tournext tourskip tooltip qsum cmpgo tab-queries
    tab-memory tab-compare tab-all`.
  - **Classes:** `.scenario[data-scenario=memories|handover|play|explore]`, `.drawer.open`, `.hidden`, `.clue`.

- [ ] **Step 1: Write the markup**

**File:** `src/codebook/static/index.html`

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codebook · live view</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rubik:ital,wght@0,500;0,700;0,800;1,800&family=Nunito+Sans:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header class="topbar">
  <div class="brand">
    <svg class="mark" viewBox="0 0 100 100" aria-hidden="true"><rect x="6" y="6" width="88" height="88" rx="22" fill="#0E1430" stroke="#7EA2F2" stroke-width="4"/><g stroke="#7EA2F2" stroke-width="4" stroke-linecap="round"><line x1="30" y1="32" x2="70" y2="40"/><line x1="70" y1="40" x2="58" y2="72"/><line x1="58" y1="72" x2="28" y2="64"/><line x1="28" y1="64" x2="30" y2="32"/><line x1="30" y1="32" x2="58" y2="72"/></g><circle cx="30" cy="32" r="7" fill="#F4EFE4"/><circle cx="70" cy="40" r="9" fill="#F28C38"/><circle cx="58" cy="72" r="7" fill="#F4EFE4"/><circle cx="28" cy="64" r="7" fill="#F4EFE4"/></svg>
    <div><h1>Code<span>book</span></h1><p class="tag">One memory per partner, each a graph in FalkorDB</p></div>
  </div>
  <nav class="actions">
    <button class="ghost" id="openScenarios" type="button">Scenarios</button>
    <button class="ghost" id="openTour" type="button">60-second tour</button>
    <button class="primary" id="openCustom" type="button">Custom game</button>
  </nav>
</header>

<main class="stage">
  <section class="col">
    <article class="card" id="gamecard">
      <header class="card-head">
        <h2>The board <button class="info" type="button" aria-label="About the board" data-tip="Codenames: Codebook gives a one-word clue and a number; the partner picks that many words. Blue cards are our team's, orange the other team's, grey neutral. Picking the dark card, the bomb, loses the game.">i</button></h2>
        <div class="status" id="status" role="status"></div>
      </header>
      <div class="muted gameinfo" id="gameinfo">Pick a scenario to start.</div>
      <div class="board" id="board"></div>
      <div class="legend" aria-label="Card colours">
        <span><i class="sw team"></i>our team</span><span><i class="sw opponent"></i>other team</span><span><i class="sw neutral"></i>neutral</span><span><i class="sw assassin"></i>the bomb</span>
      </div>
      <div class="clue"><span class="label">clue</span><span class="word" id="clueword">&nbsp;</span><span class="meta" id="cluemeta"></span></div>
      <p class="narration" id="narration" aria-live="polite">Codebook reads its memory of a partner, picks a clue, and learns from the guesses.</p>
      <div class="your-turn hidden" id="yourturn">Your turn: click a word. <button class="ghost" id="endturn" type="button">End turn</button></div>
      <div class="result hidden" id="result"></div>
      <div class="blocks" id="blocks"></div>
      <div class="log" id="log"></div>
    </article>
  </section>

  <section class="col">
    <article class="card graph-card" id="graphcard">
      <header class="card-head">
        <h2>This partner's memory, live <button class="info" type="button" aria-label="About the memory graph" data-tip="The words around the current clue in the memory Codebook is reading: a real FalkorDB graph, fetched with three read-only Cypher queries. Drag to turn it, scroll to zoom, click a word to see its links.">i</button></h2>
        <span class="muted" id="graphinfo">from FalkorDB</span>
      </header>
      <div class="graph" id="graph3d"><p class="graph-empty">Start a game: the words around each clue appear here, straight from the partner's graph.</p></div>
      <div class="legend links" aria-label="Link kinds">
        <span><i class="ln direct"></i>direct</span><span><i class="ln reverse"></i>backwards</span><span><i class="ln chain"></i>two steps</span><span><i class="ln bomb"></i>path to the bomb</span>
      </div>
      <div class="nodecard hidden" id="nodecard"></div>
    </article>

    <article class="card" id="tabscard">
      <div class="tabs" role="tablist">
        <button data-tab="queries" class="on" type="button">Live Cypher</button>
        <button data-tab="memory" type="button">Partner memory</button>
        <button data-tab="compare" type="button">Compare memories</button>
        <button data-tab="all" type="button">All queries</button>
      </div>
      <p class="explain" id="tabexplain"></p>
      <div id="tab-queries"><div class="muted" id="qsum">Queries for the current game appear here, newest first.</div><div id="qlist"></div></div>
      <div id="tab-memory" class="hidden"></div>
      <div id="tab-compare" class="hidden"><div class="cmp-bar"><input id="cmpmems" placeholder="everyone,w2v,persona-leaper" aria-label="Memories to compare"><button class="ghost" id="cmpgo" type="button">Compare</button></div><div id="cmp"></div></div>
      <div id="tab-all" class="hidden"></div>
    </article>
  </section>
</main>

<div class="overlay hidden" id="scenarios" role="dialog" aria-modal="true" aria-labelledby="sc-title">
  <div class="sheet">
    <p class="kicker">Graph Hacks 2026 · Track 02 · Agent memory</p>
    <h2 id="sc-title">Every partner gets their own <span>codebook</span>.</h2>
    <p class="lead">Codebook is an AI clue-giver for the word game Codenames. It keeps <b>one memory per partner</b>, a graph in FalkorDB, learns how that partner thinks from every guess, and plays better with them. Pick a scenario: each one is a real game.</p>
    <div class="cards">
      <button class="scenario" data-scenario="memories" type="button"><span class="num">1</span><h3>Same board, two memories</h3><p>A bot plays board 6030 with everyone's memory, then with its own. Watch the bomb, then the win.</p><span class="foot">about 60 s · real benchmark games</span></button>
      <button class="scenario" data-scenario="handover" type="button"><span class="num">2</span><h3>Another AI takes over</h3><p>Claude Sonnet gives the clues, choosing from the bot's memory through Codebook's tools.</p><span class="foot">about 20 s · replayed from the log</span></button>
      <button class="scenario" data-scenario="play" type="button"><span class="num">3</span><h3>Play it yourself</h3><p>You guess. Every pick changes your own memory, a new graph in FalkorDB.</p><span class="foot">your pace · learning on</span></button>
      <button class="scenario" data-scenario="explore" type="button"><span class="num">4</span><h3>Explore a memory</h3><p>See a partner's graph around a board in 3D, and compare the clue each memory picks.</p><span class="foot">instant · no game</span></button>
    </div>
    <div class="sheet-foot"><button class="primary" id="tourbtn" type="button">Take the 60-second tour</button><button class="ghost" id="closeScenarios" type="button">Just look around</button></div>
  </div>
</div>

<aside class="drawer" id="custom" aria-hidden="true" aria-labelledby="custom-title">
  <h2 id="custom-title">Custom game</h2>
  <p class="explain">Any partner, any memory, any board. The same board seed always deals the same board.</p>
  <label>Partner <small>who guesses</small><select id="partner"></select></label>
  <label>Memory <small>whose memory Codebook reads</small><select id="memory"><option value="own">their own</option><option value="everyone">everyone's</option></select></label>
  <label>Board seed <small>6000-6199 are the benchmark's test boards</small><input id="seed" type="number" value="6030"></label>
  <label>Clue-giver<select id="giver"><option value="codebook">Codebook</option><option value="claude-sonnet">Claude Sonnet (+memory)</option><option value="claude">Claude Haiku (+memory)</option><option value="codex">Codex (+memory)</option></select></label>
  <label class="check"><input id="learn" type="checkbox"> Learn from this game <small>writes to the partner's own memory</small></label>
  <label class="check" title="With an AI clue-giver: take its clues from the final run's log, so the logged game replays live"><input id="replay" type="checkbox"> Replay the AI's logged clues</label>
  <label>Speed<select id="delay"><option value="1.2">slow</option><option value="0.5" selected>normal</option><option value="0">fast</option></select></label>
  <div class="drawer-foot"><button class="primary" id="start" type="button">Start game</button><button class="ghost" id="closeCustom" type="button">Close</button></div>
</aside>

<div class="tour hidden" id="tour" role="dialog" aria-live="polite">
  <div class="tour-spot" id="tourspot"></div>
  <div class="tour-tip" id="tourtip"><p class="tour-step" id="tourstep"></p><p id="tourtext"></p>
    <div class="tour-nav"><button class="ghost" id="tourback" type="button">Back</button><button class="primary" id="tournext" type="button">Next</button><button class="link" id="tourskip" type="button">Skip</button></div></div>
</div>
<div class="tooltip hidden" id="tooltip" role="tooltip"></div>

<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js" integrity="sha384-XmJ9SoHtVOHoQUcKvFAzVXwdkKo1Ie3bhmSoIAkcdsHGaIrVJIkmozyq0FJeb/Ly" crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/3d-force-graph@1.80.1/dist/3d-force-graph.min.js" integrity="sha384-i98VDQKdpyVrtyuFn0fjUWJBLBmxnqHqOANcvYe9HLJUgT2wPixa4ZkLd7Dh3VEk" crossorigin="anonymous"></script>
<script src="/static/graph3d.js"></script>
<script src="/static/tour.js"></script>
<script src="/static/app.js"></script>
<script src="/static/panels.js"></script>
<script src="/static/scenarios.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write the styles**

**File:** `src/codebook/static/app.css`

```css
/* Codebook live view: dark stage, glass cards, the board, the 3D memory graph, overlays and the tour. */
:root {
  color-scheme: dark;
  --bg: #070A16; --bg2: #0E1430; --card: rgba(21, 26, 46, 0.82); --raise: #1B2242;
  --line: rgba(244, 239, 228, 0.12); --line-strong: rgba(244, 239, 228, 0.22);
  --ink: #F4EFE4; --muted: #9AA3C7; --dim: #6B7392;
  --blue: #7EA2F2; --blue-deep: #2F5BC2; --orange: #F28C38; --red: #FF4D5E; --green: #3DDC97; --lilac: #D7A6FF; --gold: #F2B84B;
  --neutral: #4A5068; --bomb: #05060C;
  --radius: 18px; --shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
  --display: 'Rubik', Arial, sans-serif; --body: 'Nunito Sans', Arial, sans-serif; --mono: 'JetBrains Mono', Consolas, monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  min-height: 100vh; color: var(--ink); font: 15px/1.5 var(--body);
  background: radial-gradient(1200px 700px at 15% -10%, rgba(47, 91, 194, 0.35), transparent 60%),
              radial-gradient(900px 700px at 110% 20%, rgba(242, 140, 56, 0.14), transparent 60%), var(--bg);
  background-attachment: fixed;
}
button { font: 700 14px var(--body); border: 0; border-radius: 12px; padding: 10px 16px; cursor: pointer; color: var(--ink); background: var(--raise); transition: transform .15s, background .2s, border-color .2s, box-shadow .2s; }
button:hover { transform: translateY(-1px); }
button:focus-visible, select:focus-visible, input:focus-visible { outline: 3px solid var(--blue); outline-offset: 2px; }
button.primary { background: linear-gradient(135deg, var(--blue-deep), #4B78E0); color: #fff; box-shadow: 0 8px 24px rgba(47, 91, 194, 0.45); }
button.ghost { background: transparent; border: 1px solid var(--line-strong); }
button.ghost:hover { border-color: var(--blue); }
button.link { background: none; color: var(--muted); padding: 10px 6px; }
button:disabled { opacity: .4; cursor: default; transform: none; }
select, input { font: 600 14px var(--body); color: var(--ink); background: var(--bg2); border: 1px solid var(--line-strong); border-radius: 10px; padding: 8px 10px; width: 100%; }
input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--blue); }
.hidden { display: none !important; }
.muted { color: var(--muted); }

/* top bar */
.topbar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding: 14px 28px; background: rgba(7, 10, 22, 0.72); backdrop-filter: blur(14px); border-bottom: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 14px; }
.brand .mark { width: 44px; height: 44px; }
.brand h1 { margin: 0; font: 800 26px var(--display); letter-spacing: -0.5px; }
.brand h1 span { color: var(--blue); }
.brand .tag { margin: 0; color: var(--muted); font-size: 13px; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; }

/* stage */
.stage { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.08fr); gap: 22px; padding: 22px 28px 40px; max-width: 1760px; margin: 0 auto; }
.col { display: flex; flex-direction: column; gap: 22px; min-width: 0; }
@media (max-width: 1100px) { .stage { grid-template-columns: 1fr; padding: 16px; } .topbar { padding: 12px 16px; } }
.card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px 20px; box-shadow: var(--shadow); backdrop-filter: blur(10px); }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.card-head h2 { margin: 0; font: 800 18px var(--display); display: flex; align-items: center; gap: 8px; }
.info { width: 22px; height: 22px; padding: 0; border-radius: 50%; font: 800 12px var(--display); background: var(--raise); color: var(--muted); border: 1px solid var(--line-strong); }
.explain { margin: 0 0 10px; color: var(--muted); font-size: 13px; }
.gameinfo { font-size: 13px; margin-bottom: 12px; min-height: 20px; }
.status { font: 800 14px var(--display); }
.status.won { color: var(--green); }
.status.lost, .status.error { color: var(--red); }

/* board */
.board { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; perspective: 900px; }
.tile { position: relative; display: flex; align-items: center; justify-content: center; min-height: 64px; padding: 10px 6px; border-radius: 12px;
  font: 800 14px var(--display); letter-spacing: .8px; text-align: center; overflow-wrap: anywhere; background: linear-gradient(180deg, #1D2546, #161C38);
  border: 1px solid var(--line); box-shadow: 0 6px 16px rgba(0, 0, 0, .35), inset 0 1px 0 rgba(255, 255, 255, .05); transform-style: preserve-3d;
  transition: background .3s, color .3s, box-shadow .3s; }
.tile.keyed::after { content: ""; position: absolute; left: 10px; right: 10px; bottom: 7px; height: 4px; border-radius: 2px; opacity: .9; }
.tile.keyed.team::after { background: var(--blue); }
.tile.keyed.opponent::after { background: var(--orange); }
.tile.keyed.neutral::after { background: var(--neutral); }
.tile.keyed.assassin::after { background: var(--red); }
.tile.target { box-shadow: 0 0 0 3px var(--blue), 0 0 24px rgba(126, 162, 242, .45); }
.tile.r-team { background: linear-gradient(180deg, #8DB0FF, var(--blue)); color: #0B1024; }
.tile.r-opponent { background: linear-gradient(180deg, #FFA45C, var(--orange)); color: #1A0E04; }
.tile.r-neutral { background: #3A4262; color: var(--muted); }
.tile.r-assassin { background: var(--bomb); color: #fff; box-shadow: 0 0 0 3px var(--red), 0 0 34px rgba(255, 77, 94, .6); }
.tile.r-assassin::before { content: "BOMB"; position: absolute; bottom: 6px; font-size: 10px; letter-spacing: 2px; color: var(--red); }
.tile.clickable { cursor: pointer; }
.tile.clickable:hover { transform: translateY(-3px); border-color: var(--blue); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 12px 0 2px; font-size: 12px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 14px; height: 14px; border-radius: 4px; display: inline-block; }
.sw.team { background: var(--blue); }
.sw.opponent { background: var(--orange); }
.sw.neutral { background: var(--neutral); }
.sw.assassin { background: var(--bomb); box-shadow: 0 0 0 2px var(--red); }
.ln { width: 22px; height: 3px; border-radius: 2px; display: inline-block; }
.ln.direct { background: var(--blue); }
.ln.reverse { background: #9DD3FF; }
.ln.chain { background: var(--lilac); }
.ln.bomb { background: var(--red); }

/* clue, narration, result, blocks, log */
.clue { display: flex; flex-wrap: wrap; align-items: baseline; gap: 14px; margin: 16px 0 6px; }
.clue .label { font: 800 11px var(--body); letter-spacing: 3px; text-transform: uppercase; color: var(--muted); }
.clue .word { font: italic 800 46px var(--display); letter-spacing: -1px; display: inline-block; }
.clue .meta { color: var(--muted); font-size: 14px; }
.clue .meta b { color: var(--ink); }
.narration { margin: 8px 0 4px; padding: 12px 16px; border-radius: 12px; background: rgba(126, 162, 242, .08); border-left: 4px solid var(--blue); font-weight: 700; min-height: 48px; }
.narration.good { background: rgba(61, 220, 151, .10); border-left-color: var(--green); }
.narration.bad { background: rgba(255, 77, 94, .10); border-left-color: var(--red); }
.your-turn { margin-top: 12px; display: flex; gap: 12px; align-items: center; font-weight: 800; color: var(--orange); }
.result { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.res { padding: 14px 16px; border-radius: 14px; background: var(--raise); border: 1px solid var(--line); }
.res span { display: block; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px; }
.res b { font: 800 18px var(--display); }
.res.won { border-color: var(--green); }
.res.won b { color: var(--green); }
.res.lost { border-color: var(--red); }
.res.lost b { color: var(--red); }
.blocks { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; max-height: 210px; overflow: auto; }
.block { border-left: 4px solid var(--red); background: rgba(255, 77, 94, .08); border-radius: 8px; padding: 6px 10px; font-size: 13px; }
.block b { font-family: var(--mono); }
.log { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; max-height: 240px; overflow: auto; }
.turn { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; }
.turn .c { font: 800 13px var(--display); min-width: 130px; }
.chip { border-radius: 999px; padding: 2px 10px; font-weight: 800; font-size: 12px; }
.chip.team { background: var(--blue); color: #0B1024; }
.chip.opponent { background: var(--orange); color: #1A0E04; }
.chip.neutral { background: var(--neutral); color: var(--ink); }
.chip.assassin { background: var(--bomb); color: #fff; box-shadow: 0 0 0 1px var(--red); }

/* 3D graph */
.graph-card { padding-bottom: 14px; }
.graph { position: relative; height: 440px; border-radius: 14px; overflow: hidden; border: 1px solid var(--line);
  background: radial-gradient(600px 300px at 50% 40%, rgba(47, 91, 194, .18), transparent 70%), #0A0F24; }
.graph canvas { display: block; }
.graph-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 30px; margin: 0; text-align: center; color: var(--muted); font-weight: 700; }
.graph-labels { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.glabel { position: absolute; left: 0; top: 0; transform: translate(-9999px, 0); margin: -9px 0 0 10px; font: 800 11px var(--display); letter-spacing: .6px; color: var(--muted); white-space: nowrap; text-shadow: 0 1px 4px #000; }
.glabel.board { color: #C9CEDD; }
.glabel.board.revealed.team { color: var(--blue); }
.glabel.board.assassin { color: var(--red); }
.glabel.aim { color: #fff; font-size: 13px; }
.glabel.clue { font-size: 18px; color: var(--gold); margin: -14px 0 0 16px; }
.glabel.via { font: 600 10px var(--body); color: var(--dim); }
.graph-fallback { padding: 18px; font-size: 13px; overflow: auto; height: 100%; }
.graph-fallback ol { margin: 8px 0; padding-left: 20px; }
.k { font: 700 11px var(--mono); padding: 1px 6px; border-radius: 6px; background: var(--raise); }
.k.direct { color: var(--blue); }
.k.reverse { color: #9DD3FF; }
.k.chain { color: var(--lilac); }
.k.bomb { color: var(--red); }
.bombline { color: var(--red); font-weight: 800; }
.nodecard { margin-top: 10px; padding: 10px 14px; border-radius: 12px; background: var(--raise); border: 1px solid var(--line); font-size: 13px; }
.nodecard ul { margin: 6px 0 0; padding-left: 18px; }

/* tabs */
.tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.tabs button { background: transparent; color: var(--muted); border: 1px solid var(--line); padding: 7px 13px; border-radius: 999px; }
.tabs button.on { background: var(--blue-deep); color: #fff; border-color: var(--blue-deep); }
#qlist { max-height: 360px; overflow: auto; }
.q { border: 1px solid var(--line); border-radius: 10px; margin-bottom: 6px; background: rgba(10, 15, 36, .6); }
.q summary { cursor: pointer; padding: 7px 10px; display: flex; gap: 10px; align-items: center; font-size: 13px; list-style: none; }
.q summary .n { font: 700 13px var(--mono); color: var(--blue); min-width: 120px; }
.q summary .k { color: var(--muted); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; background: none; font: 400 12px var(--body); padding: 0; }
.q pre { margin: 0; padding: 8px 10px; border-top: 1px solid var(--line); font: 12px/1.55 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; color: #DCE4F7; }
.q .p { color: var(--muted); }
.bars { display: grid; grid-template-columns: 70px 1fr 50px; gap: 8px 10px; align-items: center; font-size: 13px; margin: 8px 0 14px; }
.bar { height: 10px; border-radius: 5px; background: var(--raise); position: relative; overflow: hidden; }
.bar i { position: absolute; left: 0; top: 0; bottom: 0; background: linear-gradient(90deg, var(--blue-deep), var(--blue)); border-radius: 5px; }
.bar s { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--orange); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 6px; border-bottom: 1px solid var(--line); }
th { font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); }
td.m, .m { font-family: var(--mono); }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 10px; }
.stat { background: var(--raise); border-radius: 12px; padding: 10px; }
.stat b { display: block; font: 800 22px var(--display); }
.stat span { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }
.cmp-bar { display: flex; gap: 8px; margin-bottom: 10px; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.cmp-col h4 { margin: 4px 0 8px; font: 800 14px var(--display); color: var(--muted); }
.opt { background: var(--raise); border-radius: 10px; padding: 9px; margin-bottom: 6px; font-size: 13px; border: 1px solid transparent; }
.opt.top { border-color: var(--blue); }
.opt b { font: 800 16px var(--display); }

/* start screen */
.overlay { position: fixed; inset: 0; z-index: 50; display: flex; align-items: center; justify-content: center; padding: 24px; background: rgba(7, 10, 22, 0.78); backdrop-filter: blur(10px); }
.sheet { width: min(1180px, 100%); max-height: calc(100vh - 48px); overflow: auto; padding: 34px 36px; border-radius: 26px; background: linear-gradient(180deg, #121937, #0B1024); border: 1px solid var(--line-strong); box-shadow: 0 40px 120px rgba(0, 0, 0, .6); }
.kicker { margin: 0; font: 800 12px var(--body); letter-spacing: 3px; text-transform: uppercase; color: var(--blue); }
.sheet h2 { margin: 8px 0 10px; font: italic 800 44px/1.1 var(--display); letter-spacing: -1px; }
.sheet h2 span { color: var(--blue); }
.lead { margin: 0 0 22px; max-width: 860px; color: #C9CEDD; font-size: 17px; }
.lead b { color: var(--ink); }
.cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
@media (max-width: 1000px) { .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .cards { grid-template-columns: 1fr; } .sheet { padding: 24px 16px; } .sheet h2 { font-size: 32px; } }
.scenario { text-align: left; display: flex; flex-direction: column; gap: 8px; padding: 18px; border-radius: 18px; background: var(--raise); border: 1px solid var(--line-strong); color: var(--ink); min-height: 220px; }
.scenario:hover { border-color: var(--blue); transform: translateY(-4px); box-shadow: 0 16px 40px rgba(47, 91, 194, .35); }
.scenario .num { width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: var(--blue-deep); font: 800 16px var(--display); }
.scenario h3 { margin: 4px 0 0; font: 800 19px var(--display); }
.scenario p { margin: 0; color: #C9CEDD; font: 600 14px/1.45 var(--body); flex: 1; }
.scenario .foot { font: 700 12px var(--body); color: var(--muted); }
.sheet-foot { display: flex; gap: 12px; margin-top: 22px; flex-wrap: wrap; }

/* custom game drawer */
.drawer { position: fixed; top: 0; right: 0; bottom: 0; z-index: 40; width: min(400px, 100%); padding: 26px 24px; overflow: auto;
  background: #0E1430; border-left: 1px solid var(--line-strong); box-shadow: -30px 0 80px rgba(0, 0, 0, .5); transform: translateX(105%); transition: transform .35s cubic-bezier(.2, .8, .2, 1); }
.drawer.open { transform: translateX(0); }
.drawer h2 { margin: 0 0 6px; font: 800 22px var(--display); }
.drawer label { display: flex; flex-direction: column; gap: 5px; margin: 12px 0; font-size: 12px; font-weight: 800; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); }
.drawer label small { text-transform: none; letter-spacing: 0; font-weight: 600; color: var(--dim); }
.drawer label.check { flex-direction: row; align-items: center; gap: 10px; text-transform: none; letter-spacing: 0; font-size: 14px; color: var(--ink); }
.drawer-foot { display: flex; gap: 10px; margin-top: 18px; }

/* tour and tooltips */
.tour { position: fixed; inset: 0; z-index: 60; }
.tour-spot { position: fixed; border-radius: 16px; box-shadow: 0 0 0 9999px rgba(7, 10, 22, .74), 0 0 0 3px var(--blue), 0 0 40px rgba(126, 162, 242, .6); transition: all .35s cubic-bezier(.2, .8, .2, 1); pointer-events: none; }
.tour-tip { position: fixed; width: min(400px, calc(100vw - 32px)); padding: 16px 18px; border-radius: 16px; background: #121937; border: 1px solid var(--line-strong); box-shadow: var(--shadow); }
.tour-step { margin: 0 0 4px; font: 800 12px var(--body); letter-spacing: 2px; text-transform: uppercase; color: var(--blue); }
.tour-tip p { margin: 0 0 12px; }
.tour-nav { display: flex; gap: 8px; align-items: center; }
.tooltip { position: fixed; z-index: 70; max-width: 320px; padding: 10px 12px; border-radius: 10px; background: #121937; border: 1px solid var(--line-strong); font-size: 13px; box-shadow: var(--shadow); pointer-events: none; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
}
```

- [ ] **Step 3: Check it's served.** Start the live view (`uv run codebook ui`), then fetch the stylesheet and the page:

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7811/static/app.css && curl -s http://127.0.0.1:7811/ | grep -c 'id="graph3d"'`
Expected: `200`, then `1`. The page's scripts 404 until Tasks 4 and 5 add them, which is expected.

- [ ] **Step 4: Commit**

```bash
git add src/codebook/static/index.html src/codebook/static/app.css
git commit -m "feat: new live view shell, design system, start screen, drawer and tour layers"
```

---

### Task 4: The 3D graph and the tour (`graph3d.js`, `tour.js`)

**Files:**
- Create: `src/codebook/static/graph3d.js`, `src/codebook/static/tour.js`

**Interfaces:**
- Consumes: Task 3's ids `tour tourspot tourtip tourstep tourtext tourback tournext tourskip`, and the globals
  `ForceGraph3D` and `gsap` (either may be missing).
- Produces:
  - `window.CodebookGraph`:
    - `mount(el, onPick)`, where `onPick(id, links)` receives links shaped `{from, to, kind, s}`;
    - `show(graph, aimWords)`, where `graph` is Task 2's response;
    - `reveal(word)`, `clear(message)`;
    - `stats() -> {mode: 'empty'|'3d'|'fallback', nodes, links}`.
  - `window.CodebookTour`:
    - `start(steps, onEnd)`, where `steps` is `[{el: selector | () => Element, title, text}]`;
    - `end()`, `isOpen()`.

- [ ] **Step 1: Write the graph module**

**File:** `src/codebook/static/graph3d.js`

```javascript
// The partner's memory around the current clue, in 3D (3d-force-graph on three.js), with a 2D fallback.
// window.CodebookGraph = { mount(el, onPick), show(graph, aim), reveal(word), clear(message), stats() }
(function () {
  'use strict';
  const ROLE = { team: '#7EA2F2', opponent: '#F28C38', neutral: '#8A91AB', assassin: '#FF4D5E' };
  const ROLE_DIM = { team: '#3E5590', opponent: '#8A5426', neutral: '#4A5068', assassin: '#A3303C' };
  const LINK = { direct: '#7EA2F2', reverse: '#9DD3FF', chain: '#D7A6FF', bomb: '#FF4D5E' };
  const FALLBACK_ROWS = 14;
  const FLIGHT_MS = 1200;
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

  function flyToClue() {
    const n = data.nodes.find((x) => x.id === clue);
    if (!fg || !n || n.x === undefined) return;
    const k = 1 + 240 / (Math.hypot(n.x, n.y, n.z) || 1);
    fg.cameraPosition({ x: n.x * k, y: n.y * k, z: n.z * k + 60 }, { x: n.x, y: n.y, z: n.z }, reduced ? 0 : FLIGHT_MS);
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
      .onNodeClick((n) => onPick && onPick(n.id, linksOf(n.id)))
      .onEngineStop(() => {
        if (!flyPending) return;
        flyPending = false;
        flyToClue();
      });
    fg.d3Force('charge').strength(-90);
    labelLayer = document.createElement('div');
    labelLayer.className = 'graph-labels';
    host.appendChild(labelLayer);
    new ResizeObserver(() => fg && fg.width(host.clientWidth).height(host.clientHeight)).observe(host);
    requestAnimationFrame(followLabels);
    return fg;
  }

  function makeLabels() {
    labelLayer.textContent = '';
    labels = new Map();
    for (const n of data.nodes) {
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
```

- [ ] **Step 2: Write the tour module**

**File:** `src/codebook/static/tour.js`

```javascript
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
```

- [ ] **Step 3: Check the syntax**

Run: `node --check src/codebook/static/graph3d.js && node --check src/codebook/static/tour.js`
Expected: no output (both files parse).

- [ ] **Step 4: Commit**

```bash
git add src/codebook/static/graph3d.js src/codebook/static/tour.js
git commit -m "feat: 3D memory graph view with labels and 2D fallback; coach-mark tour"
```

---

### Task 5: The app (`app.js`, `panels.js`, `scenarios.js`) and the browser smoke test

**Files:**
- Create: `src/codebook/static/app.js`, `src/codebook/static/panels.js`, `src/codebook/static/scenarios.js`
- Create: `../codebook-video/scripts/ui_smoke.mjs`
- Test: `tests/contract/test_web_routes.py` (append)

**Interfaces:**
- Consumes: Task 4's `CodebookGraph` and `CodebookTour`; Task 2's endpoints; Task 3's ids.
- Produces:
  - `window.CB` with:
    - helpers: `$`, `num`, `esc`, `anim`, `api`, `post`, `say`, `POLL_MS`;
    - game: `loadPartners`, `renderBoard`, `startGame`, `poll`, `finish`, `handle`, `guess`, `loadGraph(turn | null, aim)`;
    - views: `gameInfo`, `endStatus`, `resetGameView`, `showError`;
    - hooks: `on('start' | 'end', fn)`;
    - set by panels.js: `addQuery`, `showMemory`, `compare`, `allQueries`, `showTab`;
    - set by scenarios.js: `closeDrawer`.

- [ ] **Step 1: Write the failing tests first.** Both fail until the app exists.

Append to `tests/contract/test_web_routes.py` (and add `import re` under `from __future__ import annotations`):

```python
def test_the_page_and_every_file_it_loads_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and 'id="graph3d"' in page.text
    files = re.findall(r'"/static/([\w.-]+)"', page.text)
    assert {"app.css", "app.js", "graph3d.js", "tour.js", "panels.js", "scenarios.js"} <= set(files)
    for name in files:
        assert client.get(f"/static/{name}").status_code == 200, name
```

**File:** `../codebook-video/scripts/ui_smoke.mjs`

```javascript
// Browser smoke test for the redesigned live view. Needs `uv run codebook ui` on 127.0.0.1:7811.
// Usage (from the codebook-video folder, which has puppeteer-core): node scripts/ui_smoke.mjs
// Check 5 leaves one human game waiting for a guess; the server ends it after 5 minutes (HUMAN_WAIT_S).
import puppeteer from "puppeteer-core";

const BASE = process.env.CODEBOOK_UI || "http://127.0.0.1:7811";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const IDS = ["partner", "memory", "seed", "giver", "learn", "replay", "delay", "start", "board", "clueword", "cluemeta",
  "status", "blocks", "log", "yourturn", "endturn", "qlist", "cmp", "cmpmems", "gameinfo", "graph3d", "narration"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
const check = (ok, what) => {
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
  if (!ok) failures.push(what);
};

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true, defaultViewport: { width: 1600, height: 1000 },
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});

async function fresh(blockCdn = false) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  if (blockCdn) {
    await page.setRequestInterception(true);
    page.on("request", (r) => (r.url().includes("cdn.jsdelivr.net") ? r.abort() : r.continue()));
  }
  return { ctx, page, errors };
}

async function startScenario(page, name) {
  await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#scenarios:not(.hidden)", { timeout: 15000 });
  await page.click(`.scenario[data-scenario="${name}"]`);
}

const statusMatches = (page, source, ms = 180000) =>
  page.waitForFunction((src) => new RegExp(src).test(document.getElementById("status").textContent), { timeout: ms }, source);

try {
  { // 1-2. a first visit shows the start screen; ids preserved; scenario 1 compares two memories in 3D
    const { ctx, page, errors } = await fresh();
    await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
    await page.waitForSelector("#scenarios:not(.hidden)", { timeout: 15000 });
    check((await page.$$(".scenario")).length === 4, "a first visit shows the start screen with four scenarios");
    const missing = await page.evaluate((ids) => ids.filter((id) => !document.getElementById(id)), IDS);
    check(missing.length === 0, `preserved element ids are all present ${missing.join(",")}`);
    await page.click('.scenario[data-scenario="memories"]');
    await page.waitForSelector("#result:not(.hidden)", { timeout: 300000 });
    const result = (await page.$eval("#result", (e) => e.textContent)).replace(/\s+/g, " ");
    check(/Lost \(bomb\)/.test(result) && /Won in 11 turns/.test(result), `scenario 1 compares the memories: ${result}`);
    const stats = await page.evaluate(() => window.CodebookGraph.stats());
    check(stats.mode === "3d" && stats.nodes >= 26, `3D graph rendered ${JSON.stringify(stats)}`);
    check((await page.$("#graph3d canvas")) !== null, "the graph draws on a canvas");
    check(errors.length === 0, `no console errors in scenario 1 ${errors.slice(0, 3).join(" | ")}`);
    await ctx.close();
  }
  { // 3. scenario 2 replays the handover
    const { ctx, page, errors } = await fresh();
    await startScenario(page, "handover");
    await statusMatches(page, "Won in 8 turns · matches the benchmark log");
    check(true, "scenario 2 replays Claude's handover: won in 8, matches the log");
    check(errors.length === 0, `no console errors in scenario 2 ${errors.slice(0, 3).join(" | ")}`);
    await ctx.close();
  }
  { // 4. scenario 4 explores a memory; the tour has seven steps
    const { ctx, page, errors } = await fresh();
    await startScenario(page, "explore");
    await page.waitForFunction(() => window.CodebookGraph.stats().nodes >= 26, { timeout: 90000 });
    await page.waitForSelector("#cmp .opt", { timeout: 90000 });
    check(true, "scenario 4 shows the explore graph and the compared clues");
    await page.click("#openTour");
    let steps = 0;
    while (steps < 10 && (await page.$("#tour:not(.hidden)"))) {
      steps += 1;
      await page.click("#tournext");
      await sleep(300);
    }
    check(steps === 7, `the tour has seven steps (${steps})`);
    check(errors.length === 0, `no console errors in explore and the tour ${errors.slice(0, 3).join(" | ")}`);
    await ctx.close();
  }
  { // 5. scenario 3: a human guesser never sees the key, in the clue line or the graph
    const { ctx, page, errors } = await fresh();
    await startScenario(page, "play");
    await page.waitForSelector("#yourturn:not(.hidden)", { timeout: 90000 });
    const meta = await page.$eval("#cluemeta", (e) => e.textContent);
    const graph = await page.evaluate(() => window.CodebookGraph.stats());
    const keyed = await page.$$eval(".tile.keyed", (t) => t.length);
    check(!/aiming at/.test(meta) && graph.nodes === 0 && keyed === 0,
      `your turn hides the key (meta "${meta}", graph ${JSON.stringify(graph)}, keyed tiles ${keyed})`);
    await page.click(".tile.clickable");
    await sleep(1500);
    check(errors.length === 0, `no console errors while playing ${errors.slice(0, 3).join(" | ")}`);
    await ctx.close();
  }
  { // 6. no CDN: a deep link skips the start screen, the game plays, the graph falls back to a list
    const { ctx, page, errors } = await fresh(true);
    await page.goto(`${BASE}/?tab=queries`, { waitUntil: "networkidle2" });
    check(await page.$eval("#scenarios", (e) => e.classList.contains("hidden")), "a deep link skips the start screen");
    await page.waitForFunction(() => document.getElementById("partner").options.length > 1);
    await page.evaluate(() => {
      document.getElementById("partner").value = "w2v";
      document.getElementById("memory").value = "own";
      document.getElementById("seed").value = "6030";
      document.getElementById("delay").value = "0";
      document.getElementById("start").click();
    });
    await statusMatches(page, "Won in 11 turns");
    const fallback = await page.$eval("#graph3d", (e) => e.textContent);
    check(/3D view unavailable/.test(fallback), "without the CDN the graph falls back to a ranked list");
    const scriptErrors = errors.filter((e) => !/net::ERR_FAILED|Failed to load resource|integrity|ERR_BLOCKED/i.test(e));
    check(scriptErrors.length === 0, `no script errors without the CDN ${scriptErrors.slice(0, 3).join(" | ")}`);
    await ctx.close();
  }
} finally {
  await browser.close();
}
console.log(failures.length ? `${failures.length} check(s) failed` : "all checks passed");
process.exit(failures.length ? 1 : 0);
```

- [ ] **Step 2: Run them and see them fail**

Run (with `uv run codebook ui` restarted so Task 2's routes are live):
1. `uv run pytest -q tests/contract/test_web_routes.py -k page`. Expected: FAIL, because `/static/app.js` returns 404.
2. `cd ../codebook-video && node scripts/ui_smoke.mjs`. Expected: FAIL. The start screen never appears, because no
   script shows it yet.

- [ ] **Step 3: Write the core**

**File:** `src/codebook/static/app.js`

```javascript
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
    game: null, since: 0, timer: null, polling: false, failures: 0, humanGame: false,
    partnersInfo: [], queries: [], roles: {},
    hooks: { start: [], end: [] },
  });
  CB.on = (name, fn) => CB.hooks[name].push(fn);
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
  CB.startGame = async function startGame(body) {
    CB.resetGameView();
    CB.game = null;
    const j = await CB.post('/api/game', body);
    CB.game = j.game;
    CB.since = 0;
    CB.failures = 0;
    CB.humanGame = body.partner === 'you';
    CB.renderBoard(j.words, j.key, CB.humanGame);
    $('gameinfo').innerHTML = CB.gameInfo(body.seed, body.partner, j.read_key, j.benchmark_game, j.replay);
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
    try {
      await CB.startGame(body);
      if (CB.closeDrawer) CB.closeDrawer();
    } catch (e) {
      CB.showError(e.message);
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
    const path = ev.path && ev.path.length ? ev.path : null;
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
```

- [ ] **Step 4: Write the panels**

**File:** `src/codebook/static/panels.js`

```javascript
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
      $('qlist').innerHTML = CB.queries.slice(0, SHOWN_QUERIES).map((x) => `<details class="q"><summary><span class="n">${esc(x.name)}</span><span class="k">${esc(x.key)} · ${x.ro ? 'GRAPH.RO_QUERY' : 'GRAPH.QUERY'}</span><span>${num(x.rows)} rows</span><span>${num(x.ms)} ms</span></summary><pre>${esc(x.cypher)}</pre>${x.params ? `<pre class="p">${esc(x.params)}</pre>` : ''}</details>`).join('');
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
    CB.loadPartners().catch(() => {});  // a learning game may have added a memory; the page keeps working without it
  });
})();
```

- [ ] **Step 5: Write the scenarios, the start screen and init**

**File:** `src/codebook/static/scenarios.js`

```javascript
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
    try {
      return await CB.startGame(body);
    } catch (e) {
      CB.showError(e.message);
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
```

- [ ] **Step 6: Check the syntax, then run both tests**

1. Run `node --check src/codebook/static/app.js && node --check src/codebook/static/panels.js && node --check src/codebook/static/scenarios.js`.
   Expected: no output.
2. Run `uv run pytest -q`. Expected: all pass, including `test_the_page_and_every_file_it_loads_are_served`.
3. Restart `uv run codebook ui` (the static files are served fresh; Python changes need the restart), then run
   `cd ../codebook-video && node scripts/ui_smoke.mjs`. Expected: every line `ok`, then `all checks passed` and
   exit code 0.

If anything prints `FAIL`, fix it before committing. The message names the scenario and the first console errors.

- [ ] **Step 7: Look at it.** Open http://127.0.0.1:7811/ in a fresh browser profile and click each scenario. Check:
  - the board, clue and narration read at a glance;
  - labels don't pile up in the graph;
  - nothing overflows at 1366×768 or 1920×1080.

  Tune only CSS sizes and the graph's charge strength (`-90`) here.

- [ ] **Step 8: Commit** (`codebook-video` isn't under git, so only `codebook` is committed)

```bash
git add src/codebook/static/app.js src/codebook/static/panels.js src/codebook/static/scenarios.js tests/contract/test_web_routes.py
git commit -m "feat: redesigned live view, scenarios, narration, motion and the 3D memory graph"
```

---

### Task 6: Review, screenshots and docs

**Files:**
- Create: `../codebook-video/scripts/readme_shots.mjs`
- Modify:
  - `docs/img/live-view.png`, `docs/img/partner-memory.png`, `docs/img/compare-memories.png` (re-captured);
  - `README.md` (the screenshot alt text and a one-paragraph "Live view" description);
  - `scripts/record_demo.py` line 193.

**Interfaces:**
- Consumes: the running live view.
- Produces: the three README images at 1600×1000.

- [ ] **Step 1: Whole-branch review.** Dispatch one reviewer subagent (`ecc:code-reviewer`, which covers security).
  - **Scope:** the diff since the spec commit (`git diff b6d8c4b..HEAD`).
  - **Focus:** escaping of every server value in the new JS, request validation in `graphview.py` and the two
    routes, the thread-local reset in `game_graph`, and the five Review Focus items above.
  - Fix every CRITICAL and HIGH finding, re-run `uv run pytest -q` and the smoke test, then commit:
    `fix: review findings`.

- [ ] **Step 2: Keep the old recorder working.** In `scripts/record_demo.py`, line 193, change
  `page.goto(f"{BASE}/")` to `page.goto(f"{BASE}/?tab=queries")`. A query string skips the new start screen.

- [ ] **Step 3: Write the screenshot script**

**File:** `../codebook-video/scripts/readme_shots.mjs`

```javascript
// Re-captures the README screenshots from the live view: node scripts/readme_shots.mjs (needs `uv run codebook ui`).
import puppeteer from "puppeteer-core";
import path from "node:path";

const BASE = "http://127.0.0.1:7811";
const OUT = "C:/Users/sarpa/Desktop/ps5/codebook/docs/img";
const SETTLE_MS = 2500;  // the graph settles and the camera lands
const browser = await puppeteer.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe", headless: true,
  defaultViewport: { width: 1600, height: 1000 }, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
try {
  const page = await browser.newPage();
  await page.goto(`${BASE}/?tab=queries`, { waitUntil: "networkidle2" });
  await page.waitForFunction(() => document.getElementById("partner").options.length > 1);
  await page.evaluate(() => {
    for (const [id, v] of [["partner", "w2v"], ["memory", "own"], ["seed", "6030"], ["delay", "0"]]) document.getElementById(id).value = v;
    document.getElementById("start").click();
  });
  await page.waitForFunction(() => /Won in/.test(document.getElementById("status").textContent), { timeout: 180000 });
  await new Promise((r) => setTimeout(r, SETTLE_MS));
  await page.screenshot({ path: path.join(OUT, "live-view.png") });
  await page.click('.tabs button[data-tab="memory"]');
  await page.waitForSelector("#tab-memory .bars");
  await new Promise((r) => setTimeout(r, SETTLE_MS / 2));
  await page.screenshot({ path: path.join(OUT, "partner-memory.png") });
  await page.goto(`${BASE}/?tab=compare&seed=6042&memories=everyone,w2v,persona-mirror`, { waitUntil: "networkidle2" });
  await page.waitForSelector("#cmp .opt", { timeout: 90000 });
  await new Promise((r) => setTimeout(r, SETTLE_MS / 2));
  await page.screenshot({ path: path.join(OUT, "compare-memories.png") });
  console.log("wrote live-view.png, partner-memory.png, compare-memories.png");
} finally {
  await browser.close();
}
```

- [ ] **Step 4: Capture and look at them**

Run: `cd ../codebook-video && node scripts/readme_shots.mjs`
Expected: `wrote live-view.png, partner-memory.png, compare-memories.png`. Open each image. The live view must show
the board, the clue, the narration and the 3D graph with labels, with nothing clipped.

- [ ] **Step 5: README text.** In `README.md`:
  1. Replace the screenshot table's alt text for `live-view.png` with
     `Board 6030 with the word2vec bot's own memory: the board, the clue, plain-English narration and the partner's memory in 3D`.
  2. Add this paragraph directly under the screenshot table:

```markdown
**The live view explains itself.** On a first visit it offers four one-click scenarios: the same board with two
memories, another AI taking over, playing as the guesser yourself, and exploring a memory. There's also a 60-second
tour. While a game plays, a narration line says what just happened in plain words. The partner's memory around each
clue turns in 3D, from three read-only Cypher queries (`graph_clue_links`, `graph_chains`, `path_to`), and those
queries appear in the Live Cypher tab with everything else.
```

- [ ] **Step 6: Run everything one last time and commit**

Run `uv run pytest -q` (all pass), then `cd ../codebook-video && node scripts/ui_smoke.mjs` (all checks passed).

```bash
git add docs/img/live-view.png docs/img/partner-memory.png docs/img/compare-memories.png README.md scripts/record_demo.py
git commit -m "docs: README screenshots and a live view paragraph for the redesign"
```

- [ ] **Step 7 (optional, if time remains): re-render the demo video from the new UI**
  1. `capture.mjs` already opens `/?tab=queries`, so the start screen stays closed. It reads `#start`'s position
     (line 56) for a cursor ripple. That button now sits in the closed drawer, so click `#openCustom` and wait
     400 ms before that measurement.
  2. Capture: `cd ../codebook-video && node scripts/capture.mjs`.
  3. Check the stills: run `node scripts/stills.mjs --all`, then look at them.
  4. Render: `npx remotion render src/index.ts Codebook out/codebook-raw.mp4 --browser-executable="C:/Program Files/Google/Chrome/Application/chrome.exe" --concurrency=2 --jpeg-quality=92`
  5. Loudness-normalise exactly as before (two-pass `loudnorm`, I=-14, TP=-1.5).
