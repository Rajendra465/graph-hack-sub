import numpy as np

from codebook.model import DEFAULT_STYLE, Choice, PartnerModel, Style, choices_from_turn, fit, log_likelihood


def _simulate(model: PartnerModel, n: int, seed: int = 0) -> list[Choice]:
    rng = np.random.default_rng(seed)
    words = tuple(f"w{i}" for i in range(12))
    out = []
    for _ in range(n):
        x = rng.choice([0.0, 0.0, 0.01, 0.05, 0.2], size=(12, 3))
        pull = model.pull(x, words)
        p = np.exp(pull - pull.max())
        p /= p.sum()
        out.append(Choice(words, x, int(rng.choice(12, p=p))))
    return out


def test_fit_moves_style_towards_a_planted_partner():
    planted = PartnerModel(Style(0.3, 2.2, 0.4))
    train = _simulate(planted, 400, seed=1)
    learned = fit(train, DEFAULT_STYLE, style_strength=0.5)
    assert learned.style.reverse > learned.style.direct
    test = _simulate(planted, 300, seed=2)
    ll_learned, _ = log_likelihood(learned, test)
    ll_default, _ = log_likelihood(PartnerModel(DEFAULT_STYLE), test)
    assert ll_learned > ll_default


def test_fit_learns_a_favourite_word():
    words = tuple(f"w{i}" for i in range(6))
    zeros = np.zeros((6, 3))
    choices = [Choice(words, zeros, 3) for _ in range(40)]
    model = fit(choices)
    assert max(model.bias, key=model.bias.get) == "w3"


def test_fit_without_data_returns_the_prior():
    assert fit([]).style == DEFAULT_STYLE


def test_choices_from_turn_shrinks_the_board_after_each_pick():
    board = ["a", "b", "c"]
    strengths = {"a": (0.1, 0.0, 0.0), "b": (0.0, 0.2, 0.0)}
    choices = choices_from_turn(board, strengths, ["b", "a"])
    assert [c.words for c in choices] == [("a", "b", "c"), ("a", "c")]
    assert [c.chosen for c in choices] == [1, 0]
    assert choices[0].strengths[1].tolist() == [0.0, 0.2, 0.0]
