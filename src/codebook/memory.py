"""The gatekeeper: every read and write of Codebook's memories goes through here.

Agents (Claude, Codex, the web view) never hold database credentials; they call these
operations. Everyone's memory (codebook:population) is never written after setup.
Partner memories (codebook:partner:<id>) are GRAPH.COPY clones that learn and keep a diary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from codebook import cypher as C
from codebook import keys
from codebook.board import TEAM, BoardView, is_legal_clue
from codebook.db import Db, DbError
from codebook.model import DEFAULT_STYLE, K, Choice, PartnerModel, Style, choices_from_turn, fit

LEARN_GAIN = 0.05     # each graded pick adds 5 points of link strength for this partner
LEARN_DECAY = 0.7     # each miss keeps 70% of it
CHAIN_FLOOR = 0.0005  # two-step chains weaker than this are ignored
SHORTLIST = 150


class ReadOnlyKey(PermissionError):
    """Everyone's memory, or a key outside Codebook's namespace, cannot be written."""


class NoPopulation(DbError):
    """Everyone's memory has not been built yet: run `codebook setup`."""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class FeatureTable:
    """Link strengths (direct, reverse, chain) from shortlisted clues to unrevealed words."""

    rows: Mapping[str, Mapping[str, tuple[float, ...]]]
    ms: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnRecord:
    n: int
    clue: str
    count: int
    board: tuple[str, ...]
    intended: tuple[str, ...]
    strengths: Mapping[str, tuple[float, ...]]
    guesses: tuple[tuple[str, str], ...]   # (word, role) in the order they were picked
    by: str
    value: float = 0.0


@dataclass(frozen=True)
class PartnerInfo:
    pid: str
    key: str
    style: Style
    games: int
    turns: int
    learned_words: int
    updated: str
    memory_mb: float | None


