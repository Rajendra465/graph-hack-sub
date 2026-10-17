# Submission text (copy into the WeMakeDevs form)

**Project name:** Codebook

**Tagline (one line):** An AI teammate that learns how you think, remembers it next session, and can hand that
memory to another AI. One memory per partner, each its own graph in FalkorDB.

**Track:** 02 · Agent Memory and Coordination

**Links**
- Repository: [repo URL]
- Demo video (2:19, captioned): [video URL]
- Pitch deck: [deck link]

**Short description (≈60 words)**

AI teammates forget their partner every session. Codebook is a Codenames clue-giver that keeps one memory per
partner in FalkorDB: a GRAPH.COPY of everyone's word associations that learns from every graded guess, keeps a
diary, survives restarts, and is shared with other AIs through MCP tools, never database passwords. The
unmodified Codenames AI Competition engine keeps the score.

**Long description**

People who play word games together build a private shorthand; AI teammates start from zero every time.
Codebook gives an AI clue-giver two memories, both in FalkorDB: everyone's memory (half a million weighted word
links) and one memory per partner, a GRAPH.COPY of it that learns. Every turn, Cypher reads four kinds of link
between candidate clues and the cards (direct, backwards, two-step chains, shared associates); a small model of
this partner predicts their picks; code blocks any clue whose chain reaches the bomb; and every graded guess
reweights the partner's own graph. After each game the diary is consolidated into the partner's style, and
practice games deliberately probe how the partner thinks.

Evaluation was written down and committed before the first test, with a stop rule. On boards the partners never
saw, scored by the unmodified Codenames AI Competition engine, 3 of 4 promises were kept: a partner's own memory
beat everyone's memory and beat the wrong partner's memory for three of four partners (the word2vec bot's bomb hits
fell from 32% to 21%), and it improved steadily over 5, 10 and 20 practice games. GloVe gained nothing significant,
and the handover to another AI (Claude Sonnet) pointed the right way (bomb hits 40% to 22%) but was not significant
on 40 boards. Every game is in the repository.

What only FalkorDB made easy: each partner's memory is its own graph key (copied in 0.7 s, exported to an 11 MB
file and restored on another server), locked to one database user with an ACL selector, traversed in
milliseconds, and still there after a restart. Remove FalkorDB and nothing runs: there is no fallback store.

We also report five things we learned about FalkorDB 6.0.2 while building it (an index-first query pattern that
made our reads 12 to 150 times faster, an OPTIONAL MATCH pitfall, read-only ACL selectors, DUMP/RESTORE for
graphs, and keeping same-named graphs apart across Redis databases).

**How FalkorDB is used:** primary and only database. `codebook:population` (everyone's memory, read-only after
setup) and `codebook:partner:<id>` (one graph per partner: learned link weights, style, diary). Cypher for every
read and write; GRAPH.COPY for new partners and learning-curve snapshots; per-partner ACL users; DUMP/RESTORE
for export and import.

**Tech stack:** FalkorDB 6.0.2, Python 3.12, Starlette, MCP (Python SDK), Typer; the Codenames AI Competition
engine (MIT, vendored unmodified); GloVe and word2vec vectors for the competition's bot partners; Claude Code
headless (`claude -p`) and Codex CLI as AI partners and clue-givers.

**AI use (required disclosure):** Built with Claude Code (Claude Opus) as the coding assistant for research,
code, tests, documentation, the pitch deck and the demo recording script. A Codex CLI adapter is included as an
in-product partner and clue-giver; Codex did not write code for this project. Inside the product, Claude Haiku plays as a guesser and Claude Sonnet as a
clue-giver through their command-line tools; they never get database access.

**Data:** everyone's memory is built at setup from the Small World of Words data (SWOW-EN18, downloaded by each
user under CC BY-NC-ND 3.0) or ConceptNet 5.7 (CC BY-SA 4.0); the reported results used ConceptNet 5.7. No word
data is committed to the repository.

**Team:** [Team name]
