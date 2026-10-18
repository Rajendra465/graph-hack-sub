"""The 3D view's graph comes from real read-only queries on a memory (database index 15, synthetic data)."""

from __future__ import annotations

import pytest

from codebook import keys
from codebook.board import BoardView
from codebook.graphview import GraphRequest, clue_graph
from codebook.harness import board_for_seed
from codebook.memory import Memory
from codebook.web import LiveApp, LiveGame

pytestmark = pytest.mark.contract
KINDS = {"direct", "reverse", "chain", "bomb"}


def _board() -> BoardView:
    words, key = board_for_seed(5000)
    return BoardView.from_harness(words, key)


def _linked_clue(population, board: BoardView) -> str:
    """The clue word with the most direct links into this board."""
    q = ("MATCH (c:Word)-[:ASSOC]->(w:Word) WHERE c.clue AND w.text IN $board AND NOT c.text IN $board "
         "RETURN c.text, count(w) AS n ORDER BY n DESC, c.text LIMIT 1")
    return population.ro_query(keys.POPULATION, q, {"board": list(board.words)}).rows[0][0]


def _bomb_clue(population, board: BoardView) -> str | None:
    """A clue word with a chain of one or two links to this board's bomb."""
    q = ("MATCH (c:Word)-[:ASSOC*1..2]->(a:Word {text: $bomb}) WHERE c.clue AND NOT c.text IN $board "
         "RETURN DISTINCT c.text LIMIT 1")
    rows = population.ro_query(keys.POPULATION, q, {"bomb": board.assassin, "board": list(board.words)}).rows
    return rows[0][0] if rows else None


def _graph(population, clue: str, *, revealed=frozenset(), max_via: int = 30) -> tuple[BoardView, dict]:
    board = _board()
    graph = clue_graph(Memory(population), keys.POPULATION, board.words, board.roles, revealed, clue, max_via=max_via)
    return board, graph


def test_every_board_word_is_a_node_with_its_role(population):
    board = _board()
    _, g = _graph(population, _linked_clue(population, board), revealed={board.words[0]})
    nodes = {n["id"]: n for n in g["nodes"]}
    for w, r in zip(board.words, board.roles):
        assert nodes[w]["kind"] == "board" and nodes[w]["role"] == r
    assert nodes[board.words[0]]["revealed"] is True
    assert nodes[board.words[1]]["revealed"] is False
    assert nodes[g["clue"]]["kind"] == "clue"


def test_links_are_typed_and_point_at_nodes(population):
    board = _board()
    _, g = _graph(population, _linked_clue(population, board))
    ids = {n["id"] for n in g["nodes"]}
    assert g["links"], "a clue linked to the board must have links"
    for link in g["links"]:
        assert link["kind"] in KINDS
        assert link["source"] in ids and link["target"] in ids
        assert link["s"] > 0
    assert {link["kind"] for link in g["links"]} & {"direct", "reverse"}
    linked = {link["source"] for link in g["links"]} | {link["target"] for link in g["links"]}
    assert all(n["id"] in linked for n in g["nodes"] if n["kind"] == "via"), "no via word without a link"


def test_the_via_words_are_capped(population):
    board = _board()
    _, g = _graph(population, _linked_clue(population, board), max_via=1)
    on_bomb_path = set((g["bomb_path"] or [])[1:-1])
    assert len({n["id"] for n in g["nodes"] if n["kind"] == "via"} - on_bomb_path) <= 1
    assert len(g["links"]) <= 160


def test_the_path_to_the_bomb_is_marked(population):
    board = _board()
    clue = _bomb_clue(population, board)
    if clue is None:
        pytest.skip("no clue in the synthetic graph reaches this board's bomb")
    _, g = _graph(population, clue)
    assert g["bomb_path"][0] == clue and g["bomb_path"][-1] == board.assassin
    assert any(link["kind"] == "bomb" for link in g["links"])


def test_an_unknown_clue_gives_the_board_and_no_links(population):
    board, g = _graph(population, "zzznotaword")
    assert len([n for n in g["nodes"] if n["kind"] == "board"]) == len(board.words)
    assert g["links"] == [] and g["bomb_path"] is None


def test_a_clue_on_the_board_is_refused(population):
    board = _board()
    with pytest.raises(ValueError):
        clue_graph(Memory(population), keys.POPULATION, board.words, board.roles, set(), board.words[0])


def test_board_graph_uses_the_memorys_top_clue(population, test_settings):
    g = LiveApp(test_settings).board_graph(GraphRequest(5000, "everyone", None))
    assert g["seed"] == 5000
    assert len([n for n in g["nodes"] if n["kind"] == "board"]) == 25
    assert g["clue"] not in _board().words and any(n["kind"] == "clue" for n in g["nodes"])


def test_board_graph_refuses_a_missing_memory(population, test_settings):
    with pytest.raises(ValueError, match="no memory"):
        LiveApp(test_settings).board_graph(GraphRequest(5000, "nobody-here", None))


def test_game_graph_uses_the_board_as_it_stood_and_joins_the_live_feed(population, test_settings):
    live = LiveApp(test_settings)
    words, key = board_for_seed(5000)
    board = BoardView.from_harness(words, key)
    clue = _linked_clue(population, board)
    game = LiveGame("live-test-1", "glove", "everyone", keys.POPULATION, 5000, "watch", False, "codebook", 0.0,
                    words, key)
    live.games[game.gid] = game
    game.add({"kind": "clue", "turn": 1, "clue": clue})
    game.add({"kind": "guess", "word": board.words[0], "role": board.roles[0]})
    game.add({"kind": "clue", "turn": 2, "clue": clue})

    def revealed(g: dict) -> set[str]:
        return {n["id"] for n in g["nodes"] if n.get("revealed")}

    first = live.game_graph(game.gid, 1)
    latest = live.game_graph(game.gid, None)
    assert first["turn"] == 1 and revealed(first) == set()
    assert latest["turn"] == 2 and revealed(latest) == {board.words[0]}
    assert any(e["kind"] == "query" and e["name"].startswith("graph_") for e in game.since(0))
    with pytest.raises(LookupError):
        live.game_graph(game.gid, 9)
    with pytest.raises(LookupError):
        live.game_graph("no-such-game", None)
