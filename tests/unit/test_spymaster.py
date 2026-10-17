from codebook.board import BoardView
from codebook.model import PartnerModel
from codebook.spymaster import plan

WORDS = ["WAVE", "TIDE", "SALT", "PIANO", "MOON", "BANK", "CAR", "LION"]
KEY = ["Red", "Red", "Red", "Blue", "Civilian", "Assassin", "Civilian", "Blue"]


def board() -> BoardView:
    return BoardView.from_harness(WORDS, KEY)


def test_plan_prefers_the_clue_that_reaches_several_team_words():
    table = {
        "ocean": {"wave": (0.3, 0.1, 0.0), "tide": (0.25, 0.1, 0.0), "salt": (0.2, 0.0, 0.0)},
        "music": {"piano": (0.4, 0.2, 0.0), "wave": (0.01, 0.0, 0.0)},
    }
    best = plan(board(), table, PartnerModel(), seed=1)[0]
    assert best.clue == "ocean"
    assert best.count >= 2
    assert set(best.targets) <= {"wave", "tide", "salt"}


def test_plan_values_a_bomb_link_below_a_safe_clue():
    table = {
        "river": {"wave": (0.3, 0.0, 0.0), "tide": (0.2, 0.0, 0.0), "bank": (0.45, 0.2, 0.0)},
        "sea": {"wave": (0.25, 0.0, 0.0), "tide": (0.2, 0.0, 0.0)},
    }
    ranked = plan(board(), table, PartnerModel(), seed=1)
    assert ranked[0].clue == "sea"
    river = next(o for o in ranked if o.clue == "river")
    assert river.p_assassin > ranked[0].p_assassin


def test_plan_skips_illegal_clues():
    table = {"waves": {"wave": (0.5, 0.0, 0.0)}, "sea": {"wave": (0.2, 0.0, 0.0)}}
    assert [o.clue for o in plan(board(), table, PartnerModel(), seed=1)] == ["sea"]
