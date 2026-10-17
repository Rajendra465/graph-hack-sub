# Demo video: shot list (3 minutes)

Everything on screen is live: the unmodified engine deals each board from its seed, and the right-hand
panel of the live view shows every Cypher statement as FalkorDB runs it. The boards below come from the final
run's game log (`results/runs/final-20261017-1941-v2/games.jsonl`), so each scene is a recorded result you can
replay.

Before recording: `docker compose up -d`, `uv run codebook status` (memories built), `uv run codebook ui`,
browser at http://127.0.0.1:7811.

A captioned version with no narration is recorded automatically:
`uv run --with playwright python scripts/record_demo.py --out demo` (writes `demo/codebook-demo.mp4`; every
caption that quotes a clue or a result reads it from the live view or the game log).

| Time | Scene | On screen | Say |
|---|---|---|---|
| 0:00-0:20 | Hook | A board; Codebook gives a clue; the partner guesses | "AI teammates forget you every session. People don't: they build a private shorthand. Codebook gives an AI clue-giver one memory per partner, in FalkorDB." |
| 0:20-0:45 | Same board, different partners | "Compare memories" tab on board 6042 with `everyone,w2v,persona-mirror`: SKY 2 vs MIDDLE 1 vs PLACE 3. Then "Partner memory": word2vec's bars (shared associates high, two-step chains low) | "Same board, different clue, because each partner's memory is its own graph. Codebook learned that the word2vec bot links words by shared associates, not the way people do." |
| 0:45-1:10 | Memory across sessions | Terminal: `bash scripts/persistence_check.sh glove 20`: 20 games, `docker compose restart`, a fresh process, the same 20 games, fingerprint `86311cdd8d209a53` both times. Then `codebook export glove` | "Restart the database and a fresh process plays the same games, fingerprint for fingerprint: the memory lives in FalkorDB, not in our process. And a memory is a file you can carry to another server." |
| 1:10-1:35 | The swap | Live view, board 6141, partner persona-mirror: its own memory wins in 4 turns; memory "persona-leaper's" walks into the bomb | "Same code, same board, wrong partner's memory: it misreads the partner. The memory is about this partner, not a better general model." |
| 1:35-1:55 | The block | Live view, board 6183, partner w2v, own memory: "Blocked GLOBE: globe → ROUND (the bomb)"; Live Cypher tab, the `path_to` query | "A tempting clue is refused before it is given: in this partner's memory, GLOBE leads straight to ROUND, the bomb. Code has the final say, and here is the exact query that found it." |
| 1:55-2:25 | Handover | Clue-giver "Claude Sonnet (+memory)", partner GloVe, board 6030. In the benchmark on this board, Sonnet alone hit the bomb; with GloVe's memory it won in 8 turns, every clue its own | "Another AI gives the clues now, choosing from this partner's memory through Codebook's tools. It never sees a database password, and the block still applies." |
| 2:25-3:00 | Your turn, then the score | Partner "you", learn on: three clues, click guesses; Partner memory tab updates. Last frame: the scorecard, 3 of 4 promises kept | "Play three rounds and your own memory appears. On boards it never saw, here is what partner memory changed, against promises we wrote down before testing, including the one we didn't keep." |

Recording notes: 1920x1080, browser zoom 110%, dark theme. Terminal font 18 pt.
