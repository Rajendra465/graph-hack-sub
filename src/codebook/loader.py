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
