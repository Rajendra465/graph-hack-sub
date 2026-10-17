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

from codebook.board import WORD_RE, BoardView, is_legal_clue
from codebook.memory import Memory, TurnRecord
from codebook.model import PartnerModel
from codebook.spymaster import Costs, Option, disagreement, evaluate, plan

BLOCK_STRENGTH = 0.02
BLOCK_P = 0.05
AI_ATTEMPTS = 3       # an AI clue-giver gets this many proposals per turn, each rejection explained
PASS_CLUE = "zzzz"    # plain AI with no usable clue: a legal word no partner knows, so the turn passes


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


# An outside AI that proposes a clue. It sees the board, Codebook's ranked options (none for the
# plain AI) and its own rejected proposals with the reasons, and returns (clue, count) or None.
Chooser = Callable[[BoardView, Sequence[Option], Sequence[tuple[str, str]]], "tuple[str, int] | None"]


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
    explore: float = 0.0  # practice games: bonus for clues that reveal how this partner thinks
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
        seed = zlib.crc32(f"{self.game_id}:{n}".encode())
        table, options = self._options(seed, exclude={t.clue for t in self.turns})
        if not options:  # every unused clue is gone: repeating one beats giving up the game
            self._emit("repeat_allowed", turn=n)
            table, options = self._options(seed, exclude=set())
        ai = self.chooser_name or "ai"
        candidates: list[tuple[Option, dict, str]] = []
        if self.chooser:
            proposed = self._ask_ai(n, seed, options)
            if proposed is not None and self.plain:
                return self._commit(n, proposed[0], proposed[1], ai, options, table.ms, forced=False)
            if proposed is not None:
                candidates.append((proposed[0], proposed[1], ai))
            elif self.plain:  # no usable clue from the AI, and no graph to fall back on: the turn passes
                return self._commit(n, Option(PASS_CLUE, 1, 0.0, 0.0, 0.0, 0.0, (), ()), {}, f"{ai}-pass",
                                    [], table.ms, forced=True)
            else:
                self._emit("fallback", turn=n)
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
        return self._last_resort(n, table.ms)

    def _options(self, seed: int, exclude: set[str]):
        def allowed(word: str) -> bool:
            return word not in exclude and self.allowed(word)

        table = self.memory.features(self.read_key, self.board, self.model, allowed=allowed)
        options = plan(self.board, table.rows, self.model, seed=seed, allowed=allowed, costs=self.costs)
        if self.learn and self.explore > 0:
            bonus = {o.clue: self.explore * disagreement(self.board, table.rows[o.clue]) for o in options}
            options = sorted(options, key=lambda o: (-(o.value + bonus[o.clue]), o.count, o.clue))
        return table, options

    def _ask_ai(self, n: int, seed: int, options) -> tuple[Option, dict] | None:
        """Up to AI_ATTEMPTS proposals; each rejected one goes back to the AI with the reason."""
        rejected: list[tuple[str, str]] = []
        for attempt in range(1, AI_ATTEMPTS + 1):
            proposal = self.chooser(self.board, [] if self.plain else options[:10], tuple(rejected))
            if not proposal:
                rejected.append(("", "no usable answer"))
                continue
            opt, strengths, reason = self._evaluate_proposal(proposal, seed)
            if opt is not None:
                return opt, strengths
            rejected.append((str(proposal[0]), reason))
            self._emit("proposal_rejected", turn=n, clue=str(proposal[0]), reason=reason, attempt=attempt)
        return None

    def _last_resort(self, n: int, ms):
        """No clue links to any team word in this memory: any legal word the partner knows, count 1."""
        from codebook.harness import clue_wordlist  # noqa: PLC0415 - avoids an import cycle

        for word in clue_wordlist():
            if self.allowed(word) and is_legal_clue(word, self.board.all_words):
                opt = Option(word, 1, 0.0, 0.0, 0.0, 0.0, self.board.team[:1], ())
                return self._commit(n, opt, {}, "codebook-last-resort", [], ms, forced=True)
        raise NoClue(f"{self.game_id} turn {n}: no legal clue at all")

    def _commit(self, n: int, opt: Option, strengths, proposer: str, options, ms, *, forced: bool):
        record = TurnRecord(n, opt.clue, opt.count, self.board.words, opt.targets,
                            dict(strengths), (), proposer, opt.value)
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
        clue = str(proposal[0]).strip().lower()
        try:
            count = int(proposal[1])
        except (TypeError, ValueError):
            return None, {}, "the count is not a number"
        if not WORD_RE.fullmatch(clue):
            return None, {}, "not one word of lowercase letters"
        if not is_legal_clue(clue, self.board.all_words):
            return None, {}, "a word on the board, part of one, or the same stem"
        if not self.allowed(clue):
            return None, {}, "your partner does not know this word"
        strengths = self.memory.clue_strengths(self.read_key, clue, self.board.words)
        rng = np.random.default_rng(seed)
        gumbel = rng.gumbel(size=(self.costs.samples, len(self.board.words)))
        costs = replace(self.costs, max_count=9) if self.plain else self.costs
        options = evaluate(self.board, clue, strengths, self.model, gumbel, costs)
        if not options:
            return None, {}, "no team words left"
        count = max(1, min(count, len(options)))
        return replace(options[count - 1]), strengths, ""

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
