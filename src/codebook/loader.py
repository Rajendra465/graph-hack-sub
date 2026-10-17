"""Build everyone's memory (codebook:population) from the Small World of Words release.

SWOW-EN18 is CC BY-NC-ND 3.0: each user downloads it from the SWOW research page after
accepting the terms. Codebook checks the published SHA-256, reads the R123 strength table
straight out of the zip, and never copies the data into the repository.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from codebook import cypher as C
from codebook import keys
from codebook.board import WORD_RE
from codebook.db import Db
from codebook.memory import now

SWOW_FILE = "SWOW-EN18.zip"
SWOW_SHA256 = "69ee1f4f19c657bb2f6e1bc27abd2becbcd01d83d1fdade94a0455b4e66eb093"
SWOW_PAGE = "https://smallworldofwords.org/en/project/research"
MIN_COUNT = 2
BATCH = 5000


class DataError(ValueError):
    """The word-association file is missing, altered, or not in the expected format."""


@dataclass(frozen=True)
class Link:
    cue: str
    response: str
    count: int
    p: float


@dataclass(frozen=True)
class LoadReport:
    words: int
    links: int
    clue_words: int
    pool_words: int
    pool_missing: tuple[str, ...]
    seconds: float


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strength_member(names: Sequence[str]) -> str:
    tables = [n for n in names if "strength" in n.lower() and n.lower().endswith((".csv", ".tsv", ".txt"))]
    for tag in ("r123", "r1"):
        found = sorted(n for n in tables if tag in n.lower().replace(".", "").replace("_", ""))
        if found:
            return found[0]
    raise DataError(f"no association-strength table in the zip (found: {', '.join(sorted(names))[:400]})")


def _clean(cell: str) -> str:
    return cell.strip().strip('"').strip()


def parse_strength(lines: Iterable[str]) -> Iterator[Link]:
    """Rows of cue, response, count, total, strength (tab- or comma-separated, header first)."""
    it = iter(lines)
    header = next(it, None)
    if header is None:
        raise DataError("empty strength table")
    sep = "\t" if "\t" in header else ","
    cols = [_clean(c).lower() for c in header.rstrip("\r\n").split(sep)]
    try:
        i_cue, i_resp = cols.index("cue"), cols.index("response")
    except ValueError as exc:
        raise DataError(f"strength table header lacks cue/response: {cols}") from exc
    i_count = next((i for i, c in enumerate(cols) if c.startswith("r1") and "strength" not in c), None)
    i_p = next((i for i, c in enumerate(cols) if "strength" in c), None)
    if i_count is None or i_p is None:
        raise DataError(f"strength table header lacks count/strength columns: {cols}")
    for line in it:
        parts = line.rstrip("\r\n").split(sep)
        if len(parts) <= max(i_cue, i_resp, i_count, i_p):
            continue
        cue, resp = _clean(parts[i_cue]).lower(), _clean(parts[i_resp]).lower()
        try:
            count, p = int(float(_clean(parts[i_count]))), float(_clean(parts[i_p]))
        except ValueError:
            continue
        yield Link(cue, resp, count, p)


def read_links(path: Path) -> list[Link]:
    with zipfile.ZipFile(path) as z:
        member = strength_member(z.namelist())
        with z.open(member) as fh:
            return list(parse_strength(io.TextIOWrapper(fh, encoding="utf-8", errors="replace")))


# ---------- fallback: ConceptNet 5.7 (CC BY-SA 4.0), used only when SWOW is unavailable ----------

CONCEPTNET_FILE = "conceptnet-assertions-5.7.0.csv.gz"
CONCEPTNET_URL = f"https://s3.amazonaws.com/conceptnet/downloads/2019/edges/{CONCEPTNET_FILE}"
CONCEPTNET_SHA256 = "accd65fe94038584295574ddc26e1500c1919c8c4532bf771811cafd0948af7e"
# Relations that read like a free association ("X makes me think of Y"); morphology and
# etymology links (FormOf, DerivedFrom, EtymologicallyRelatedTo) and external links are left out.
CN_FORWARD = {"IsA", "PartOf", "HasA", "UsedFor", "CapableOf", "AtLocation", "Causes", "HasSubevent",
              "HasFirstSubevent", "HasLastSubevent", "HasPrerequisite", "HasProperty", "MotivatedByGoal",
              "ObstructedBy", "Desires", "CreatedBy", "CausesDesire", "MadeOf", "ReceivesAction", "MannerOf",
              "SymbolOf", "DefinedAs", "Entails", "InstanceOf"}
CN_BOTH_WAYS = {"RelatedTo", "Synonym", "Antonym", "SimilarTo", "DistinctFrom", "LocatedNear"}
CN_TOP = 60  # keep each cue's strongest responses, like SWOW's long-tailed response lists
CN_SMOOTH = 5.0  # shrink shares for cues with few links (one link of three is not "33% of people")


def _cn_term(uri: str) -> str | None:
    parts = uri.split("/")  # /c/en/word[/pos[/...]]
    if len(parts) < 4 or parts[2] != "en":
        return None
    word = parts[3]
    return word if WORD_RE.match(word) else None


def parse_conceptnet(lines: Iterable[str], top: int = CN_TOP, vocab: set[str] | None = None) -> list[Link]:
    """English single-word assertions -> per-cue response shares (weight / cue total).

    `vocab` (optional) keeps the graph SWOW-sized: only words in it become nodes."""
    import json  # noqa: PLC0415

    weights: dict[str, dict[str, float]] = {}
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 5 or "/c/en/" not in cols[2] or "/c/en/" not in cols[3]:
            continue
        rel = cols[1].rsplit("/", 1)[-1]
        if rel not in CN_FORWARD and rel not in CN_BOTH_WAYS:
            continue
        a, b = _cn_term(cols[2]), _cn_term(cols[3])
        if not a or not b or a == b or (vocab is not None and (a not in vocab or b not in vocab)):
            continue
        try:
            w = float(json.loads(cols[4]).get("weight", 1.0))
        except (ValueError, AttributeError):
            continue
        pairs = ((a, b), (b, a)) if rel in CN_BOTH_WAYS else ((a, b),)
        for x, y in pairs:
            row = weights.setdefault(x, {})
            row[y] = row.get(y, 0.0) + w
    links: list[Link] = []
    for cue, row in weights.items():
        best = sorted(row.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
        total = sum(w for _, w in best) + CN_SMOOTH
        for resp, w in best:
            links.append(Link(cue, resp, max(1, round(w)), w / total))
    return links


def read_conceptnet(path: Path, vocab: set[str] | None = None) -> list[Link]:
    import gzip  # noqa: PLC0415

    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        return parse_conceptnet(fh, vocab=vocab)


def frequent_words(glove_gz: Path, limit: int = 50_000) -> set[str]:
    """The `limit` most frequent lowercase words in GloVe 6B (its file is frequency-ordered)."""
    import gzip  # noqa: PLC0415

    words: set[str] = set()
    with gzip.open(glove_gz, "rt", encoding="utf-8", errors="replace") as fh:
        next(fh, None)  # word2vec header line
        for line in fh:
            w = line.split(" ", 1)[0]
            if WORD_RE.match(w):
                words.add(w)
                if len(words) >= limit:
                    break
    return words


def select(links: Iterable[Link], clue_list: Iterable[str], pool: Iterable[str],
           min_count: int = MIN_COUNT) -> tuple[list[list], list[list]]:
    """Word rows [text, cue, clue, pool] and link rows [cue, response, p, n] to load."""
    links = list(links)
    cues = {l.cue for l in links if WORD_RE.match(l.cue)}
    kept = [l for l in links
            if l.count >= min_count and l.cue != l.response and WORD_RE.match(l.cue) and WORD_RE.match(l.response)]
    pool_set = {w.lower() for w in pool}
    clue_set = {w.lower() for w in clue_list}
    words = sorted(cues | {l.response for l in kept} | pool_set)
    word_rows = [[w, w in cues, w in clue_set and w in cues, w in pool_set] for w in words]
    link_rows = [[l.cue, l.response, round(l.p, 6), l.count] for l in kept]
    return word_rows, link_rows


def load(db: Db, word_rows: list[list], link_rows: list[list], *, dataset: str, version: str, digest: str,
         min_count: int = MIN_COUNT, key: str = keys.POPULATION, progress: Callable[[str], None] = lambda _m: None,
         ) -> int:
    """Create the population graph. The key must not exist (setup --force deletes it first)."""
    if db.exists(key):
        raise DataError(f"{key} already exists; use `codebook setup --force` to rebuild it")
    for stmt in C.SCHEMA:
        db.query(key, stmt, name="schema")
    for i in range(0, len(word_rows), BATCH):
        db.query(key, C.LOAD_WORDS, {"rows": word_rows[i:i + BATCH]}, timeout_ms=120_000, name="load_words")
    progress(f"words: {len(word_rows)}")
    for i in range(0, len(link_rows), BATCH):
        db.query(key, C.LOAD_LINKS, {"rows": link_rows[i:i + BATCH]}, timeout_ms=120_000, name="load_links")
        if (i // BATCH) % 20 == 0:
            progress(f"links: {min(i + BATCH, len(link_rows))}/{len(link_rows)}")
    db.query(key, C.SOURCE, {"dataset": dataset, "version": version, "sha256": digest, "loaded_at": now(),
                             "words": len(word_rows), "links": len(link_rows), "min_count": min_count},
             name="source")
    return len(link_rows)
