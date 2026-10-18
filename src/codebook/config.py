"""Settings read from environment variables, with defaults that work for a local run."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:\d{1,5})?")


class ConfigError(ValueError):
    """A setting has an invalid value."""


@dataclass(frozen=True)
class Settings:
    db_host: str = "127.0.0.1"
    db_port: int = 6390
    db_user: str = ""
    db_password: str = field(default="", repr=False)
    db_index: int = 0
    home: Path = Path(".")
    ui_host: str = "127.0.0.1"
    ui_port: int = 7811
    public_host: str = ""  # a public deployment's host name; empty for a local run (see web.LiveApp)
    max_games: int = 4  # live-view games playing at once
    human_wait_s: int = 300  # an unanswered human turn ends the game after this long

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def results_dir(self) -> Path:
        return self.home / "results"


def _int(env: Mapping[str, str], name: str, default: int, lo: int = 1, hi: int = 65535) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _host(env: Mapping[str, str], name: str) -> str:
    raw = env.get(name, "").strip().lower()
    if raw and not _HOST.fullmatch(raw):
        raise ConfigError(f"{name} must be a host name such as demo.hf.space, got {raw!r}")
    return raw


def load(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        db_host=env.get("CODEBOOK_DB_HOST", "127.0.0.1"),
        db_port=_int(env, "CODEBOOK_DB_PORT", 6390),
        db_user=env.get("CODEBOOK_DB_USER", ""),
        db_password=env.get("CODEBOOK_DB_PASSWORD", ""),
        db_index=_int(env, "CODEBOOK_DB_INDEX", 0, lo=0, hi=15),
        home=Path(env.get("CODEBOOK_HOME", ".")).resolve(),
        ui_host=env.get("CODEBOOK_UI_HOST", "127.0.0.1"),
        ui_port=_int(env, "CODEBOOK_UI_PORT", 7811),
        public_host=_host(env, "CODEBOOK_PUBLIC_HOST"),
        max_games=_int(env, "CODEBOOK_MAX_GAMES", 4, lo=1, hi=64),
        human_wait_s=_int(env, "CODEBOOK_HUMAN_WAIT_S", 300, lo=10, hi=3600),
    )
