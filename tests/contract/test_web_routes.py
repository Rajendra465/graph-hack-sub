"""The graph endpoints over HTTP (database index 15, synthetic data): good requests answer, bad ones get a 4xx."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from codebook.web import create_app

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def client(population, test_settings) -> TestClient:
    return TestClient(create_app(test_settings), base_url="http://127.0.0.1")  # a host TrustedHostMiddleware allows


def test_board_graph_route_returns_the_graph(client):
    r = client.get("/api/graph", params={"seed": "5000", "memory": "everyone"})
    assert r.status_code == 200
    body = r.json()
    assert body["seed"] == 5000
    assert len([n for n in body["nodes"] if n["kind"] == "board"]) == 25


@pytest.mark.parametrize("params", [{"clue": "../x"}, {"seed": "abc"}, {"memory": "W2V!"}, {"memory": "nobody-here"}])
def test_board_graph_route_refuses_bad_requests(client, params):
    r = client.get("/api/graph", params={"seed": "5000", **params})
    assert r.status_code == 400
    assert "error" in r.json()


def test_game_graph_route_answers_404_and_400(client):
    assert client.get("/api/game/no-such-game/graph").status_code == 404
    assert client.get("/api/game/no-such-game/graph", params={"turn": "0"}).status_code == 400
