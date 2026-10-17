"""Shared fixtures. Contract tests use FalkorDB database index 15 (never the real keys in index 0)."""

from __future__ import annotations

import os

os.environ["CODEBOOK_KEY_PREFIX"] = "cbtest:"  # before any codebook import: tests never share key names

import pytest  # noqa: E402

from codebook import config, keys  # noqa: E402
from codebook.db import Db, DbError  # noqa: E402

TEST_DB_INDEX = os.environ.get("CODEBOOK_TEST_DB_INDEX", "15")


@pytest.fixture(scope="session")
def test_settings() -> config.Settings:
    env = dict(os.environ)
    env["CODEBOOK_DB_INDEX"] = TEST_DB_INDEX
    env["CODEBOOK_DB_PORT"] = os.environ.get("CODEBOOK_TEST_PORT", "6390")
    return config.load(env)


@pytest.fixture(scope="session")
def db(test_settings) -> Db:
    d = Db(test_settings)
    try:
        d.ping()
    except DbError as exc:
        pytest.skip(f"no FalkorDB for contract tests: {exc}")
    return d


def wipe(d: Db) -> None:
    for key in d.graph_keys():
        if key.startswith(keys.PREFIX):
            d.delete_graph(key)


@pytest.fixture(scope="session")
def population(db):
    from synthetic import build

    from codebook import loader

    wipe(db)
    words, links = build()
    loader.load(db, words, links, dataset="synthetic", version="test", digest="0" * 64)
    yield db
    wipe(db)
