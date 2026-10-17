"""A synthetic association graph shaped like SWOW (no real data), for tests against a live FalkorDB."""

from __future__ import annotations

import random

from codebook.harness import clue_wordlist, pool_words


def _strength(rng: random.Random) -> float:
    return round(min(0.6, rng.paretovariate(2.0) / 40), 4)


def build(seed: int = 7, clues: int = 1500, to_pool: int = 10, to_clues: int = 6) -> tuple[list[list], list[list]]:
    rng = random.Random(seed)
    pool = pool_words()
    pool_set = set(pool)
    clue_words = rng.sample(sorted(w for w in clue_wordlist() if w not in pool_set), clues)
    words = [[w, True, True, False] for w in clue_words] + [[w, True, False, True] for w in pool]
    links: dict[tuple[str, str], list] = {}
    for c in clue_words:
        for t in rng.sample(pool, to_pool) + rng.sample(clue_words, to_clues):
            if t != c:
                links[(c, t)] = [c, t, _strength(rng), rng.randint(2, 60)]
    for p in pool:
        for t in rng.sample(clue_words, 6):
            links[(p, t)] = [p, t, _strength(rng), rng.randint(2, 60)]
    return words, list(links.values())
