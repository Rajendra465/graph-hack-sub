"""The only module that talks to FalkorDB.

- Queries always use `--compact` (verbose mode stringifies lists and maps on 6.0.2).
- Parameters go in a `CYPHER k=v ...` prefix built by `encode()`.
- Results are parsed into plain Python values; graph entities are rejected
  (queries must RETURN scalars, lists or maps).
- There is no fallback store. If FalkorDB is unreachable, Codebook stops and says so.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import redis

from codebook.config import Settings

log = logging.getLogger(__name__)

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Compact-mode value types, probed on falkordb/falkordb:6.0.2.
T_NULL, T_STRING, T_INTEGER, T_BOOLEAN, T_DOUBLE, T_ARRAY = 1, 2, 3, 4, 5, 6
T_EDGE, T_NODE, T_PATH, T_MAP, T_POINT, T_VECTOR = 7, 8, 9, 10, 11, 12


class DbError(Exception):
    """A FalkorDB/Redis error."""


class NoPermission(DbError):
    """The server refused the command for this user (ACL)."""


class QueryTimeout(DbError):
    """The query exceeded its timeout."""


class EmptyKey(DbError):
    """A read-only query hit a graph key that does not exist."""


class Unreachable(DbError):
    """FalkorDB could not be reached. Codebook has no fallback store: fail loudly."""


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    stats: Mapping[str, str]
    ms: float

    def records(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]

    def scalar(self, default: Any = None) -> Any:
        return self.rows[0][0] if self.rows else default

    def stat(self, name: str) -> int:
        """Integer write statistic such as 'Nodes created'; 0 when absent."""
        raw = self.stats.get(name)
        if raw is None:
            return 0
        try:
            return int(float(raw.split()[0]))
        except (ValueError, IndexError):
            return 0


@dataclass(frozen=True)
class QueryEvent:
    key: str
    name: str
    cypher: str
    params: str
    ms: float
    ro: bool
    ok: bool
    rows: int = 0
    error: str = ""


def _quote(s: str) -> str:
    s = _CONTROL_RE.sub("", s)
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{s}"'


def _ident(k: str) -> str:
    if not IDENT_RE.match(k):
        raise ValueError(f"invalid parameter or map key {k!r}")
    return k


def encode(value: Any) -> str:
    """Encode a Python value as a Cypher literal for the CYPHER parameter prefix."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float parameter")
        return repr(value)
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return "[" + ",".join(encode(v) for v in value) + "]"
    if isinstance(value, Mapping):
        return "{" + ",".join(f"{_ident(str(k))}:{encode(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"cannot encode {type(value).__name__} as a Cypher literal")


def params_prefix(values: Mapping[str, Any] | None) -> str:
    if not values:
        return ""
    return "CYPHER " + " ".join(f"{_ident(k)}={encode(v)}" for k, v in values.items()) + " "


def parse_value(cell: Any) -> Any:
    if not isinstance(cell, list) or len(cell) != 2 or not isinstance(cell[0], int):
        return cell
    kind, value = cell
    if kind == T_NULL:
        return None
    if kind == T_STRING:
        return value
    if kind == T_INTEGER:
        return int(value)
    if kind == T_BOOLEAN:
        return value in ("true", True, 1)
    if kind == T_DOUBLE:
        return float(value)
    if kind == T_ARRAY:
        return [parse_value(v) for v in value]
    if kind == T_MAP:
        return {value[i]: parse_value(value[i + 1]) for i in range(0, len(value), 2)}
    if kind == T_VECTOR:
        return [float(v) for v in value]
    if kind in (T_NODE, T_EDGE, T_PATH):
        raise DbError("queries must RETURN scalars, lists or maps, not graph entities")
    return value


def parse_result(raw: Sequence[Any], ms: float) -> QueryResult:
    if len(raw) == 3:
        header, rows, stats = raw
        columns = tuple(h[1] if isinstance(h, list) else h for h in header)
        parsed = tuple(tuple(parse_value(c) for c in row) for row in rows)
    else:
        columns, parsed, stats = (), (), (raw[-1] if raw else [])
    stat_map: dict[str, str] = {}
    for item in stats or []:
        name, _, val = str(item).partition(":")
        stat_map[name.strip()] = val.strip()
    return QueryResult(columns, parsed, stat_map, ms)


def summarize(values: Mapping[str, Any] | None, width: int = 80) -> str:
    if not values:
        return ""
    parts = []
    for k, v in values.items():
        text = encode(v)
        parts.append(f"{k}={text[:width]}{'…' if len(text) > width else ''}")
    return " ".join(parts)


def translate_error(exc: Exception) -> DbError:
    msg = str(exc)
    low = msg.lower()
    if isinstance(exc, (redis.ConnectionError, redis.TimeoutError)) and not isinstance(exc, redis.ResponseError):
        return Unreachable(f"FalkorDB unreachable: {msg.rstrip('. ')}. Start it with `docker compose up -d`.")
    if "noperm" in low or "no permissions" in low:
        return NoPermission(msg)
    if "timed out" in low or "timeout" in low:
        return QueryTimeout(msg)
    if "empty key" in low:
        return EmptyKey(msg)
    return DbError(msg)


class Db:
    """FalkorDB client. Thread-safe (redis-py connection pool)."""

    def __init__(self, settings: Settings, username: str | None = None, password: str | None = None,
                 *, max_connections: int = 32) -> None:
        self.settings = settings
        user = username if username is not None else (settings.db_user or None)
        secret = password if password is not None else (settings.db_password or None)
        common = dict(host=settings.db_host, port=settings.db_port, db=settings.db_index, username=user,
                      password=secret, max_connections=max_connections, socket_connect_timeout=5,
                      socket_timeout=150, health_check_interval=30)
        self._r = redis.Redis(decode_responses=True, **common)
        self._rb = redis.Redis(decode_responses=False, **common)  # DUMP/RESTORE payloads are bytes
        self.username = user or "default"
        self._listeners: list[Callable[[QueryEvent], None]] = []
        self._lock = threading.Lock()

    @property
    def redis(self) -> redis.Redis:
        return self._r

    def on_query(self, callback: Callable[[QueryEvent], None]) -> None:
        with self._lock:
            self._listeners.append(callback)

    def ping(self) -> None:
        try:
            self._r.ping()
        except Exception as exc:  # noqa: BLE001 - translate everything
            raise translate_error(exc) from exc

    def command(self, *args: Any) -> Any:
        try:
            return self._r.execute_command(*args)
        except (redis.ResponseError, redis.ConnectionError, redis.TimeoutError) as exc:
            raise translate_error(exc) from exc

    def exists(self, key: str) -> bool:
        return bool(self.command("EXISTS", key))

    def graph_keys(self) -> list[str]:
        return sorted(self.command("GRAPH.LIST") or [])

    def copy_graph(self, src: str, dst: str) -> float:
        started = time.perf_counter()
        self.command("GRAPH.COPY", src, dst)
        return (time.perf_counter() - started) * 1000

    def delete_graph(self, key: str) -> None:
        try:
            self._r.execute_command("GRAPH.DELETE", key)
        except redis.ResponseError as exc:
            low = str(exc).lower()
            if "empty key" not in low and "invalid graph" not in low and "no such" not in low:
                raise translate_error(exc) from exc
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            raise translate_error(exc) from exc

    def dump(self, key: str) -> bytes:
        """The key's serialized value (Redis DUMP): a portable copy of one graph."""
        try:
            blob = self._rb.dump(key)
        except (redis.ResponseError, redis.ConnectionError, redis.TimeoutError) as exc:
            raise translate_error(exc) from exc
        if blob is None:
            raise EmptyKey(f"{key} does not exist")
        return blob

    def restore(self, key: str, blob: bytes, *, replace: bool = False) -> None:
        try:
            self._rb.restore(key, 0, blob, replace=replace)
        except (redis.ResponseError, redis.ConnectionError, redis.TimeoutError) as exc:
            raise translate_error(exc) from exc

    def memory_mb(self, key: str) -> float | None:
        """GRAPH.MEMORY USAGE in MB (total), or None if the server cannot say."""
        try:
            raw = self._r.execute_command("GRAPH.MEMORY", "USAGE", key)
        except redis.ResponseError:
            return None
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            raise translate_error(exc) from exc
        if isinstance(raw, list):
            pairs = dict(zip(raw[::2], raw[1::2]))
            for name in ("total_graph_sz_mb", "total_graph_size_mb"):
                if name in pairs:
                    return float(pairs[name])
        return None

    def query(self, key: str, text: str, params: Mapping[str, Any] | None = None, *,
              timeout_ms: int = 30000, name: str = "") -> QueryResult:
        return self._execute("GRAPH.QUERY", key, text, params, timeout_ms, name, ro=False)

    def ro_query(self, key: str, text: str, params: Mapping[str, Any] | None = None, *,
                 timeout_ms: int = 30000, name: str = "") -> QueryResult:
        return self._execute("GRAPH.RO_QUERY", key, text, params, timeout_ms, name, ro=True)

    def _execute(self, cmd: str, key: str, text: str, params: Mapping[str, Any] | None,
                 timeout_ms: int, name: str, *, ro: bool) -> QueryResult:
        full = params_prefix(params) + text
        started = time.perf_counter()
        ok, err, rows = True, "", 0
        try:
            raw = self._r.execute_command(cmd, key, full, "--compact", "TIMEOUT", int(timeout_ms))
            result = parse_result(raw, (time.perf_counter() - started) * 1000)
            rows = len(result.rows)
            return result
        except (redis.ResponseError, redis.ConnectionError, redis.TimeoutError) as exc:
            ok, err = False, str(exc)
            raise translate_error(exc) from exc
        finally:
            ms = (time.perf_counter() - started) * 1000
            self._emit(QueryEvent(key, name, text.strip(), summarize(params), ms, ro, ok, rows, err))

    def _emit(self, event: QueryEvent) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - a listener must never break a query
                log.exception("query listener failed")
