"""Play games on the unmodified Codenames AI Competition engine (src/codebook/engine).

The engine owns the board, the key, the turn loop and the score. Codebook plugs in as the
competition's Codemaster; partners plug in as its Guesser. A thin subclass records each graded
guess (the original `_accept_guess` still decides the outcome) and captures the final count.
Run games in separate processes for parallelism: the engine uses the global `random` seed,
the working directory and stdout.
"""

from __future__ import annotations

import contextlib
import io
import os
from collections import Counter
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import colorama

from codebook.board import ASSASSIN, NEUTRAL, OPPONENT, TEAM
from codebook.session import Block, NoClue, Session, TurnLimit

ENGINE_DIR = Path(__file__).resolve().parent / "engine"
ROLE = {"Red": TEAM, "Blue": OPPONENT, "Civilian": NEUTRAL, "Assassin": ASSASSIN}
LOSS_TURNS = 25
_cwd_lock = threading.Lock()


def engine():
    """Import the vendored engine modules (`game`, `players.*`) from ENGINE_DIR."""
    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))
    with _quiet():
        import game  # noqa: PLC0415 - vendored module, imported on demand
    return game


def pool_words() -> list[str]:
    return [w.strip().lower() for w in (ENGINE_DIR / "game_wordpool.txt").read_text().splitlines() if w.strip()]


def clue_wordlist() -> list[str]:
    path = ENGINE_DIR / "players" / "cm_wordlist.txt"
    return [w.strip().lower() for w in path.read_text().splitlines() if w.strip()]


@contextlib.contextmanager
def _quiet():
    """Swallow the engine's prints and undo colorama's stream wrapping after each game."""
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        yield sink


@contextlib.contextmanager
def _in_engine_dir():
    with _cwd_lock:
        previous = os.getcwd()
        os.chdir(ENGINE_DIR)
        try:
            yield
        finally:
            os.chdir(previous)


@dataclass
class GuessLog:
    """What everyone at the table sees: each revealed word and its colour, in order."""

    events: list = field(default_factory=list)
    listeners: list = field(default_factory=list)

    def add(self, word: str, role: str) -> None:
        self.events.append((word, role))
        for fn in self.listeners:
            fn(word, role)


@dataclass(frozen=True)
class GameResult:
    game_id: str
    seed: int
    turns: int
    won: bool
    assassin: bool
    team_found: int
    opponent_found: int
    clues: tuple
    blocks: tuple[Block, ...]
    seconds: float

    @property
    def clean_clues(self) -> int:
        return sum(1 for c in self.clues if c.guesses and all(r == TEAM for _, r in c.guesses))

    def as_dict(self) -> dict:
        return {
            "game": self.game_id, "seed": self.seed, "turns": self.turns, "won": self.won,
            "assassin": self.assassin, "team_found": self.team_found, "opponent_found": self.opponent_found,
            "clue_count": len(self.clues), "clean_clues": self.clean_clues, "seconds": round(self.seconds, 2),
            "clues_by": dict(sorted(Counter(c.by for c in self.clues).items())),
            "clues": [{"n": c.n, "clue": c.clue, "count": c.count, "intended": list(c.intended),
                       "guesses": [list(g) for g in c.guesses], "by": c.by, "value": round(c.value, 3)}
                      for c in self.clues],
            "blocks": [b.as_dict() for b in self.blocks],
        }


def _game_classes():
    mod = engine()
    from players.codemaster import Codemaster  # noqa: PLC0415 - vendored package

    class RecordingGame(mod.Game):
        def __init__(self, codemaster, guesser, *, log: GuessLog, **kwargs):
            self._log = log
            self.final_turns = None
            with _in_engine_dir():
                super().__init__(codemaster, guesser, **kwargs)
            colorama.deinit()  # the engine calls colorama.init() per game; undo it so wrappers don't pile up

        def _accept_guess(self, guess_index):
            word, colour = self.words_on_board[guess_index], self.key_grid[guess_index]
            condition = super()._accept_guess(guess_index)
            self._log.add(word.lower(), ROLE[colour])
            return condition

        def write_results(self, num_of_turns):
            self.final_turns = num_of_turns

    return RecordingGame, Codemaster


def board_for_seed(seed: int) -> tuple[list[str], list[str]]:
    """The board and key the engine deals for this seed (same calls, same order as Game)."""
    import random  # noqa: PLC0415

    random.seed(int(seed))
    words = (ENGINE_DIR / "game_wordpool.txt").read_text().splitlines()
    random.shuffle(words)
    board = words[:25]
    key = ["Red"] * 8 + ["Blue"] * 7 + ["Civilian"] * 9 + ["Assassin"]
    random.shuffle(key)
    return board, key


def play(session_factory: Callable[[list], Session], guesser_class, seed: int, game_id: str,
         *, guesser_kwargs: dict | None = None, quiet: bool = True,
         on_guess: Callable[[str, str], None] | None = None) -> tuple[GameResult, Session]:
    """Play one seeded game. `session_factory(events)` builds the clue-giver's Session.

    quiet=True swallows the engine's prints (CLI, benchmark). The web server passes False
    and silences stdout once for the whole process instead, so threads don't fight over it.
    """
    RecordingGame, Codemaster = _game_classes()
    log = GuessLog()
    if on_guess:
        log.listeners.append(on_guess)
    session = session_factory(log.events)

    class CodebookCodemaster(Codemaster):
        def __init__(self):
            super().__init__()

        def set_game_state(self, words_on_board, key_grid):
            session.observe(words_on_board, key_grid)

        def get_clue(self):
            return session.give_clue()

    started = time.perf_counter()
    with (_quiet() if quiet else contextlib.nullcontext()):
        game = RecordingGame(CodebookCodemaster, guesser_class, log=log, seed=seed, do_print=True,
                             do_log=True, game_name=game_id, g_kwargs=guesser_kwargs or {})
        try:
            game.run()
            turns = game.final_turns if game.final_turns is not None else LOSS_TURNS
        except (TurnLimit, NoClue):
            turns = LOSS_TURNS
    roles = [r for _, r in log.events]
    team_found = roles.count(TEAM)
    won = team_found >= 8 and ASSASSIN not in roles and turns < LOSS_TURNS
    session.finish(turns, won)
    result = GameResult(game_id, seed, turns, won, ASSASSIN in roles, team_found, roles.count(OPPONENT),
                        tuple(session.turns), tuple(session.blocks), time.perf_counter() - started)
    return result, session
