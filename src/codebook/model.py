"""How a partner picks words: a small model the clue-giver can learn from a diary.

For a clue c and a board word w, the graph gives four link strengths:
  direct  = share of people who answer w when shown c       (c -> w)
  reverse = share of people who answer c when shown w       (w -> c)
  chain   = strongest two-step chain c -> m -> w            (product of shares)
  shared  = shared associates c -> m <- w                   (sum over m of the products)
A partner's pull towards w is  style . phi(strengths) + bias[w],  with phi(x) = log(1 + 100 x),
and the partner picks among the unrevealed words with probability softmax(pull).

Everyone's memory uses DEFAULT_STYLE and no biases. A partner's memory refits the
style and per-word biases from that partner's diary (maximum a posteriori, with a
pull back towards the default so a few games cannot swing it far).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

FEATURES = ("direct", "reverse", "chain", "shared")
K = len(FEATURES)
PHI_SCALE = 100.0
ZERO = (0.0, 0.0, 0.0, 0.0)


def phi(x: np.ndarray) -> np.ndarray:
    return np.log1p(PHI_SCALE * np.clip(np.asarray(x, dtype=float), 0.0, None))


@dataclass(frozen=True)
class Style:
    # Default: with direct = 1, picks are proportional to the share of people who give the
    # word (phi ~ log p). People pick the most associated word rather than sampling, so the
    # default is sharper (x3). Set on training board 1003, where a flatter default never trusted
    # a two-word clue ("COIN 3 -> change, mint, round" only appears at this sharpness).
    direct: float = 3.0
    reverse: float = 1.5
    chain: float = 1.5
    shared: float = 1.5

    def vector(self) -> np.ndarray:
        return np.array([self.direct, self.reverse, self.chain, self.shared], dtype=float)

    @classmethod
    def from_vector(cls, v: Sequence[float]) -> "Style":
        return cls(*(round(float(x), 4) for x in v))

    def as_dict(self) -> dict[str, float]:
        return {"direct": self.direct, "reverse": self.reverse, "chain": self.chain, "shared": self.shared}


DEFAULT_STYLE = Style()


@dataclass(frozen=True)
class PartnerModel:
    style: Style = DEFAULT_STYLE
    bias: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    def pull(self, strengths: np.ndarray, words: Sequence[str]) -> np.ndarray:
        """strengths: (n_words, K) raw link strengths, rows aligned with words."""
        base = phi(strengths) @ self.style.vector()
        if not self.bias:
            return base
        return base + np.array([self.bias.get(w, 0.0) for w in words], dtype=float)


@dataclass(frozen=True)
class Choice:
    """One guess: the partner picked words[chosen]; strengths rows align with words."""

    words: tuple[str, ...]
    strengths: np.ndarray
    chosen: int


def choices_from_turn(board: Sequence[str], strengths: Mapping[str, Sequence[float]],
                      guesses: Sequence[str]) -> list[Choice]:
    """Turn one clue's guesses into sequential choices among the words still unrevealed."""
    remaining = list(board)
    out: list[Choice] = []
    for g in guesses:
        if g not in remaining:
            break
        x = np.array([tuple(strengths.get(w, ZERO)) for w in remaining], dtype=float)
        out.append(Choice(tuple(remaining), x, remaining.index(g)))
        remaining.remove(g)
    return out


def _pack(choices: Sequence[Choice], index: Mapping[str, int]):
    width = max(len(c.words) for c in choices)
    n = len(choices)
    feats = np.zeros((n, width, len(FEATURES)))
    mask = np.zeros((n, width), dtype=bool)
    ids = np.zeros((n, width), dtype=int)
    chosen = np.zeros(n, dtype=int)
    for i, c in enumerate(choices):
        k = len(c.words)
        feats[i, :k] = phi(c.strengths)
        mask[i, :k] = True
        ids[i, :k] = [index[w] for w in c.words]
        chosen[i] = c.chosen
    return feats, mask, ids, chosen


def _softmax(scores: np.ndarray, mask: np.ndarray) -> np.ndarray:
    s = np.where(mask, scores, -np.inf)
    s = s - s.max(axis=1, keepdims=True)
    e = np.where(mask, np.exp(s), 0.0)
    return e / e.sum(axis=1, keepdims=True)


def fit(choices: Sequence[Choice], prior: Style = DEFAULT_STYLE, *, style_strength: float = 2.0,
        bias_strength: float = 1.0, steps: int = 300, lr: float = 0.05) -> PartnerModel:
    """MAP fit of style and per-word bias (Adam on the summed log-likelihood)."""
    if not choices:
        return PartnerModel(prior)
    vocab = sorted({w for c in choices for w in c.words})
    index = {w: i for i, w in enumerate(vocab)}
    feats, mask, ids, chosen = _pack(choices, index)
    rows = np.arange(len(choices))
    theta0 = prior.vector()
    params = np.concatenate([theta0, np.zeros(len(vocab))])
    m = np.zeros_like(params)
    v = np.zeros_like(params)
    for t in range(1, steps + 1):
        theta, bias = params[:K], params[K:]
        p = _softmax(feats @ theta + bias[ids], mask)
        g_theta = (feats[rows, chosen] - np.einsum("nw,nwk->nk", p, feats)).sum(axis=0)
        g_theta -= style_strength * (theta - theta0)
        g_bias = np.zeros(len(vocab))
        np.add.at(g_bias, ids[mask], -p[mask])
        np.add.at(g_bias, ids[rows, chosen], 1.0)
        g_bias -= bias_strength * bias
        grad = np.concatenate([g_theta, g_bias])
        m = 0.9 * m + 0.1 * grad
        v = 0.999 * v + 0.001 * grad * grad
        params = params + lr * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    style = Style.from_vector(params[:K])
    bias = {w: round(float(params[K + i]), 4) for w, i in index.items() if abs(params[K + i]) >= 0.05}
    return PartnerModel(style, MappingProxyType(bias))


def log_likelihood(model: PartnerModel, choices: Sequence[Choice]) -> tuple[float, float]:
    """Mean log-probability of the partner's actual picks, and top-1 accuracy."""
    if not choices:
        return 0.0, 0.0
    total, hits = 0.0, 0
    for c in choices:
        pull = model.pull(c.strengths, c.words)
        pull = pull - pull.max()
        logp = pull - np.log(np.exp(pull).sum())
        total += float(logp[c.chosen])
        hits += int(int(np.argmax(pull)) == c.chosen)
    return total / len(choices), hits / len(choices)
