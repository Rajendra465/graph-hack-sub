"""A live game on a benchmark board replays the logged game: same set-up names, same AI clues."""

import json

import pytest

from codebook.evaluate import benchmark_game_id
from codebook.replay import benchmark_condition, live_condition, logged_chooser, logged_game, same_moves

ROW = {"partner": "glove", "condition": "handover", "clue_giver": "claude-sonnet", "seed": 6030, "clues": [
    {"n": 1, "clue": "space", "count": 2, "by": "claude-sonnet", "guesses": [["ship", "team"]]},
    {"n": 2, "clue": "candy", "count": 1, "by": "codebook", "guesses": [["chocolate", "team"]]},
    {"n": 3, "clue": "ocean", "count": 2, "by": "claude-sonnet", "guesses": [["wave", "assassin"]]},
]}
NO_ANSWER = ("", "no usable answer")


def write_log(results_dir, *rows_or_lines):
    run = results_dir / "runs" / "final-x"
    run.mkdir(parents=True)
    (results_dir / "LATEST_RUN").write_text("final-x\n", encoding="utf-8")
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows_or_lines]
    (run / "games.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_live_ai_game_never_claims_to_repeat_a_logged_one():
    assert live_condition("glove", "own", "claude-sonnet", learn=False, replay=False) is None
    assert live_condition("glove", "own", "claude-sonnet", learn=False, replay=True) == "handover"
    assert live_condition("glove", "own", "codebook", learn=False, replay=False) == "warm"


def test_a_learning_game_is_always_new():
    assert live_condition("glove", "own", "codebook", learn=True, replay=False) is None


def test_same_moves_compares_clues_counts_and_guesses():
    assert same_moves(ROW["clues"], json.loads(json.dumps(ROW["clues"])))
    changed = [dict(c) for c in ROW["clues"]]
    changed[2] = {**changed[2], "guesses": [["wave", "neutral"]]}
    assert not same_moves(ROW["clues"], changed)
    assert not same_moves(ROW["clues"], ROW["clues"][:2])


def test_live_set_ups_map_to_the_benchmark_conditions():
    assert benchmark_condition("w2v", "own", "codebook") == "warm"
    assert benchmark_condition("w2v", "everyone", "codebook") == "cold"
    assert benchmark_condition("w2v", "glove", "codebook") == "swap"
    assert benchmark_condition("persona-mirror", "persona-leaper", "codebook") == "swap"
    assert benchmark_condition("w2v", "w2v-at10", "codebook") == "warm@10"
    assert benchmark_condition("glove", "own", "claude-sonnet") == "handover"


def test_set_ups_the_benchmark_never_ran_have_no_condition():
    assert benchmark_condition("w2v", "persona-mirror", "codebook") is None
    assert benchmark_condition("w2v", "glove-at10", "codebook") is None
    assert benchmark_condition("glove", "everyone", "claude-sonnet") is None
    assert benchmark_condition("you", "own", "codebook") is None


def test_benchmark_game_ids_name_partner_condition_and_board():
    assert benchmark_game_id("w2v", "warm", 6183) == "w2v-warm-6183"


def test_logged_chooser_proposes_the_ai_clues_in_turn_order():
    choose = logged_chooser(ROW, "claude-sonnet")
    assert choose([], [], ()) == ("space", 2)
    # turn 2 was Codebook's suggestion in the benchmark: no AI answer on any attempt
    assert choose([], [], ()) is None
    assert choose([], [], (NO_ANSWER,)) is None
    assert choose([], [], (NO_ANSWER, NO_ANSWER)) is None
    assert choose([], [], ()) == ("ocean", 2)
    # past the end of the logged game: no answer, so Codebook's own suggestion is used
    assert choose([], [], ()) is None


def test_a_rejected_replayed_clue_is_not_proposed_again():
    choose = logged_chooser(ROW, "claude-sonnet")
    assert choose([], [], ()) == ("space", 2)
    assert choose([], [], (("space", "blocked: reaches the bomb"),)) is None
    assert choose([], [], ()) is None  # turn 2 is still Codebook's


def test_logged_game_reads_the_latest_run_and_keeps_the_last_row(tmp_path):
    rerun = {**ROW, "clues": ROW["clues"][:1]}
    write_log(tmp_path, ROW, rerun)
    assert logged_game(tmp_path, "glove", "handover", 6030, "claude-sonnet") == rerun
    assert logged_game(tmp_path, "glove", "handover", 6031, "claude-sonnet") is None


def test_logged_game_belongs_to_the_clue_giver_asked_for(tmp_path):
    write_log(tmp_path, ROW)
    assert logged_game(tmp_path, "glove", "handover", 6030, "codex") is None
    assert logged_game(tmp_path, "glove", "handover", 6030, "codebook") is None


def test_logged_game_skips_rows_that_are_not_games(tmp_path):
    write_log(tmp_path, "[1, 2]", "", ROW)
    assert logged_game(tmp_path, "glove", "handover", 6030, "claude-sonnet") == ROW


def test_an_unreadable_log_is_reported_without_its_path(tmp_path):
    write_log(tmp_path, "{not json")
    with pytest.raises(ValueError, match="unreadable") as err:
        logged_game(tmp_path, "glove", "handover", 6030, "claude-sonnet")
    assert str(tmp_path) not in str(err.value)
    (tmp_path / "runs" / "final-x" / "games.jsonl").unlink()
    with pytest.raises(ValueError, match="unreadable") as err:
        logged_game(tmp_path, "glove", "handover", 6030, "claude-sonnet")
    assert str(tmp_path) not in str(err.value)


@pytest.mark.parametrize("run_id", ["../../etc", "..", "a/b", ""])
def test_logged_game_refuses_a_run_id_that_is_not_a_plain_name(tmp_path, run_id):
    (tmp_path / "LATEST_RUN").write_text(run_id + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        logged_game(tmp_path, "glove", "handover", 6030, "claude-sonnet")


def test_logged_game_without_a_run_says_so(tmp_path):
    with pytest.raises(ValueError, match="LATEST_RUN"):
        logged_game(tmp_path, "glove", "handover", 6030, "claude-sonnet")
