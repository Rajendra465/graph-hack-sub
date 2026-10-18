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
