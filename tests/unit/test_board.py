from codebook.board import ASSASSIN, NEUTRAL, OPPONENT, TEAM, BoardView, is_legal_clue


def test_from_harness_skips_revealed_words_and_maps_colours():
    words = ["OCEAN", "*Red*", "BANK", "PIANO", "MOON"]
    key = ["Red", "Red", "Assassin", "Blue", "Civilian"]
    board = BoardView.from_harness(words, key, original=["OCEAN", "WAVE", "BANK", "PIANO", "MOON"])
    assert board.words == ("ocean", "bank", "piano", "moon")
    assert board.roles == (TEAM, ASSASSIN, OPPONENT, NEUTRAL)
    assert board.assassin == "bank"
    assert board.team == ("ocean",)
    assert "wave" in board.all_words


def test_clue_rules_reject_board_words_substrings_and_shared_stems():
    printed = ["fire", "dancing", "pie"]
    assert not is_legal_clue("fire", printed)
    assert not is_legal_clue("fireman", printed)       # contains a board word
    assert not is_legal_clue("dance", printed)         # same stem as "dancing"
    assert not is_legal_clue("Ocean", printed)         # not lowercase letters only
    assert not is_legal_clue("ice cream", printed)
    assert is_legal_clue("ocean", printed)
