"""Test partners with planted quirks. We hold their answer key, so we can check what the memory learned.

A persona reads everyone's memory (read-only) and picks words with its own planted style and a
planted set of favourite board words, plus a little seeded noise:
  persona-mirror  thinks backwards: "which board word makes me think of the clue?"
  persona-leaper  jumps two steps: clue -> something -> board word
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from codebook import keys
from codebook.harness import engine, pool_words
from codebook.model import PartnerModel, Style
from codebook.partners import PartnerSpec


@dataclass(frozen=True)
class Persona:
    pid: str
    style: Style
    favourites: int
    boost: float
    noise: float
    seed: int
    label: str

    def favourite_words(self) -> dict[str, float]:
        chosen = random.Random(self.seed).sample(sorted(pool_words()), self.favourites)
        return {w: self.boost for w in sorted(chosen)}

    def model(self) -> PartnerModel:
        return PartnerModel(self.style, MappingProxyType(self.favourite_words()))


# Styles are sharp on purpose: the planted habit should decide most picks, with favourites
# and a little noise on top, so we can check the memory recovers what we planted.
PERSONAS = {
    "persona-mirror": Persona("persona-mirror", Style(0.6, 6.0, 0.6, 0.6), 20, 1.0, 0.15, 11,
                              "planted test partner: reverse associations, 20 favourite words"),
    "persona-leaper": Persona("persona-leaper", Style(1.2, 0.6, 6.0, 1.2), 20, 1.0, 0.15, 23,
                              "planted test partner: two-step chains, 20 favourite words"),
}


def partner(pid: str, memory) -> PartnerSpec:
    engine()
    from players.guesser import Guesser  # noqa: PLC0415 - vendored package

    persona = PERSONAS[pid]
    model = persona.model()

    class PersonaGuesser(Guesser):
        def __init__(self):
            super().__init__()
            self.words, self.clue, self.left, self.cache = [], "", 0, {}

        def set_board(self, words):
            self.words = words

        def set_clue(self, clue, num):
            self.clue, self.left, self.cache = clue.lower(), int(num), {}

        def keep_guessing(self):
            return self.left > 0

        def get_answer(self):
            live = [w.lower() for w in self.words if not w.startswith("*")]
            if not set(live) <= set(self.cache):  # links for this clue, read once per clue
                self.cache = memory.clue_strengths(keys.POPULATION, self.clue, live)
            strengths = self.cache
            pull = model.pull(np.array([strengths[w] for w in live], dtype=float), live)
            rng = np.random.default_rng(zlib.crc32(f"{pid}:{self.clue}:{','.join(sorted(live))}".encode()))
            pull = pull + persona.noise * rng.gumbel(size=len(live))
            self.left -= 1
            return live[int(np.argmax(pull))].upper()

    PersonaGuesser.__name__ = "".join(p.title() for p in pid.split("-"))
    return PartnerSpec(pid, "persona", persona.label, lambda _w: True, PersonaGuesser)
