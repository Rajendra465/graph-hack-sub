"""MCP server: any agent (Claude Code, Codex, ...) can give clues with a partner's memory.

The agent calls tools; the tools call the gatekeeper (memory.py). The agent never sees a
database address or password. Register it with, for example:
    claude mcp add codebook -- uv --directory <repo> run codebook mcp
"""

from __future__ import annotations

import functools
import re

from mcp.server.fastmcp import FastMCP

from codebook import config, keys
from codebook import cypher as C
from codebook.board import ASSASSIN, NEUTRAL, OPPONENT, TEAM, WORD_RE, BoardView, is_legal_clue
from codebook.db import Db, DbError, Unreachable
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


MAX_WORDS = 25
COLOURS = {TEAM, OPPONENT, NEUTRAL, ASSASSIN}
_GAME_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _word(w: str) -> str:
    word = str(w).strip().lower()
    if not WORD_RE.fullmatch(word) or len(word) > 32:
        raise ValueError(f"not a single lowercase word: {w!r}")
    return word


def _words(ws, name: str) -> list[str]:
    ws = list(ws or [])
    if len(ws) > MAX_WORDS:
        raise ValueError(f"{name}: at most {MAX_WORDS} words")
    return [_word(w) for w in ws]


def _board(team: list[str], opponent: list[str], neutral: list[str], assassin: str,
           revealed: list[str] | None = None) -> BoardView:
    groups = [(_words(team, "team"), TEAM), (_words(opponent, "opponent"), OPPONENT),
              (_words(neutral, "neutral"), NEUTRAL), ([_word(assassin)] if assassin else [], ASSASSIN)]
    words = [w for g, _ in groups for w in g]
    if not 1 <= len(words) <= MAX_WORDS:
        raise ValueError(f"a board has 1 to {MAX_WORDS} unrevealed words")
    roles = [r for g, r in groups for _ in g]
    return BoardView(tuple(words), tuple(roles), tuple(words) + tuple(_words(revealed, "revealed")))


def _read_key(partner: str, memory_of: str) -> str:
    """Reads never create memories: a partner with no memory yet is read from everyone's."""
    if memory_of == "everyone":
        return keys.POPULATION
    key = keys.partner_key(partner if memory_of == "own" else memory_of)
    if memory().db.exists(key):
        return key
    if memory_of == "own":
        return keys.POPULATION
    raise ValueError(f"no memory for partner {memory_of!r}")


