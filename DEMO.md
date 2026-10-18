# Demo videos

## The submitted video (2:44)

A narrated, captioned video made in Remotion. Its app screens are real captures of the redesigned live view, and
its results come from `results/runs/final-20261017-1941-v2/`. The narration is a synthetic voice (the open Kokoro
text-to-speech model).

| Time | Chapter |
|---|---|
| 0:00 | Same board, two memories: everyone's memory walks the bot into the bomb, its own memory wins |
| 0:11 | The problem: AI agents forget the people they work with |
| 0:24 | The game we built to test it: Codenames, with a bot, another AI or you as the partner |
| 0:42 | How the memory works: everyone's memory in FalkorDB, then a copy per partner that learns |
| 0:57 | Partner 1, a bot: every clue is a live Cypher query, the 3D memory graph, a blocked clue |
| 1:16 | Partners 2 and 3: another AI uses the memory through MCP tools; you play and get your own |
| 1:34 | Architecture: MCP server, command line and live view over one engine and one graph per partner |
| 1:47 | Why FalkorDB: a graph per partner, copied in under a second, locked to its owner, one file to move |
| 2:09 | Results: the word2vec bot's bomb hits fell from 32% to 21% on unseen boards; 3 of 4 promises kept |
| 2:21 | Why it matters: coding assistants, support agents and tutors that remember each person |
| 2:34 | Try it yourself: one command, four scenarios and a 60-second tour |

## The recorded walkthrough (2:19)

`demo/codebook-demo.mp4` is recorded from the live view by `scripts/record_demo.py`: real games on the
unmodified engine, captioned, no narration. Every game in it uses a board and a set-up from the final run, so
the live view repeats the logged game move for move and says so ("matches the benchmark log"); the handover
replays Claude Sonnet's logged clues, because a model never answers the same way twice. Every caption that quotes
a clue or a result reads it from the live view or from `results/runs/final-20261017-1941-v2/games.jsonl`.

To record it: `docker compose up -d`, `uv run codebook ui`, then
`uv run --with playwright python scripts/record_demo.py --out demo` (needs Google Chrome and ffmpeg; the first
run asks for `uv run --with playwright playwright install ffmpeg`).

| Time | Scene | On screen | Say (for a narrated version) |
|---|---|---|---|
| 0:00-0:22 | Same board, different partners | Title, then "Compare memories" on board 6042: everyone's memory says SKY 2, the word2vec bot's MIDDLE 1, the backwards thinker's PLACE 3 | "AI teammates forget you every session. Codebook gives an AI clue-giver one memory per partner, in FalkorDB. Same board, three memories, three different clues." |
| 0:22-0:33 | What the memory learned | "Partner memory": the word2vec bot links words mostly by shared associates (2.0), least by two-step chains (0.8) | "Nobody told it: after 20 practice games, the memory learned how this partner links words." |
| 0:33-0:45 | Memory across sessions | 20 GloVe games, `docker compose restart`, a fresh process, the same 20 games: fingerprint `86311cdd8d209a53` both times | "Restart the database and the same memory comes back: it lives in FalkorDB, not in our process." |
| 0:45-1:10 | The swap | Board 6141, a planted partner: its own memory wins in 4 turns; the wrong partner's memory hits the bomb on the first clue | "Same code, same board, the wrong partner's memory: it misreads the partner. The memory is about this partner." |
| 1:10-1:33 | The block | Board 6183, the word2vec bot's own memory: "Blocked GLOBE: globe → round reaches the bomb", every Cypher query on the right; won in 10 turns | "A tempting clue is refused before it is given. Code has the final say, and here is every query FalkorDB ran." |
| 1:33-1:57 | Handover | Board 6030, Claude Sonnet's logged clues with the GloVe bot's memory: won in 8 turns; Sonnet alone hit the bomb on this board; over 40 boards, bomb hits 40% alone and 22% with the memory | "Another AI gives the clues, choosing from this partner's memory through Codebook's tools, with no database password." |
| 1:57-2:19 | The score | The scorecard: 3 of 4 promises kept, then the closing card | "Promises written down before testing, scored by the unmodified engine on boards the partners never saw, including the one we didn't keep." |

For a narrated version you can add one more scene: partner "you", learn on, three clues, click your guesses, and
watch "Partner memory" grow. Recording notes: 1920x1080, browser zoom 110%, dark theme, terminal font 18 pt.
