"""Partners are the guessers Codebook gives clues to. Each one is an engine Guesser class.

- glove, w2v              the competition's own embedding guessers, unmodified
- persona-mirror/-leaper  test partners with planted quirks (we hold their answer key)
- claude, claude-sonnet   Claude Code headless (`claude -p`)
- codex                   Codex CLI (`codex exec`)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class UnknownPartner(ValueError):
    """No partner with that id."""


@dataclass(frozen=True)
class PartnerSpec:
    pid: str
    kind: str
    label: str
    knows: Callable[[str], bool]
    guesser_class: type


EMBEDDING = ("glove", "w2v")
PERSONAS = ("persona-mirror", "persona-leaper")
LLMS = ("claude", "claude-sonnet", "codex")
ALL = EMBEDDING + PERSONAS + LLMS


def make_partner(pid: str, *, settings, memory) -> PartnerSpec:
    if pid in EMBEDDING:
        from codebook.partners import embedding
        return embedding.partner(pid, settings)
    if pid in PERSONAS:
        from codebook.partners import persona
        return persona.partner(pid, memory)
    if pid in LLMS:
        from codebook.partners import llm
        return llm.partner(pid)
    raise UnknownPartner(f"unknown partner {pid!r}; choose from {', '.join(ALL)}")
