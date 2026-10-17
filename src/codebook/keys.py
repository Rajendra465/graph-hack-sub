"""FalkorDB key names. Every graph Codebook touches lives under `codebook:`.

- `codebook:population` is everyone's memory: built once at setup, read-only after.
- `codebook:partner:<id>` is one partner's memory: a GRAPH.COPY of the population
  that learns from every graded guess, plus that partner's diary of games.
"""

from __future__ import annotations

import re

PREFIX = "codebook:"
POPULATION = "codebook:population"
PARTNER_PREFIX = "codebook:partner:"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


class BadPartnerId(ValueError):
    """A partner id must be lowercase letters, digits, '-' or '_' (max 48)."""


def check_partner_id(pid: str) -> str:
    if not isinstance(pid, str) or not _ID_RE.match(pid):
        raise BadPartnerId(f"bad partner id {pid!r}: use lowercase letters, digits, '-' or '_'")
    return pid


def partner_key(pid: str) -> str:
    return PARTNER_PREFIX + check_partner_id(pid)


def partner_of(key: str) -> str | None:
    """The partner id inside a partner key, or None for any other key."""
    if not key.startswith(PARTNER_PREFIX):
        return None
    pid = key[len(PARTNER_PREFIX):]
    return pid if _ID_RE.match(pid) else None


def is_codebook_key(key: str) -> bool:
    return key == POPULATION or partner_of(key) is not None


def acl_user(pid: str) -> str:
    """The Redis ACL user that may touch only this partner's key."""
    return "cb-" + check_partner_id(pid)
