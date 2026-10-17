"""The competition's own GloVe and word2vec guessers, unmodified, as partners.

Vectors come from the gensim-data releases: glove-wiki-gigaword-300 (Stanford glove.6B.300d)
and word2vec-google-news-300. Setup keeps only the words a game can use (the clue list, the
board pool and SWOW cues) in a small .npz cache; similarities between those words are unchanged.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Iterable, Iterator, Mapping

import numpy as np

from codebook.harness import engine
from codebook.partners import PartnerSpec

RELEASES = "https://github.com/RaRe-Technologies/gensim-data/releases/download"
SOURCES = {
    "glove": ("glove-wiki-gigaword-300", False, "GloVe 6B 300d (competition GloVe guesser)"),
    "w2v": ("word2vec-google-news-300", True, "word2vec Google News 300d (competition w2v guesser)"),
}


class VectorTable(Mapping[str, np.ndarray]):
    """Read-only word -> vector map; missing words raise KeyError like the engine expects."""

    def __init__(self, words: Iterable[str], vecs: np.ndarray) -> None:
        self._index = {w: i for i, w in enumerate(words)}
        self._vecs = vecs

    def __getitem__(self, word: str) -> np.ndarray:
        return self._vecs[self._index[word]]

    def __contains__(self, word: object) -> bool:
        return word in self._index

    def __iter__(self) -> Iterator[str]:
        return iter(self._index)

    def __len__(self) -> int:
        return len(self._index)


def vectors_dir(settings) -> Path:
    return settings.data_dir / "vectors"


def cache_path(settings, name: str) -> Path:
    return vectors_dir(settings) / f"{name}.npz"


def download(name: str, settings, log=print) -> Path:
    release, _, _ = SOURCES[name]
    dest = vectors_dir(settings) / f"{release}.gz"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RELEASES}/{release}/{release}.gz"
    log(f"downloading {url}")
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)
    return dest


def build_cache(name: str, settings, vocab: Iterable[str], log=print) -> Path:
    from gensim.models import KeyedVectors  # noqa: PLC0415 - heavy import, setup only

    src = download(name, settings, log)
    _, binary, _ = SOURCES[name]
    log(f"reading {src.name} (one-time, a few minutes)")
    kv = KeyedVectors.load_word2vec_format(str(src), binary=binary, unicode_errors="ignore")
    words = sorted({w for w in vocab if w in kv.key_to_index})
    vecs = np.stack([kv[w] for w in words]).astype(np.float32)
    out = cache_path(settings, name)
    np.savez_compressed(out, words=np.array(words), vecs=vecs)
    log(f"{name}: kept {len(words)} words -> {out}")
    return out


def load_table(name: str, settings) -> VectorTable:
    path = cache_path(settings, name)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `codebook setup --vectors`")
    data = np.load(path, allow_pickle=False)
    return VectorTable([str(w) for w in data["words"]], data["vecs"])


def partner(pid: str, settings) -> PartnerSpec:
    engine()
    from players import guesser_glove, guesser_w2v  # noqa: PLC0415 - vendored package

    table = load_table(pid, settings)
    base, kwarg = (guesser_glove.AIGuesser, "glove_vecs") if pid == "glove" else (guesser_w2v.AIGuesser, "word_vectors")

    class EmbeddingPartner(base):
        def __init__(self):
            super().__init__(**{kwarg: table})

        def get_answer(self):
            try:
                return super().get_answer()
            except IndexError:  # the clue is not in this partner's vocabulary
                return None

    EmbeddingPartner.__name__ = f"{pid.upper()}Partner"
    return PartnerSpec(pid, "embedding", SOURCES[pid][2], table.__contains__, EmbeddingPartner)
