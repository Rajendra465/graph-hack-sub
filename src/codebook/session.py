"""One game from the clue-giver's side: read the memory, choose a clue, block, then learn.

The block has the final say. Whoever proposes the clue (Codebook's ranking or an outside AI
such as Claude or Codex), a clue is refused when, in the memory being used, a chain of at most
two links reaches the bomb with strength >= BLOCK_STRENGTH, or the partner model gives the
bomb a pick probability >= BLOCK_P.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace
from typing import Callable, Sequence

import numpy as np

from codebook.board import BoardView, is_legal_clue
from codebook.memory import Memory, TurnRecord
from codebook.model import PartnerModel
from codebook.spymaster import Costs, Option, evaluate, plan

BLOCK_STRENGTH = 0.02
BLOCK_P = 0.05


class TurnLimit(RuntimeError):
    """The game ran past the turn limit; it counts as a loss."""


class NoClue(RuntimeError):
    """No legal, unblocked clue links to any team word."""


@dataclass(frozen=True)
class Block:
    turn: int
    clue: str
    path: tuple[str, ...]
    strength: float
    p_assassin: float
    proposed_by: str

    def as_dict(self) -> dict:
        return {"turn": self.turn, "clue": self.clue, "path": list(self.path),
                "strength": round(self.strength, 5), "p_assassin": round(self.p_assassin, 4),
                "proposed_by": self.proposed_by}


@dataclass(frozen=True)
class Pending:
    record: TurnRecord
    since: int


# An outside AI that proposes a clue. It sees the board and Codebook's ranked options and
# returns (clue, count), or None to take Codebook's top option.
Chooser = Callable[[BoardView, Sequence[Option]], "tuple[str, int] | None"]


@dataclass
class Session:
    memory: Memory
    read_key: str
    model: PartnerModel
    game_id: str
    seed: int
    condition: str
    events: list  # the GuessLog's (word, role) list, shared with the engine wrapper
    write_key: str | None = None
    learn: bool = False
    by: str = "codebook"
    allowed: Callable[[str], bool] = lambda _w: True
    chooser: Chooser | None = None
    chooser_name: str = ""
    plain: bool = False  # the AI's own clue is used as-is: no graph suggestions, no block
    costs: Costs = field(default_factory=Costs)
    max_turns: int = 25
    on_event: Callable[[dict], None] | None = None
    turns: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    board: BoardView | None = None
    _original: tuple[str, ...] | None = None
    _pending: Pending | None = None

    def __post_init__(self) -> None:
        if self.write_key:
            self.memory.start_game(self.write_key, self.game_id, self.seed, self.condition, self.by)

    def _emit(self, kind: str, **data) -> None:
        if self.on_event:
            self.on_event({"kind": kind, "game": self.game_id, **data})

    # ---- engine callbacks ----
    def observe(self, words_on_board: Sequence[str], key_grid: Sequence[str]) -> None:
        if self._original is None:
            self._original = tuple(words_on_board)
        self.board = BoardView.from_harness(words_on_board, key_grid, self._original)
        self._close_turn()

    def give_clue(self) -> tuple[str, int]:
        if self.board is None:
            raise RuntimeError("give_clue before observe")
        if len(self.turns) >= self.max_turns:
            raise TurnLimit(f"{self.game_id}: {self.max_turns} clues without finishing")
        n = len(self.turns) + 1
        used = {t.clue for t in self.turns}

        def allowed(word: str) -> bool:  # never repeat a clue within a game
            return word not in used and self.allowed(word)

        table = self.memory.features(self.read_key, self.board, self.model, allowed=allowed)
        seed = zlib.crc32(f"{self.game_id}:{n}".encode())
        options = plan(self.board, table.rows, self.model, seed=seed, allowed=allowed, costs=self.costs)
        candidates: list[tuple[Option, dict, str]] = []
        proposal = self.chooser(self.board, [] if self.plain else options[:10]) if self.chooser else None
        if proposal:
            opt, strengths = self._evaluate_proposal(proposal, seed)
            if opt is not None and self.plain:
                return self._commit(n, opt, strengths, self.chooser_name or "ai", options, table.ms, forced=False)
            if opt is not None:
                candidates.append((opt, strengths, self.chooser_name or "ai"))
        if self.chooser and not candidates:
            self._emit("fallback", turn=n, proposal=list(proposal) if proposal else None)
        candidates.extend((o, table.rows[o.clue], "codebook") for o in options)
        blocked: list[tuple[Block, Option, dict, str]] = []
        for opt, strengths, proposer in candidates:
            block = self._block(n, opt, proposer)
            if block:
                self.blocks.append(block)
                blocked.append((block, opt, strengths, proposer))
                self._emit("block", **block.as_dict())
                continue
            return self._commit(n, opt, strengths, proposer, options, table.ms, forced=False)
        if blocked:
            # Every candidate is blocked: give the one least likely to reach the bomb, and say so.
            _, opt, strengths, proposer = min(blocked, key=lambda b: (b[0].p_assassin, b[0].strength, -b[1].value))
            opt = replace(opt, count=1, targets=opt.targets[:1])
            return self._commit(n, opt, strengths, proposer, options, table.ms, forced=True)
        raise NoClue(f"{self.game_id} turn {n}: no legal clue links to any team word")

    def _commit(self, n: int, opt: Option, strengths, proposer: str, options, ms, *, forced: bool):
        record = TurnRecord(n, opt.clue, opt.count, self.board.words, opt.targets,
                            dict(strengths), (), proposer if proposer != "codebook" else self.by, opt.value)
        self._pending = Pending(record, len(self.events))
        self._emit("clue", turn=n, clue=opt.clue, count=opt.count, proposed_by=proposer, forced=forced,
                   option=opt.as_dict(), alternatives=[o.as_dict() for o in options[:5]],
                   ms=dict(ms), board=list(self.board.words), roles=list(self.board.roles))
        return opt.clue, opt.count

    def finish(self, turns: int, won: bool) -> None:
        self._close_turn()
        if self.write_key:
            self.memory.end_game(self.write_key, self.game_id, turns, won)
            if self.learn:
                self.model = self.memory.refit(self.write_key)
                self._emit("refit", style=self.model.style.as_dict(), biased_words=len(self.model.bias))

    # ---- internals ----
    def _evaluate_proposal(self, proposal: tuple[str, int], seed: int):
        clue, count = proposal[0].strip().lower(), int(proposal[1])
        if not is_legal_clue(clue, self.board.all_words) or not self.allowed(clue):
            self._emit("proposal_rejected", clue=clue, reason="illegal clue or unknown to this partner")
            return None, {}
        strengths = self.memory.clue_strengths(self.read_key, clue, self.board.words)
        rng = np.random.default_rng(seed)
        gumbel = rng.gumbel(size=(self.costs.samples, len(self.board.words)))
        costs = replace(self.costs, max_count=9) if self.plain else self.costs
        options = evaluate(self.board, clue, strengths, self.model, gumbel, costs)
        if not options:
            return None, {}
        count = max(1, min(count, len(options)))
        return replace(options[count - 1]), strengths

    def _block(self, n: int, opt: Option, proposer: str) -> Block | None:
        bomb = self.board.assassin
        if bomb is None:
            return None
        found = self.memory.path_to(self.read_key, opt.clue, bomb)
        path, strength = (tuple(found[0]), found[1]) if found else ((), 0.0)
        if strength >= BLOCK_STRENGTH or opt.p_assassin >= BLOCK_P:
            return Block(n, opt.clue, path, strength, opt.p_assassin, proposer)
        return None

    def _close_turn(self) -> None:
        if self._pending is None:
            return
        guesses = tuple(self.events[self._pending.since:])
        record = replace(self._pending.record, guesses=guesses)
        self._pending = None
        self.turns.append(record)
        learned = (0, 0)
        if self.write_key:
            self.memory.record_turn(self.write_key, self.game_id, record)
            if self.learn:
                learned = self.memory.learn(self.write_key, record)
        self._emit("graded", turn=record.n, clue=record.clue, guesses=[list(g) for g in guesses],
                   learned_hits=learned[0], learned_misses=learned[1])