class Memory:
    def __init__(self, db: Db) -> None:
        self.db = db

    # ---------- keys ----------
    def require_population(self) -> None:
        if not self.db.exists(keys.POPULATION):
            raise NoPopulation("everyone's memory (codebook:population) is missing: run `codebook setup` first")

    def _writable(self, key: str) -> str:
        if keys.partner_of(key) is None:
            raise ReadOnlyKey(f"{key} is read-only; only partner memories learn")
        return key

    def ensure_partner(self, pid: str) -> str:
        key = keys.partner_key(pid)
        if not self.db.exists(key):
            self.require_population()
            self.db.copy_graph(keys.POPULATION, key)
            self._write_partner(key, pid, DEFAULT_STYLE, games=0, turns=0)
        return key

    def reset_partner(self, pid: str) -> str:
        key = keys.partner_key(pid)
        self.db.delete_graph(key)
        return self.ensure_partner(pid)

    def copy_partner(self, src_pid: str, dst_pid: str) -> str:
        src, dst = keys.partner_key(src_pid), keys.partner_key(dst_pid)
        if not self.db.exists(src):
            raise DbError(f"no memory for partner {src_pid}")
        self.db.delete_graph(dst)
        self.db.copy_graph(src, dst)
        self.db.query(dst, "MATCH (p:Partner) SET p.id = $id", {"id": dst_pid}, name="partner_rename")
        return dst

    def partners(self) -> list[str]:
        return [keys.partner_of(k) for k in self.db.graph_keys() if keys.partner_of(k)]

    # ---------- reading ----------
    def features(self, key: str, board: BoardView, model: PartnerModel, *,
                 allowed=lambda _w: True, shortlist: int = SHORTLIST) -> FeatureTable:
        words = list(board.words)
        params = {"board": words}
        direct = self.db.ro_query(key, C.DIRECT, params, name="direct")
        reverse = self.db.ro_query(key, C.REVERSE, params, name="reverse")
        rows: dict[str, dict[str, list[float]]] = {}
        for clue, word, s in direct.rows:
            rows.setdefault(clue, {}).setdefault(word, [0.0] * K)[0] = float(s)
        for clue, word, s in reverse.rows:
            rows.setdefault(clue, {}).setdefault(word, [0.0] * K)[1] = float(s)
        team = set(board.team)
        scored = []
        for clue, links in rows.items():
            if not allowed(clue) or not is_legal_clue(clue, board.all_words):
                continue
            linked = list(links)
            if not team.intersection(linked):
                continue
            pulls = model.pull(np.array([links[w] for w in linked], dtype=float), linked)
            team_pulls = sorted((float(p) for w, p in zip(linked, pulls) if w in team), reverse=True)
            other = max((float(p) for w, p in zip(linked, pulls) if w not in team), default=0.0)
            scored.append((sum(team_pulls[:3]) - other, clue))
        scored.sort(key=lambda t: (-t[0], t[1]))
        short = [c for _, c in scored[:shortlist]]
        chain = self.db.ro_query(key, C.CHAIN, {"clues": short, "board": words, "floor": CHAIN_FLOOR},
                                 name="chain") if short else None
        for clue, word, s in (chain.rows if chain else ()):
            rows.setdefault(clue, {}).setdefault(word, [0.0] * K)[2] = float(s)
        shared = self.db.ro_query(key, C.SHARED, {"clues": short, "board": words, "floor": CHAIN_FLOOR},
                                  name="shared") if short else None
        for clue, word, s in (shared.rows if shared else ()):
            rows.setdefault(clue, {}).setdefault(word, [0.0] * K)[3] = float(s)
        table = {c: MappingProxyType({w: tuple(v) for w, v in rows[c].items()}) for c in short}
        ms = {"direct": direct.ms, "reverse": reverse.ms, "chain": chain.ms if chain else 0.0,
              "shared": shared.ms if shared else 0.0}
        return FeatureTable(MappingProxyType(table), MappingProxyType(ms))

    def clue_strengths(self, key: str, clue: str, words: Sequence[str]) -> dict[str, tuple[float, ...]]:
        """Strengths from one clue (any word) to the given board words."""
        out = {w: [0.0] * K for w in words}
        links = self.db.ro_query(key, C.CLUE_LINKS, {"clue": clue, "board": list(words)}, name="clue_links")
        if links.rows:
            fwd, back = links.rows[0]
            for word, s in fwd:
                if word is not None and s is not None:
                    out[word][0] = float(s)
            for word, s in back:
                if word is not None and s is not None:
                    out[word][1] = float(s)
        params = {"clues": [clue], "board": list(words), "floor": CHAIN_FLOOR}
        for _, word, s in self.db.ro_query(key, C.CHAIN, params, name="chain").rows:
            out[word][2] = float(s)
        for _, word, s in self.db.ro_query(key, C.SHARED, params, name="shared").rows:
            out[word][3] = float(s)
        return {w: tuple(v) for w, v in out.items()}

    def path_to(self, key: str, clue: str, target: str) -> tuple[list[str], float] | None:
        res = self.db.ro_query(key, C.PATH_TO, {"clue": clue, "target": target}, name="path_to")
        if not res.rows:
            return None
        path, strength = res.rows[0]
        return list(path), float(strength)

    def model(self, key: str) -> PartnerModel:
        if keys.partner_of(key) is None:
            return PartnerModel(DEFAULT_STYLE)
        rows = self.db.ro_query(key, C.PARTNER_GET, name="partner_get").records()
        style = DEFAULT_STYLE
        if rows and rows[0]["direct"] is not None:
            r = rows[0]
            style = Style(float(r["direct"]), float(r["reverse"]), float(r["chain"]),
                          float(r["shared"] if r.get("shared") is not None else DEFAULT_STYLE.shared))
        bias = {w: float(b) for w, b in self.db.ro_query(key, C.BIAS_GET, name="bias_get").rows}
        return PartnerModel(style, MappingProxyType(bias))

    def info(self, pid: str) -> PartnerInfo:
        key = keys.partner_key(pid)
        rows = self.db.ro_query(key, C.PARTNER_GET, name="partner_get").records()
        r = rows[0] if rows else {}
        style = Style(*(float(r[f]) if r.get(f) is not None else getattr(DEFAULT_STYLE, f)
                        for f in ("direct", "reverse", "chain", "shared"))) if r else DEFAULT_STYLE
        learned = self.db.ro_query(key, "MATCH ()-[r:ASSOC]->() WHERE r.hits > 0 OR r.misses > 0 RETURN count(r)",
                                   name="learned_count").scalar(0)
        return PartnerInfo(pid, key, style, int(r.get("games") or 0), int(r.get("turns") or 0), int(learned or 0),
                           str(r.get("updated") or ""), self.db.memory_mb(key))

    # ---------- writing: partner keys only ----------
    def _write_partner(self, key: str, pid: str, style: Style, *, games: int, turns: int) -> None:
        self.db.query(self._writable(key), C.PARTNER_SET, {
            "id": pid, **style.as_dict(), "games": games, "turns": turns, "updated": now()}, name="partner_set")

    def start_game(self, key: str, game_id: str, seed: int, condition: str, by: str) -> None:
        self.db.query(self._writable(key), C.DIARY_GAME, {
            "game": game_id, "seed": seed, "condition": condition, "by": by, "at": now()}, name="diary_game")

    def record_turn(self, key: str, game_id: str, turn: TurnRecord) -> None:
        key = self._writable(key)
        self.db.query(key, C.DIARY_TURN, {
            "game": game_id, "n": turn.n, "clue": turn.clue, "count": turn.count, "board": list(turn.board),
            "feats": json.dumps({w: [round(x, 6) for x in v] for w, v in turn.strengths.items()}),
            "by": turn.by, "ev": round(turn.value, 4), "intended": list(turn.intended)}, name="diary_turn")
        if turn.guesses:
            self.db.query(key, C.DIARY_GUESSES, {
                "game": game_id, "n": turn.n,
                "guesses": [[w, i + 1, role] for i, (w, role) in enumerate(turn.guesses)]}, name="diary_guesses")

    def end_game(self, key: str, game_id: str, turns: int, won: bool) -> None:
        self.db.query(self._writable(key), C.DIARY_END,
                      {"game": game_id, "turns": turns, "won": won, "at": now()}, name="diary_end")

    def learn(self, key: str, turn: TurnRecord) -> tuple[int, int]:
        """Reweight this partner's links from one graded clue. Returns (hits, misses) written."""
        key = self._writable(key)
        picked = [w for w, _ in turn.guesses]
        hits = [[turn.clue, w] for w in picked]
        ended_wrong = bool(turn.guesses) and turn.guesses[-1][1] != TEAM
        misses = [[turn.clue, w] for w in turn.intended if w not in picked] if ended_wrong else []
        if hits:
            self.db.query(key, C.LEARN_HITS, {"hits": hits, "gain": LEARN_GAIN, "decay": LEARN_DECAY},
                          name="learn_hits")
        if misses:
            self.db.query(key, C.LEARN_MISSES, {"misses": misses, "gain": LEARN_GAIN, "decay": LEARN_DECAY},
                          name="learn_misses")
        return len(hits), len(misses)

    def diary_choices(self, key: str) -> tuple[list[Choice], int, int]:
        rows = self.db.ro_query(key, C.DIARY_TURNS, name="diary_turns").records()
        choices: list[Choice] = []
        games = set()
        for r in rows:
            games.add(r["game"])
            feats = json.loads(r["feats"] or "{}")
            guesses = [g for g in sorted((g for g in r["guesses"] if g[0] is not None), key=lambda g: g[0])]
            choices.extend(choices_from_turn(r["board"], feats, [g[1] for g in guesses]))
        return choices, len(games), len(rows)

    def refit(self, key: str, prior: Style = DEFAULT_STYLE) -> PartnerModel:
        """Consolidate the diary into the partner's style and word biases, and store them."""
        key = self._writable(key)
        choices, games, turns = self.diary_choices(key)
        model = fit(choices, prior)
        self.db.query(key, C.BIAS_CLEAR, name="bias_clear")
        if model.bias:
            self.db.query(key, C.BIAS_SET, {"rows": [[w, b] for w, b in sorted(model.bias.items())]},
                          name="bias_set")
        self._write_partner(key, keys.partner_of(key), model.style, games=games, turns=turns)
        return model
