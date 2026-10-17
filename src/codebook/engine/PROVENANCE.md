# Vendored engine: Codenames AI Competition

Copied unmodified from https://github.com/CodenamesAICompetition/Game
at commit 1116940767d8e82c339067ef8f522e43e81fdcef (2020-05-29), MIT licence (see LICENSE).

Files: `game.py`, `game_wordpool.txt`, `players/__init__.py`, `players/codemaster.py`,
`players/guesser.py`, `players/guesser_glove.py`, `players/guesser_w2v.py`, `players/cm_wordlist.txt`.

Codebook never edits these files. It subclasses `Game` only to record each graded guess
(`_accept_guess` calls the original) and to capture the final turn count (`write_results`).
Boards come from `random.seed(seed)` exactly as in the competition, so any seed replays the same board.
`tests/unit/test_engine_unmodified.py` checks the SHA-256 of every vendored file.
