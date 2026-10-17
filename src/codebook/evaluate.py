"""The benchmark: build each partner's memory on training boards, then test on boards it never saw.

Set-ups on the same held-out boards (the engine keeps the score; a loss counts 25 turns):
  cold      Codebook with everyone's memory only (no partner memory) - the removal baseline
  warm      Codebook with this partner's own memory
  swap      Codebook with another partner's memory - is the memory specific to the partner?
  plain     an AI clue-giver with no memory at all
  handover  another AI as clue-giver, choosing from this partner's memory
Training boards use seeds 1000.., test boards 5000.. (disjoint). Test memories are frozen.
"""

from __future__ import annotations

import json
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np

from codebook import config, keys
from codebook.db import Db
from codebook.harness import play
from codebook.memory import Memory
from codebook.partners import make_partner
from codebook.session import Session

TRAIN_SEED0 = 1000
TEST_SEED0 = 5000
SWAPS = {"glove": "w2v", "w2v": "glove", "persona-mirror": "persona-leaper", "persona-leaper": "persona-mirror",
         "claude": "glove", "claude-sonnet": "glove", "codex": "glove"}
CONDITIONS = ("cold", "warm", "swap", "plain", "handover")


@dataclass(frozen=True)
class Setup:
    """How the clue-giver plays one test game: which memory it reads and who proposes clues."""

    condition: str
    read_key: str
    memory_of: str           # whose memory: "everyone" or a partner id
    chooser: str = ""        # "", "claude", "claude-sonnet", "codex"
    suggestions: bool = True


def setup_for(condition: str, pid: str, *, ai: str = "codex") -> Setup:
    if condition == "cold":
        return Setup("cold", keys.POPULATION, "everyone")
    if condition == "warm":
        return Setup("warm", keys.partner_key(pid), pid)
    if condition == "swap":
        other = SWAPS[pid]
        return Setup("swap", keys.partner_key(other), other)
    if condition == "plain":
        return Setup("plain", keys.POPULATION, "none", chooser=ai, suggestions=False)
    if condition == "handover":
        return Setup("handover", keys.partner_key(pid), pid, chooser=ai, suggestions=True)
    raise ValueError(f"unknown condition {condition!r}; choose from {', '.join(CONDITIONS)}")


def _memory() -> tuple[config.Settings, Memory]:
    settings = config.load()
    db = Db(settings)
    db.ping()
    return settings, Memory(db)


def train_partner(pid: str, games: int, *, fresh: bool = True, log: Callable[[str], None] = print) -> list[dict]:
    """Play `games` training boards with learning on. Returns one dict per game."""
    settings, memory = _memory()
    spec = make_partner(pid, settings=settings, memory=memory)
    key = memory.reset_partner(pid) if fresh else memory.ensure_partner(pid)
    model = memory.model(key)
    out = []
    for i in range(games):
        seed = TRAIN_SEED0 + i
        gid = f"{pid}-train-{seed}"
        result, session = play(lambda ev: Session(memory, key, model, gid, seed, "train", ev, write_key=key,
                                                  learn=True, allowed=spec.knows), spec.guesser_class, seed, gid)
        model = session.model
        row = {"partner": pid, "condition": "train", "memory_of": pid, **result.as_dict(),
               "style": model.style.as_dict(), "biased_words": len(model.bias)}
        out.append(row)
        log(f"[train {pid}] game {i + 1}/{games} seed {seed}: {result.turns} turns, won={result.won}, "
            f"style={model.style.as_dict()}")
    return out


