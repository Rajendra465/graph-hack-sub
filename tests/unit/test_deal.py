"""Dealing a board for the live view must not disturb the engine's games, which deal from the global `random`."""

import random

from codebook.harness import board_for_seed


def test_dealing_a_board_leaves_the_global_random_state_alone():
    random.seed(12345)
    state = random.getstate()
    board_for_seed(6030)
    assert random.getstate() == state


def test_board_6030_is_still_the_benchmark_board():
    words, key = board_for_seed(6030)
    assert words[:5] == ["HOTEL", "DWARF", "ORANGE", "RACKET", "STAR"]
    assert key[:5] == ["Blue", "Blue", "Red", "Civilian", "Civilian"]
    assert key[words.index("GAME")] == "Assassin"
