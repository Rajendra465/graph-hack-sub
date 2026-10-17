"""Contract tests against a live FalkorDB 6.0.2 (database index 15, synthetic data)."""

from __future__ import annotations

import pytest

from codebook import cypher as C
from codebook import keys
from codebook.board import BoardView
from codebook.db import Db
from codebook.harness import board_for_seed, play
from codebook.memory import Memory, ReadOnlyKey, TurnRecord
from codebook.partners import make_partner
from codebook.session import Session

pytestmark = pytest.mark.contract


def _turn() -> TurnRecord:
    return TurnRecord(1, "zzclue", 1, ("wave",), ("wave",), {}, (("wave", "team"),), "codebook")


def test_everyones_memory_refuses_writes(population):
    with pytest.raises(ReadOnlyKey):
        Memory(population).learn(keys.POPULATION, _turn())


def test_partner_memory_is_a_copy_that_learns_alone(population):
    memory = Memory(population)
    key = memory.reset_partner("alice")
    clue, word = population.ro_query(keys.POPULATION, "MATCH (c:Word)-[r:ASSOC]->(w:Word) WHERE c.clue AND w.pool "
                                     "RETURN c.text, w.text LIMIT 1").rows[0]
    turn = TurnRecord(1, clue, 1, (word,), (word,), {}, ((word, "team"),), "codebook")
    assert memory.learn(key, turn) == (1, 0)
    q = "MATCH (:Word {text: $c})-[r:ASSOC]->(:Word {text: $w}) RETURN r.pp, r.hits"
    assert population.ro_query(key, q, {"c": clue, "w": word}).rows[0][1] == 1
    assert population.ro_query(keys.POPULATION, q, {"c": clue, "w": word}).rows[0] == (None, None)


def test_learning_a_new_link_creates_it_only_in_the_partner_memory(population):
    memory = Memory(population)
    key = memory.reset_partner("bob")
    words = [r[0] for r in population.ro_query(keys.POPULATION, "MATCH (w:Word) WHERE w.pool RETURN w.text LIMIT 2").rows]
    a, b = words
    turn = TurnRecord(1, a, 1, (b,), (b,), {}, ((b, "neutral"),), "codebook")
    memory.learn(key, turn)
    q = "MATCH (:Word {text: $a})-[r:ASSOC]->(:Word {text: $b}) RETURN r.learned"
    assert population.ro_query(key, q, {"a": a, "b": b}).rows == ((True,),)
    assert population.ro_query(keys.POPULATION, q, {"a": a, "b": b}).rows == ()


def test_features_cover_team_words(population):
    memory = Memory(population)
    words, key = board_for_seed(5000)
    board = BoardView.from_harness(words, key)
    table = memory.features(keys.POPULATION, board, memory.model(keys.POPULATION))
    assert table.rows
    assert any(set(links) & set(board.team) for links in table.rows.values())


def test_training_game_writes_a_diary_and_a_refit_that_a_new_connection_reads(population, test_settings):
    memory = Memory(population)
    spec = make_partner("persona-mirror", settings=test_settings, memory=memory)
    key = memory.reset_partner("persona-mirror")
    model = memory.model(key)
    result, session = play(lambda ev: Session(memory, key, model, "t-1000", 1000, "train", ev, write_key=key,
                                              learn=True), spec.guesser_class, 1000, "t-1000")
    assert 1 <= result.turns <= 25
    stats = population.ro_query(key, C.DIARY_STATS).records()[0]
    assert stats["games"] == 1 and stats["turns"] == len(result.clues)
    fresh = Memory(Db(test_settings))
    assert fresh.model(key).style == session.model.style
    assert fresh.info("persona-mirror").games == 1


def test_same_seed_and_memory_replay_the_same_game(population, test_settings):
    memory = Memory(population)
    spec = make_partner("persona-leaper", settings=test_settings, memory=memory)
    model = memory.model(keys.POPULATION)
    runs = []
    for _ in range(2):
        result, _ = play(lambda ev: Session(memory, keys.POPULATION, model, "r-5001", 5001, "cold", ev),
                         spec.guesser_class, 5001, "r-5001")
        runs.append([(c.clue, c.count, c.guesses) for c in result.clues] + [result.turns])
    assert runs[0] == runs[1]
