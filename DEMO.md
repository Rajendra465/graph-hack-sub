# Demo video: shot list (3 minutes)

Everything on screen is live: the unmodified engine deals each board from its seed, and the right-hand
panel of the live view shows every Cypher statement as FalkorDB runs it. Seeds marked `[seed]` are
filled in from the final results (boards where the effect is visible, all reproducible).

Before recording: `docker compose up -d`, `uv run codebook status` (memories built), `uv run codebook ui`,
browser at http://127.0.0.1:7811, speed "slow".

| Time | Scene | On screen | Say |
|---|---|---|---|
| 0:00-0:20 | Hook | A board; Codebook gives a clue; the partner guesses | "AI teammates forget you every session. People don't: they build a private shorthand. Codebook gives an AI clue-giver one memory per partner, in FalkorDB." |
| 0:20-0:45 | Same board, different partners | "Compare memories" tab on `[seed]`: everyone's memory vs word2vec's vs the chain-thinker's top clues. Then "Partner memory": word2vec's bars (shared associates high, direct low) | "Same board, different clue, because each partner's memory is its own graph. Codebook learned that the word2vec bot links words by shared associates, not the way people do." |
| 0:45-1:10 | Memory across sessions | Terminal: `codebook status`; `codebook replay --partner w2v --games 5` (fingerprint); `docker compose restart`; new terminal, same command, same fingerprint. `codebook export w2v` | "Kill everything, restart the database: the same memory comes back and plays the same games, fingerprint for fingerprint. And a memory is a file you can carry to another server." |
| 1:10-1:35 | The swap | Live view, `[seed]`: partner word2vec with its own memory wins; same board with the chain-thinker's memory goes wrong | "Same code, same board, wrong partner's memory: it misreads the partner. The memory is about this partner, not a better general model." |
| 1:35-1:55 | The block | Live view, `[seed]`: "Blocked X: x → y → BOMB"; Live Cypher tab, the `path_to` query | "A tempting clue is refused before it is given: in this partner's memory a two-step chain reaches the bomb. Code has the final say, here is the exact query." |
| 1:55-2:25 | Handover | Clue-giver: Claude (+memory) or Codex (+memory), partner word2vec | "Another AI gives the clues now, choosing from Codebook's suggestions out of this partner's memory, through MCP tools. It never sees a database password, and the block still applies." |
| 2:25-3:00 | Your turn, then the score | Partner "you", learn on: three clues, click guesses; Partner memory tab updates. Last frame: the results scorecard and the promise count | "Play three rounds and your own memory appears. On boards it never saw, here is what partner memory changed, against promises we wrote down before testing." |

Recording notes: 1920x1080, browser zoom 110%, dark theme. Terminal font 18 pt.
