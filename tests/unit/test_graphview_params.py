"""Request parsing for the graph endpoints: bad input is refused before any query runs."""

import pytest

from codebook.graphview import GraphRequest, parse_graph_request, parse_turn, parse_word


def test_turn_is_optional_and_bounded():
    assert parse_turn(None) is None
    assert parse_turn("") is None
    assert parse_turn("3") == 3
    for bad in ("0", "-1", "101", "x", "1.5"):
        with pytest.raises(ValueError):
            parse_turn(bad)


def test_words_are_single_lowercase_words():
    assert parse_word(" Candy ") == "candy"
    for bad in ("", "a b", "../x", "x;y", "drop)", "w" * 40, "1abc"):
        with pytest.raises(ValueError):
            parse_word(bad)


def test_graph_request_defaults_to_board_6030_and_everyones_memory():
    assert parse_graph_request({}) == GraphRequest(6030, "everyone", None)
    assert parse_graph_request({"seed": "6001", "memory": "w2v", "clue": "Boat"}) == GraphRequest(6001, "w2v", "boat")


@pytest.mark.parametrize("params", [{"seed": "-1"}, {"seed": "abc"}, {"seed": str(10**9 + 1)}, {"memory": "../etc"},
                                    {"memory": "W2V!"}, {"clue": "two words"}])
def test_graph_request_refuses_bad_input(params):
    with pytest.raises(ValueError):
        parse_graph_request(params)