def play_test_games(pid: str, condition: str, seeds: Sequence[int], ai: str = "codex") -> list[dict]:
    """Play frozen-memory test games (runs in a worker process)."""
    settings, memory = _memory()
    spec = make_partner(pid, settings=settings, memory=memory)
    setup = setup_for(condition, pid, ai=ai)
    model = memory.model(setup.read_key)
    chooser = None
    if setup.chooser:
        from codebook.partners.llm import clue_chooser  # noqa: PLC0415
        chooser = clue_chooser(setup.chooser, pid, with_suggestions=setup.suggestions)
    out = []
    for seed in seeds:
        gid = f"{pid}-{condition}-{seed}"
        result, _ = play(lambda ev: Session(memory, setup.read_key, model, gid, seed, condition, ev,
                                            allowed=spec.knows, chooser=chooser, chooser_name=setup.chooser,
                                            by=setup.chooser or "codebook"),
                         spec.guesser_class, seed, gid)
        out.append({"partner": pid, "condition": condition, "memory_of": setup.memory_of,
                    "clue_giver": setup.chooser or "codebook", **result.as_dict()})
    return out


def run_tests(jobs: Iterable[tuple[str, str]], seeds: Sequence[int], *, workers: int, sink: Path,
              ai: str = "codex", log: Callable[[str], None] = print) -> list[dict]:
    """Fan (partner, condition) jobs over worker processes, appending each game to `sink` (JSONL)."""
    tasks = []
    chunks = max(1, workers)
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for pid, condition in jobs:
            for c in range(chunks):
                part = list(seeds[c::chunks])
                if part:
                    tasks.append(pool.submit(play_test_games, pid, condition, part, ai))
        for fut in as_completed(tasks):
            batch = fut.result()
            with sink.open("a", encoding="utf-8") as fh:
                for row in batch:
                    fh.write(json.dumps(row) + "\n")
            rows.extend(batch)
            if batch:
                log(f"[test] {batch[0]['partner']}/{batch[0]['condition']}: +{len(batch)} games ({len(rows)} total)")
    return rows


# ---------------- statistics ----------------

def metrics(rows: Sequence[dict]) -> dict:
    if not rows:
        return {}
    turns = np.array([r["turns"] for r in rows], dtype=float)
    clues = sum(r["clue_count"] for r in rows)
    return {
        "games": len(rows),
        "mean_turns": round(float(turns.mean()), 3),
        "win_rate": round(float(np.mean([r["won"] for r in rows])), 3),
        "assassin_rate": round(float(np.mean([r["assassin"] for r in rows])), 3),
        "clean_clue_rate": round(sum(r["clean_clues"] for r in rows) / clues, 3) if clues else 0.0,
        "team_words_per_clue": round(sum(r["team_found"] for r in rows) / clues, 3) if clues else 0.0,
    }


def paired_diff(a: Sequence[dict], b: Sequence[dict], *, resamples: int = 10_000, seed: int = 7) -> dict | None:
    """Mean of (turns_a - turns_b) over shared seeds, with a 95% paired bootstrap interval."""
    by_seed = {r["seed"]: r["turns"] for r in b}
    pairs = [(r["turns"], by_seed[r["seed"]]) for r in a if r["seed"] in by_seed]
    if len(pairs) < 2:
        return None
    d = np.array([x - y for x, y in pairs], dtype=float)
    rng = np.random.default_rng(seed)
    boots = d[rng.integers(0, len(d), size=(resamples, len(d)))].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"n": len(d), "mean": round(float(d.mean()), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
            "a_better": bool(hi < 0)}


def summarize(rows: Sequence[dict]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if r["condition"] != "train":
            groups.setdefault((r["partner"], r["condition"]), []).append(r)
    table = {f"{p}/{c}": metrics(g) for (p, c), g in sorted(groups.items())}
    comparisons = {}
    for pid in sorted({p for p, _ in groups}):
        g = {c: groups.get((pid, c), []) for c in CONDITIONS}
        for a, b in (("warm", "cold"), ("warm", "swap"), ("handover", "plain"), ("handover", "cold")):
            diff = paired_diff(g[a], g[b]) if g[a] and g[b] else None
            if diff:
                comparisons[f"{pid}: {a} vs {b}"] = diff
    return {"table": table, "comparisons": comparisons}


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + f"-{random.randint(0, 0xffff):04x}"
