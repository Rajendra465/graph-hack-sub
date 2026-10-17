"""Replay benchmark games in the live view.

A live game on a benchmark board with the same set-up uses the benchmark's game id, which seeds Codebook's
sampling, so with a bot or planted partner it repeats the logged game move for move. An AI clue-giver never
answers the same way twice, so a replay takes the AI's clues from the log instead; the engine, the partner,
the memory and every check still run live.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from codebook.evaluate import SWAPS

HUMAN = "you"
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def benchmark_condition(partner: str, memory_of: str, clue_giver: str) -> str | None:
    """The benchmark set-up a live game matches, or None if the benchmark never ran it."""
    if partner == HUMAN:
        return None
    if clue_giver != "codebook":
        return "handover" if memory_of == "own" else None
    if memory_of == "own":
        return "warm"
    if memory_of == "everyone":
        return "cold"
    if memory_of == SWAPS.get(partner):
        return "swap"
    games = memory_of.removeprefix(f"{partner}-at")
    if games != memory_of and games.isdigit():
        return f"warm@{int(games)}"
    return None


def live_condition(partner: str, memory_of: str, clue_giver: str, *, learn: bool, replay: bool) -> str | None:
    """The benchmark set-up a live game can repeat. A learning game is always new, and a live AI never repeats
    itself, so an AI clue-giver repeats a logged game only when its clues are replayed from the log."""
    if learn or (clue_giver != "codebook" and not replay):
        return None
    return benchmark_condition(partner, memory_of, clue_giver)


def logged_game(results_dir: Path, partner: str, condition: str, seed: int, clue_giver: str) -> dict | None:
    """The latest run's game for this set-up, clue-giver and board (the last row wins, as in the report)."""
    latest = results_dir / "LATEST_RUN"
    if not latest.exists():
        raise ValueError("no benchmark run to replay: results/LATEST_RUN is missing")
    run = latest.read_text(encoding="utf-8").strip()
    if not _RUN_ID.fullmatch(run):
        raise ValueError(f"results/LATEST_RUN does not name a run: {run!r}")
    found = None
    try:
        with (results_dir / "runs" / run / "games.jsonl").open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line) if line.strip() else None
                if (isinstance(row, dict) and row.get("partner") == partner and row.get("condition") == condition
                        and row.get("seed") == seed and row.get("clue_giver", "codebook") == clue_giver):
                    found = row
    except (OSError, ValueError) as exc:  # json errors are ValueErrors; neither message leaks the path
        raise ValueError(f"the benchmark log of run {run} is unreadable ({type(exc).__name__})") from None
    return found


def same_moves(live: list[dict], logged: list[dict]) -> bool:
    """Did two games give the same clues, with the same counts, and get the same guesses?"""
    def moves(clues):
        return [(c.get("clue"), c.get("count"), [list(g) for g in c.get("guesses", [])]) for c in clues]
    return moves(live) == moves(logged)


def logged_chooser(row: dict, giver: str) -> Callable:
    """A clue-giver that proposes, turn by turn, the clues `giver` gave in a logged game.

    Turns where the log shows Codebook's suggestion get no answer, so the game falls back to it again, and a
    replayed clue is never proposed twice in one turn."""
    turns = iter(row.get("clues", []))

    def choose(_board, _options, rejected=()):
        if rejected:  # a second attempt in the same turn: the log has no second answer
            return None
        turn = next(turns, None)
        if turn is None or turn.get("by") != giver:
            return None
        return str(turn["clue"]), int(turn["count"])

    return choose
