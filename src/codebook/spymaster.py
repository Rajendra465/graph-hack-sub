"""Choose a clue: score every shortlisted clue against the partner model, then rank by expected value.

For each clue the partner model gives a pull towards every unrevealed word. We simulate the
partner's picks (Gumbel-max sampling of softmax(pull), same random draws for every clue so the
comparison is fair), stopping at the first non-team word or after `count` picks, and score

    value = expected team words found - assassin_cost * P(bomb) - opponent_cost * P(opponent word)

The block (veto) is separate and has the final say: see Session.give_clue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np

from codebook.board import ASSASSIN, NEUTRAL, OPPONENT, TEAM, BoardView, is_legal_clue
from codebook.model import ZERO, PartnerModel

_CODE = {TEAM: 0, OPPONENT: 1, NEUTRAL: 2, ASSASSIN: 3}


@dataclass(frozen=True)
class Costs:
    assassin: float = 15.0
    opponent: float = 0.5
    max_count: int = 4
    samples: int = 256


@dataclass(frozen=True)
class Option:
    clue: str
    count: int
    value: float
    expected_hits: float
    p_assassin: float
    p_opponent: float
    targets: tuple[str, ...]        # the team words the partner is predicted to pick, in order
    predicted: tuple[str, ...]      # the model's top-5 words for this clue, any colour

    def as_dict(self) -> dict:
        return {
            "clue": self.clue, "count": self.count, "value": round(self.value, 3),
            "expected_hits": round(self.expected_hits, 3), "p_assassin": round(self.p_assassin, 4),
            "p_opponent": round(self.p_opponent, 4), "targets": list(self.targets),
            "predicted": list(self.predicted),
        }


def evaluate(board: BoardView, clue: str, strengths: Mapping[str, Sequence[float]], model: PartnerModel,
             gumbel: np.ndarray, costs: Costs = Costs()) -> list[Option]:
    """All counts 1..max for one clue, valued under the partner model."""
    words = board.words
    roles = np.array([_CODE[r] for r in board.roles])
    team_left = int((roles == 0).sum())
    if team_left == 0:
        return []
    x = np.array([tuple(strengths.get(w, ZERO)) for w in words], dtype=float)
    pull = model.pull(x, words)
    order = np.argsort(-(pull[None, :] + gumbel), axis=1, kind="stable")
    picked_roles = roles[order]
    bad = picked_roles != 0
    first_bad = np.where(bad.any(axis=1), bad.argmax(axis=1), len(words))
    bad_role = picked_roles[np.arange(len(order)), np.minimum(first_bad, len(words) - 1)]
    ranked = [words[i] for i in np.argsort(-pull, kind="stable")]
    team_ranked = tuple(w for w in ranked if board.role(w) == TEAM)
    out = []
    for k in range(1, min(costs.max_count, team_left) + 1):
        hits = np.minimum(first_bad, k)
        reached = first_bad < k
        p_ass = float(np.mean(reached & (bad_role == 3)))
        p_opp = float(np.mean(reached & (bad_role == 1)))
        eh = float(hits.mean())
        value = eh - costs.assassin * p_ass - costs.opponent * p_opp
        out.append(Option(clue, k, value, eh, p_ass, p_opp, team_ranked[:k], tuple(ranked[:5])))
    return out


def plan(board: BoardView, table: Mapping[str, Mapping[str, Sequence[float]]], model: PartnerModel, *,
         seed: int, allowed: Callable[[str], bool] = lambda _w: True, costs: Costs = Costs(),
         limit: int = 40) -> list[Option]:
    """Best option per clue, ranked by value (ties: fewer words, then alphabetical)."""
    rng = np.random.default_rng(seed)
    gumbel = rng.gumbel(size=(costs.samples, len(board.words)))
    best: list[Option] = []
    for clue in sorted(table):
        if not allowed(clue) or not is_legal_clue(clue, board.all_words):
            continue
        options = evaluate(board, clue, table[clue], model, gumbel, costs)
        if options:
            best.append(max(options, key=lambda o: (o.value, -o.count)))
    best.sort(key=lambda o: (-o.value, o.count, o.clue))
    return best[:limit]
