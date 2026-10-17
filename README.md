# Codebook

**An AI teammate that learns how you think, remembers it next time, and can pass that memory to another AI.**

People who play word games together build a private shorthand: after a few games you know your partner
will hear "ocean" and think *wave*, not *bank*. AI teammates forget all of that the moment a session ends.
Codebook is a Codenames clue-giver that keeps **one memory per partner in FalkorDB**. It learns from every
graded guess, keeps that memory across sessions and restarts, and hands it to any other AI (Claude, Codex,
anything that speaks MCP) through tools, never through database credentials.

Graph Hacks 2026, **Track 02: Agent Memory and Coordination**.

> Results: see [Results](#results). The evaluation was written down and committed before the first test
> run ([EVAL.md](EVAL.md)); every promise is reported, kept or not.

---

## Why a graph, and why FalkorDB

| What Codebook needs | How FalkorDB does it |
|---|---|
| Everyone's memory: ~12,000 cue words, hundreds of thousands of weighted human word links | one graph, `codebook:population` |
| Score a clue by every one- and two-step chain to each board word, many times per turn | Cypher traversals over the link graph (`DIRECT`, `REVERSE`, `CHAIN`, `PATH_TO`) |
| A separate, persistent memory per partner that starts as a copy of everyone's | each partner is its own graph key, made with `GRAPH.COPY` (~290 ms, ~18 MB at SWOW scale) |
| Partners must not read or write each other's memory | Redis ACL users with a selector per partner key |
| Survive restarts and hand a memory from one AI to another | it is a key on the server; any process that is allowed to open it gets the same memory |

Remove FalkorDB and nothing runs: there is no in-memory fallback. With the server stopped, every
command exits with an error that names FalkorDB.

## How it works

```
                 everyone's memory                      your memory (one per partner)
             codebook:population (read-only)   GRAPH.COPY   codebook:partner:<id>
   (:Word)-[:ASSOC {p}]->(:Word)  ───────────────────────►  same links + learned weights (pp, hits, misses)
                                                            + (:Partner {style}) + diary (:Game)-[:HAS]->(:Turn)
```

Every turn:

1. **Suggest**: Cypher finds every clue word linked to the unrevealed words (direct links, reverse links,
   and the strongest two-step chain) in the memory being used.
2. **Score**: a small partner model turns those links into a "pull" towards each board word
   (`style · log(1 + 100·strength) + bias[word]`). Codebook simulates the partner's picks and ranks clues by
   expected team words found minus the cost of hitting the bomb or the opponent.
3. **Block**: code has the final say. A clue is refused if, in this memory, a chain of at most two links
   reaches the bomb with strength ≥ 0.02, or the model gives the bomb ≥ 5%. This applies even when Claude or
   Codex proposes the clue.
4. **Learn** (partner memories only): every pick reweights the clue→word link in that partner's graph
   (creating it if everyone's memory lacks it); intended words the partner passed over are weakened. After each
   game the diary is consolidated into the partner's style (direct / reverse / chain weights) and favourite words.

## Data model

```cypher
(:Word {text, cue, clue, pool, bias})
(:Word)-[:ASSOC {p, n, pp, hits, misses, learned}]->(:Word)
(:Partner {id, direct, reverse, chain, games, turns, updated})          // partner keys only
(:Game {id, seed, condition, by, turns, won})-[:HAS]->(:Turn {n, clue, count, board, feats, by, ev})
(:Turn)-[:INTENDED]->(:Word)   (:Turn)-[:GUESSED {order, outcome}]->(:Word)   (:Turn)-[:BY]->(:Agent {id})
(:Source {dataset, version, sha256, loaded_at, words, links, min_count})
CREATE INDEX FOR (w:Word) ON (w.text)
```

- `p`: share of people who gave this response to the cue (SWOW R123 strength); `n`: how many.
- `pp`: this partner's weight for the link; absent in everyone's memory; written only by learning.
- Keys: `codebook:population` (never written after setup) and `codebook:partner:<id>` (the only keys written).

## The Cypher

Every statement lives in [`src/codebook/cypher.py`](src/codebook/cypher.py), and the live view shows each
one as it runs, with its key, row count and time. The core three:

```cypher
// Suggest/score, step 1: clue words with a link into each board word
UNWIND $board AS bw
MATCH (t:Word) WHERE t.text = bw
WITH t, bw
MATCH (c:Word)-[r:ASSOC]->(t)
WHERE c.clue AND coalesce(r.pp, r.p) > 0
RETURN c.text AS clue, bw AS word, coalesce(r.pp, r.p) AS s

// Score, step 3: strongest two-step chain from each shortlisted clue to every board word
UNWIND $clues AS cw
MATCH (c:Word) WHERE c.text = cw
WITH c, cw
MATCH (c)-[r1:ASSOC]->(m:Word)-[r2:ASSOC]->(t:Word)
WHERE t.text IN $board AND m <> t AND t <> c
WITH cw, t.text AS word, max(coalesce(r1.pp, r1.p) * coalesce(r2.pp, r2.p)) AS s
WHERE s >= $floor
RETURN cw AS clue, word, s

// Block: the strongest chain of at most two links from the clue to the bomb, in this memory
MATCH p=(c:Word {text: $clue})-[:ASSOC*1..2]->(a:Word {text: $target})
RETURN [n IN nodes(p) | n.text] AS path,
       reduce(s = 1.0, r IN relationships(p) | s * coalesce(r.pp, r.p)) AS strength
ORDER BY strength DESC LIMIT 1

// Learn: the partner picked WORD for CLUE
UNWIND $hits AS h
MATCH (c:Word {text: h[0]}), (g:Word {text: h[1]})
MERGE (c)-[r:ASSOC]->(g)
ON CREATE SET r.p = 0.0, r.n = 0, r.learned = true
SET r.hits = coalesce(r.hits, 0) + 1
SET r.pp = (r.p + $gain * r.hits) * pow($decay, coalesce(r.misses, 0))
```

**A FalkorDB 6.0.2 finding.** Written the obvious way (`UNWIND $board AS bw MATCH (c)-[r]->(:Word {text: bw})`),
the planner scans every link for each board word instead of using the `Word.text` index. Binding the indexed
node first and passing it through `WITH` gives a `Node By Index Scan` and a traversal from it: on a 497k-link
graph, direct links went from 3.1 s to 13 ms and two-step chains from 17.6 s to 117 ms, with identical rows
(checked by `GRAPH.EXPLAIN` and a row-by-row comparison).

## Locks: one database user per partner

```
ACL SETUSER cb-<partner> reset on ><password> resetkeys ~codebook:partner:<partner>
    +ping +select +graph.query +graph.ro_query (~codebook:population +graph.ro_query)
```

FalkorDB declares even `GRAPH.RO_QUERY` as read-write key access, so Redis's read-only pattern (`%R~`) can't
express "read-only on everyone's memory". A selector can. The contract test
[`tests/contract/test_acl.py`](tests/contract/test_acl.py) checks the result: a partner's user can read
everyone's memory and read and write its own key. It gets `NOPERM` writing everyone's memory, reading another
partner's key, or running `GRAPH.LIST`.

## Try it

Needs Docker, [uv](https://docs.astral.sh/uv/) and Python 3.11 or 3.12.

```bash
git clone [repo URL] && cd codebook
docker compose up -d                          # FalkorDB 6.0.2 on 127.0.0.1:6390, data in a volume
uv sync --extra dev
# Word data: download SWOW-EN18.zip from https://smallworldofwords.org/en/project/research
# (accept its CC BY-NC-ND licence) and save it as data/SWOW-EN18.zip. Setup checks its SHA-256.
uv run codebook setup --vectors               # build everyone's memory + the bot partners' vectors
uv run codebook play --partner glove          # watch one game in the terminal
uv run codebook ui                            # live view on http://127.0.0.1:7811
```

Other commands: `codebook train --partner glove --games 20`, `codebook status`, `codebook reset <partner>`,
`codebook acl <partner>`, `codebook eval`, `codebook mcp`.

**Use it from any agent (MCP).** `claude mcp add codebook -- uv --directory <repo> run codebook mcp`
gives an agent six tools: `list_partners`, `suggest_clues`, `check_clue`, `record_turn`, `end_game`,
`partner_memory`. The agent never sees a database address or password.

## Evaluation

Written before the first test: [EVAL.md](EVAL.md). The unmodified Codenames AI Competition engine (MIT)
deals every board from a seed and keeps the score; its files are checksummed in
[`tests/unit/test_engine_unmodified.py`](tests/unit/test_engine_unmodified.py). Partners learn on training
boards (seeds 1000-1019) and are tested on boards they never saw (6000-6199), with memories frozen.

## Results

_To be filled in from `results/` after the run._

## AI use

Built with Claude Code (Claude Opus) and Codex as coding assistants: research, code, tests and the pitch
deck. Claude Haiku and Codex also appear inside the product as partners and clue-givers, through their
command-line tools.

## Limits, stated plainly

- Word data: SWOW-EN18 is CC BY-NC-ND 3.0. It is downloaded by each user and never committed here. If it is
  unavailable, `codebook setup --source conceptnet` builds everyone's memory from ConceptNet 5.7 (CC BY-SA 4.0)
  instead, and results say which one they used.
- AI partners may think much like the average person, so most of the statistical power comes from the
  competition's own word-vector guessers and the planted test partners.
- The partner model is small (three style weights plus per-word favourites plus reweighted links). It learns
  what it can see in 20 games; it is not a theory of how people think.

## Credits

Codenames AI Competition engine (MIT). Small World of Words: De Deyne, Navarro, Perfors, Brysbaert & Storms
(2019), *Behavior Research Methods* 51, 987-1006. ConceptNet 5 (Speer, Chin & Havasi, 2017). GloVe
(Pennington, Socher & Manning, 2014). word2vec (Mikolov et al., 2013). Codenames is a game by Vlaada Chvátil
(Czech Games Edition); this project is not affiliated with it.

MIT licence for Codebook's own code.
