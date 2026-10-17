"""MCP server: any agent (Claude Code, Codex, ...) can give clues with a partner's memory.

The agent calls tools; the tools call the gatekeeper (memory.py). The agent never sees a
database address or password. Register it with, for example:
    claude mcp add codebook -- uv --directory <repo> run codebook mcp
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from codebook import config, keys
from codebook import cypher as C
from codebook.board import ASSASSIN, NEUTRAL, OPPONENT, TEAM, BoardView, is_legal_clue
from codebook.db import Db
from codebook.memory import Memory, TurnRecord
from codebook.session import BLOCK_P, BLOCK_STRENGTH
from codebook.spymaster import Costs, evaluate, plan

server = FastMCP("codebook", instructions=(
    "Codebook keeps a memory of each Codenames partner in FalkorDB. Use suggest_clues to rank clues "
    "for a board with a partner's memory, check_clue before giving any clue (it has the final say on "
    "the bomb), and record_turn after the partner guesses so the memory learns."))
_memory: Memory | None = None


def memory() -> Memory:
    global _memory
    if _memory is None:
        db = Db(config.load())
        db.ping()
        _memory = Memory(db)
    return _memory


def _board(team: list[str], opponent: list[str], neutral: list[str], assassin: str,
           revealed: list[str] | None = None) -> BoardView:
    groups = [(team, TEAM), (opponent, OPPONENT), (neutral, NEUTRAL), ([assassin] if assassin else [], ASSASSIN)]
    words = [w.strip().lower() for g, _ in groups for w in g]
    roles = [r for g, r in groups for _ in g]
    return BoardView(tuple(words), tuple(roles), tuple(words) + tuple(w.lower() for w in (revealed or [])))


def _read_key(partner: str, memory_of: str) -> str:
    if memory_of == "everyone":
        return keys.POPULATION
    return memory().ensure_partner(partner if memory_of == "own" else memory_of)


@server.tool()
def list_partners() -> list[dict]:
    """Every partner memory on the server, with games played and learned style."""
    out = []
    for pid in memory().partners():
        info = memory().info(pid)
        out.append({"partner": pid, "games": info.games, "clues": info.turns,
                    "links_reweighted": info.learned_words, "style": info.style.as_dict()})
    return out


@server.tool()
def suggest_clues(partner: str, team: list[str], opponent: list[str], neutral: list[str], assassin: str,
                  memory_of: str = "own", limit: int = 8, revealed: list[str] | None = None) -> list[dict]:
    """Rank clues for the unrevealed words using a partner's memory ("own", "everyone", or another partner id).
    Each option: clue, count, targets (predicted picks), expected_hits, p_assassin, value."""
    board = _board(team, opponent, neutral, assassin, revealed)
    key = _read_key(partner, memory_of)
    model = memory().model(key)
    table = memory().features(key, board, model)
    return [o.as_dict() for o in plan(board, table.rows, model, seed=len(board.words))[:max(1, min(limit, 20))]]


@server.tool()
def check_clue(partner: str, clue: str, count: int, team: list[str], opponent: list[str], neutral: list[str],
               assassin: str, memory_of: str = "own", revealed: list[str] | None = None) -> dict:
    """Check a clue before giving it. Returns legal, blocked (with the chain to the bomb), and the
    partner model's predicted picks. A blocked clue must not be given."""
    board = _board(team, opponent, neutral, assassin, revealed)
    word = clue.strip().lower()
    if not is_legal_clue(word, board.all_words):
        return {"clue": word, "legal": False, "blocked": True, "reason": "a board word, part of one, or not one word"}
    key = _read_key(partner, memory_of)
    model = memory().model(key)
    strengths = memory().clue_strengths(key, word, board.words)
    import numpy as np  # noqa: PLC0415

    gumbel = np.random.default_rng(len(board.words)).gumbel(size=(Costs().samples, len(board.words)))
    options = evaluate(board, word, strengths, model, gumbel)
    opt = options[max(0, min(int(count), len(options)) - 1)] if options else None
    found = memory().path_to(key, word, assassin.lower()) if assassin else None
    strength = found[1] if found else 0.0
    p_bomb = opt.p_assassin if opt else 0.0
    blocked = strength >= BLOCK_STRENGTH or p_bomb >= BLOCK_P
    return {"clue": word, "legal": True, "blocked": blocked, "path_to_bomb": found[0] if found else [],
            "bomb_strength": round(strength, 5), "p_assassin": round(p_bomb, 4),
            "option": opt.as_dict() if opt else None,
            "reason": "reaches the bomb" if blocked else "ok"}


@server.tool()
def record_turn(partner: str, game_id: str, turn: int, clue: str, count: int, board: list[str],
                intended: list[str], guesses: list[list[str]], agent: str = "agent") -> dict:
    """After the partner guesses: write the turn to the partner's diary and learn from it.
    board = unrevealed words when the clue was given; guesses = [[word, colour], ...] in order,
    colour one of team, opponent, neutral, assassin."""
    key = memory().ensure_partner(partner)
    words = tuple(w.lower() for w in board)
    strengths = memory().clue_strengths(key, clue.lower(), words)
    memory().start_game(key, game_id, 0, "mcp", agent)
    record = TurnRecord(int(turn), clue.lower(), int(count), words, tuple(w.lower() for w in intended), strengths,
                        tuple((w.lower(), r) for w, r in guesses), agent)
    memory().record_turn(key, game_id, record)
    hits, misses = memory().learn(key, record)
    return {"partner": partner, "key": key, "links_strengthened": hits, "links_weakened": misses}


@server.tool()
def end_game(partner: str, game_id: str, turns: int, won: bool) -> dict:
    """Close a game and consolidate the diary into the partner's style and favourite words."""
    key = memory().ensure_partner(partner)
    memory().end_game(key, game_id, int(turns), bool(won))
    model = memory().refit(key)
    return {"partner": partner, "style": model.style.as_dict(), "favourite_words": len(model.bias)}


@server.tool()
def partner_memory(partner: str, limit: int = 20) -> dict:
    """What Codebook remembers about a partner: style, the links it reweighted, favourite words."""
    key = keys.partner_key(partner)
    info = memory().info(partner)
    links = memory().db.ro_query(key, C.LEARNED_LINKS, {"limit": max(1, min(limit, 100))}).records()
    bias = sorted(memory().db.ro_query(key, C.BIAS_GET).rows, key=lambda r: -r[1])[:limit]
    return {"partner": partner, "games": info.games, "clues": info.turns, "style": info.style.as_dict(),
            "links": links, "favourite_words": [w for w, b in bias if b > 0]}


def main() -> None:
    server.run()
