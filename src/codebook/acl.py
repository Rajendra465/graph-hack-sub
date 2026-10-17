"""Per-partner database users: each may read everyone's memory and read/write only its own partner key.

    ACL SETUSER cb-<partner> reset on ><password> resetkeys ~codebook:partner:<partner>
        +ping +select +graph.query +graph.ro_query (~codebook:population +graph.ro_query)

FalkorDB 6.0.2 declares even GRAPH.RO_QUERY as read-write key access, so Redis's read-only key
pattern (%R~) cannot express "read-only on everyone's memory". A selector can: on the population
key the user may run GRAPH.RO_QUERY and nothing else, and FalkorDB rejects writes inside
RO_QUERY. Keyless commands (GRAPH.LIST, KEYS, SCAN, FLUSHALL) are not granted, so one partner's
process cannot list or touch another partner's memory. The password is printed once, never stored.
"""

from __future__ import annotations

import secrets

from codebook import keys
from codebook.db import Db

COMMANDS = ("+ping", "+select", "+graph.query", "+graph.ro_query")


def grant(db: Db, pid: str) -> tuple[str, str]:
    user, key = keys.acl_user(pid), keys.partner_key(pid)
    password = secrets.token_urlsafe(24)
    db.command("ACL", "SETUSER", user, "reset", "on", f">{password}", "resetkeys", f"~{key}", *COMMANDS,
               f"(~{keys.POPULATION} +graph.ro_query)")
    return user, password


def revoke(db: Db, pid: str) -> None:
    db.command("ACL", "DELUSER", keys.acl_user(pid))


def describe(db: Db, pid: str) -> list:
    return db.command("ACL", "GETUSER", keys.acl_user(pid)) or []
