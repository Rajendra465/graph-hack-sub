"""What the clue-giver sees: the unrevealed words and the secret key, plus the clue rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

from nltk.stem import PorterStemmer

TEAM, OPPONENT, NEUTRAL, ASSASSIN = "team", "opponent", "neutral", "assassin"
_KEY_ROLES = {"Red": TEAM, "Blue": OPPONENT, "Civilian": NEUTRAL, "Assassin": ASSASSIN}
WORD_RE = re.compile(r"^[a-z]+$")
_stemmer = PorterStemmer()


@lru_cache(maxsize=65536)
def stem(word: str) -> str:
    return _stemmer.stem(word)


@dataclass(frozen=True)
class BoardView:
    """Unrevealed words (lowercase, board order) with their roles from the clue-giver's key."""

    words: tuple[str, ...]
    roles: tuple[str, ...]
    all_words: tuple[str, ...]  # every word printed on the board, revealed or not

    @classmethod
    def from_harness(cls, words_on_board: Sequence[str], key_grid: Sequence[str],
                     original: Sequence[str] | None = None) -> "BoardView":
        if len(words_on_board) != len(key_grid):
            raise ValueError("board and key differ in length")
        words, roles = [], []
        for word, key in zip(words_on_board, key_grid):
            if word.startswith("*"):
                continue
            if key not in _KEY_ROLES:
                raise ValueError(f"unknown key colour {key!r}")
            words.append(word.lower())
            roles.append(_KEY_ROLES[key])
        printed = tuple(w.lower() for w in (original or words_on_board) if not w.startswith("*"))
        return cls(tuple(words), tuple(roles), printed or tuple(words))

    def role(self, word: str) -> str:
        return self.roles[self.words.index(word)]

    def with_role(self, role: str) -> tuple[str, ...]:
        return tuple(w for w, r in zip(self.words, self.roles) if r == role)

    @property
    def team(self) -> tuple[str, ...]:
        return self.with_role(TEAM)

    @property
    def assassin(self) -> str | None:
        found = self.with_role(ASSASSIN)
        return found[0] if found else None


def is_legal_clue(clue: str, printed: Iterable[str]) -> bool:
    """One lowercase word, not a board word, not inside one, and not sharing its stem."""
    if not WORD_RE.match(clue) or len(clue) < 2:
        return False
    s = stem(clue)
    for word in printed:
        if clue == word or clue in word or word in clue or stem(word) == s:
            return False
    return True