def _safe(fn):
    """Agents get the error, never the database's address."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Unreachable as exc:
            raise RuntimeError("FalkorDB is unreachable; Codebook has no fallback store") from exc
        except DbError as exc:
            raise RuntimeError(f"database error: {type(exc).__name__}") from exc
    return wrapper


@server.tool()
@_safe
def list_partners() -> list[dict]:
    """Every partner memory on the server, with games played and learned style."""
    out = []
    for pid in memory().partners():
        info = memory().info(pid)
        out.append({"partner": pid, "games": info.games, "clues": info.turns,
                    "links_reweighted": info.learned_words, "style": info.style.as_dict()})
    return out


@server.tool()
@_safe
def suggest_clues(partner: str, team: list[str], opponent: list[str], neutral: list[str], assassin: str,
                  memory_of: str = "own", limit: int = 8, revealed: list[str] | None = None) -> list[dict]:
    """Rank clues for the unrevealed words using a partner's memory ("own", "everyone", or another partner id).
    Each option: clue, count, targets (predicted picks), expected_hits, p_assassin, value."""
    board = _board(team, opponent, neutral, assassin, revealed)
    key = _read_key(partner, memory_of)
    model = memory().model(key)
    table = memory().features(key, board, model)
    return [o.as_dict() for o in plan(board, table.rows, model, seed=len(board.words), limit=max(1, min(int(limit), 20)))]


@server.tool()
@_safe
def check_clue(partner: str, clue: str, count: int, team: list[str], opponent: list[str], neutral: list[str],
               assassin: str, memory_of: str = "own", revealed: list[str] | None = None) -> dict:
    """Check a clue before giving it. Returns legal, blocked (with the chain to the bomb), and the
    partner model's predicted picks. A blocked clue must not be given."""
    board = _board(team, opponent, neutral, assassin, revealed)
    word = clue.strip().lower()
    if not WORD_RE.fullmatch(word) or not is_legal_clue(word, board.all_words):
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
@_safe
def record_turn(partner: str, game_id: str, turn: int, clue: str, count: int, board: list[str],
                intended: list[str], guesses: list[list[str]], agent: str = "agent") -> dict:
    """After the partner guesses: write the turn to the partner's diary and learn from it.
    board = unrevealed words when the clue was given; guesses = [[word, colour], ...] in order,
    colour one of team, opponent, neutral, assassin."""
    if not _GAME_ID.fullmatch(game_id) or not _GAME_ID.fullmatch(agent):
        raise ValueError("game_id and agent: 1-64 letters, digits, '_', '.', ':' or '-'")
    words = tuple(_words(board, "board"))
    clue_word, n, count = _word(clue), int(turn), int(count)
    if not 1 <= n <= 50 or not 1 <= count <= 9:
        raise ValueError("turn must be 1-50 and count 1-9")
    aimed = tuple(_words(intended, "intended"))
    picks = []
    for g in list(guesses)[:count + 1]:
        if len(g) != 2 or _word(g[0]) not in words or g[1] not in COLOURS:
            raise ValueError(f"each guess is [board word, colour in {sorted(COLOURS)}]: {g!r}")
        picks.append((_word(g[0]), g[1]))
    if len(guesses) > count + 1 or not set(aimed) <= set(words):
        raise ValueError("at most count+1 guesses, and intended words must be on the board")
    key = memory().ensure_partner(partner)
    seen = memory().db.ro_query(key, "MATCH (:Game {id: $game})-[:HAS]->(t:Turn {n: $n}) RETURN count(t)",
                                {"game": game_id, "n": n}).scalar(0)
    if seen:  # recording the same turn twice must not count its evidence twice
        return {"partner": partner, "key": key, "already_recorded": True, "links_strengthened": 0, "links_weakened": 0}
    strengths = memory().clue_strengths(key, clue_word, words)
    memory().start_game(key, game_id, 0, "mcp", agent)
    record = TurnRecord(n, clue_word, count, words, aimed, strengths, tuple(picks), agent)
    memory().record_turn(key, game_id, record)
    hits, misses = memory().learn(key, record)
    return {"partner": partner, "key": key, "links_strengthened": hits, "links_weakened": misses}


@server.tool()
@_safe
def end_game(partner: str, game_id: str, turns: int, won: bool) -> dict:
    """Close a game and consolidate the diary into the partner's style and favourite words."""
    if not _GAME_ID.fullmatch(game_id):
        raise ValueError("game_id: 1-64 letters, digits, '_', '.', ':' or '-'")
    key = keys.partner_key(partner)
    if not memory().db.exists(key):
        raise ValueError(f"no memory for partner {partner!r}; record a turn first")
    memory().end_game(key, game_id, max(0, min(int(turns), 25)), won is True)
    model = memory().refit(key)
    return {"partner": partner, "style": model.style.as_dict(), "favourite_words": len(model.bias)}


@server.tool()
@_safe
def partner_memory(partner: str, limit: int = 20) -> dict:
    """What Codebook remembers about a partner: style, the links it reweighted, favourite words."""
    key = keys.partner_key(partner)
    if not memory().db.exists(key):
        raise ValueError(f"no memory for partner {partner!r}")
    limit = max(1, min(int(limit), 100))
    info = memory().info(partner)
    links = memory().db.ro_query(key, C.LEARNED_LINKS, {"limit": limit}).records()
    bias = sorted(memory().db.ro_query(key, C.BIAS_GET).rows, key=lambda r: -r[1])[:limit]
    return {"partner": partner, "games": info.games, "clues": info.turns, "style": info.style.as_dict(),
            "links": links, "favourite_words": [w for w, b in bias if b > 0]}


def main() -> None:
    server.run()
