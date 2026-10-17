"""The vendored Codenames AI Competition engine must stay byte-for-byte as published."""

import hashlib

import pytest

from codebook.harness import ENGINE_DIR, board_for_seed, engine

PUBLISHED = {
    "game.py": "f3d3c89206ce20abf29c293ce7da785acb0d81a4f0a6cdeeecc38bdd2cc9e0ce",
    "game_wordpool.txt": "f27f23b86c39a296a42e0fe827e7cb76e867c62fb20c81e891e7cec283e9d697",
    "players/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "players/codemaster.py": "091f6a9286b9157f5936f278ffa2a59264d6730caebbccb93171692317e61357",
    "players/guesser.py": "8d58ae9d776ea792eb8e5ba427145b4d1a95238f4e0a1a82ffae56d1ef01eca7",
    "players/guesser_glove.py": "600b4a4968bd181cefbb757f6dccd6346a04867f425f7a4fc0ae71b75dab87ba",
    "players/guesser_w2v.py": "f7217c98fe36b1b1e0eb13c772863cb24044a692b4eb6afab6f68894a82b52c3",
    "players/cm_wordlist.txt": "bbf72ecf7fa9913f8d575f73dc13753b9d846737c465eeecc8a1cc1517950324",
}


@pytest.mark.parametrize("name,digest", sorted(PUBLISHED.items()))
def test_vendored_file_is_unmodified(name, digest):
    assert hashlib.sha256((ENGINE_DIR / name).read_bytes()).hexdigest() == digest


def test_board_for_seed_matches_the_engine_deal():
    import os

    game_mod = engine()
    from players.codemaster import HumanCodemaster
    from players.guesser import HumanGuesser

    cwd = os.getcwd()
    os.chdir(ENGINE_DIR)
    try:
        g = game_mod.Game(HumanCodemaster, HumanGuesser, seed=5003, do_print=True, do_log=False)
    finally:
        os.chdir(cwd)
    assert board_for_seed(5003) == (g.words_on_board, g.key_grid)
