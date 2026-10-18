"""The graph endpoints over HTTP (database index 15, synthetic data): good requests answer, bad ones get a 4xx."""

from __future__ import annotations

import dataclasses
import re

import pytest
from starlette.testclient import TestClient

from codebook.web import MAX_QUERY_EVENTS, MAX_SEED, LiveGame, create_app

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


PUBLIC_HOST = "demo-space.hf.space"


@pytest.fixture(scope="module")
def public_client(population, test_settings) -> TestClient:
    settings = dataclasses.replace(test_settings, public_host=PUBLIC_HOST)
    return TestClient(create_app(settings), base_url=f"https://{PUBLIC_HOST}")


def test_a_local_app_refuses_other_hosts(client):
    assert client.get("/api/cypher", headers={"host": "evil.example"}).status_code == 400


def test_the_public_demo_answers_on_its_own_host(public_client):
    assert public_client.get("/api/cypher").status_code == 200


def test_the_public_demo_takes_writes_only_from_its_own_page(public_client):
    body = {"partner": "glove", "learn": True, "seed": 5000}
    other = public_client.post("/api/game", json=body, headers={"origin": "https://evil.example"})
    assert other.status_code == 403
    own = public_client.post("/api/game", json=body, headers={"origin": f"https://{PUBLIC_HOST}"})
    assert own.status_code == 400 and "public demo" in own.json()["error"]  # past the origin check


def test_the_public_demo_takes_writes_from_whichever_address_serves_it(population, test_settings):
    run_host = "codebook-123.asia-south1.run.app"  # a second address for the same deployment
    app = create_app(dataclasses.replace(test_settings, public_host=PUBLIC_HOST))
    served = TestClient(app, base_url=f"https://{run_host}")
    body = {"partner": "glove", "learn": True, "seed": 5000}
    own = served.post("/api/game", json=body, headers={"origin": f"https://{run_host}"})
    assert own.status_code == 400 and "public demo" in own.json()["error"]  # past the origin check
    other = served.post("/api/game", json=body, headers={"origin": "https://evil.example"})
    assert other.status_code == 403


@pytest.mark.parametrize("body", [
    {"partner": "glove", "learn": True},                   # would change a benchmark memory
    {"partner": "claude"},                                 # an AI guesser calls a model every turn
    {"partner": "glove", "clue_giver": "claude-sonnet"},   # a live AI clue-giver calls a model
])
def test_the_public_demo_refuses_bot_learning_and_live_ai(public_client, body):
    r = public_client.post("/api/game", json={"seed": 5000, **body})
    assert r.status_code == 400
    assert "public demo" in r.json()["error"]


def test_the_public_demo_still_replays_an_ai_from_the_log(public_client):
    body = {"seed": MAX_SEED - 1, "partner": "glove", "clue_giver": "claude-sonnet", "replay": True}
    r = public_client.post("/api/game", json=body)
    assert r.status_code == 400
    assert "public demo" not in r.json()["error"]  # refused only because this board has no logged game


def test_the_game_cap_comes_from_the_settings(population, test_settings):
    capped = TestClient(create_app(dataclasses.replace(test_settings, max_games=0)), base_url="http://127.0.0.1")
    r = capped.post("/api/game", json={"partner": "w2v", "seed": 5000})
    assert r.status_code == 429 and "0 games" in r.json()["error"]


@pytest.mark.parametrize("raw", [b"{not json", b'{"seed": Infinity}', b"[1, 2]"])
def test_a_malformed_game_request_is_a_400(client, raw):
    r = client.post("/api/game", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_a_malformed_since_is_a_400(client):
    assert client.get("/api/game/no-such-game", params={"since": "abc"}).status_code == 400


def test_a_request_body_over_4_kb_is_refused(client):
    r = client.post("/api/game", json={"partner": "nobody", "pad": "x" * 5000})
    assert r.status_code == 413


def test_a_game_keeps_a_bounded_number_of_query_events():
    game = LiveGame("live-test-cap", "glove", "everyone", "k", 5000, "watch", False, "codebook", 0.0, [], [])
    for _ in range(MAX_QUERY_EVENTS + 5):
        game.add({"kind": "query"})
    game.add({"kind": "end"})
    kinds = [e["kind"] for e in game.events]
    assert kinds.count("query") == MAX_QUERY_EVENTS and kinds[-1] == "end"


def test_the_page_and_every_file_it_loads_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and 'id="graph3d"' in page.text
    files = re.findall(r'"/static/([\w.-]+)"', page.text)
    assert {"app.css", "app.js", "graph3d.js", "tour.js", "panels.js", "scenarios.js"} <= set(files)
    for name in files:
        assert client.get(f"/static/{name}").status_code == 200, name
