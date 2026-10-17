# One memory per partner: teaching an AI teammate how you think, with FalkorDB

*Graph Hacks 2026, Track 02 (Agent Memory and Coordination). Code: [repo URL]*

Play a word game with a friend for a few evenings and something quiet happens: you stop giving clues the
way "people" would and start giving them the way *your friend* would. You know they hear "ocean" and think
*wave*, never *bank*. Psychologists call these private conventions; couples and teams build them without
trying. AI teammates don't. Every session starts from zero.

We built **Codebook**, a Codenames clue-giver that keeps **one memory per partner** in FalkorDB, learns from
every graded guess, keeps that memory across sessions and restarts, and hands it to another AI. Codenames is
the test bed because it has something most "agent memory" demos lack: **a scorekeeper we don't control**. The
unmodified, MIT-licensed Codenames AI Competition engine deals each board from a seed and checks every guess
against the hidden key.

## The idea in one picture

```
everyone's memory (read-only)                 your memory (one graph per partner)
codebook:population   ── GRAPH.COPY ──►   codebook:partner:<id>
(:Word)-[:ASSOC {p}]->(:Word)                same links + learned weights + style + diary
```

Everyone's memory is a word-association graph: for each cue word, the share of people who answer each
response. A new partner gets a `GRAPH.COPY` of it (about 0.7 s and 44 MB at half a million links). From then
on, only that copy learns.

## Four kinds of link, read by Cypher

For a candidate clue and a board word, Codebook reads four strengths out of the partner's graph:

| link | pattern | example |
|---|---|---|
| direct | clue → word | ocean → wave |
| reverse | word → clue | wave → ocean |
| chain | clue → m → word | ocean → water → fish |
| shared associates | clue → m ← word | ocean, lake → water |

A small partner model turns them into a "pull" towards each word (`style · log(1 + 100·strength) + bias`) and
Codebook simulates the partner's picks to rank clues by expected words found, minus the cost of the bomb.
Then code has the final say: if a chain of at most two links reaches the bomb in *this partner's* memory, the
clue is refused, even when Claude or Codex proposed it.

## Learning a partner: reweight, consolidate, and probe

Every graded pick reweights the clue→word link in that partner's graph (creating it if everyone's memory
lacks it); passed-over targets are weakened. After each game, the diary (`(:Game)-[:HAS]->(:Turn)-[:GUESSED]->(:Word)`)
is consolidated into the partner's *style* (how much they rely on each kind of link) and favourite words.

The surprise came from a planted test partner that thinks backwards (it picks the word that makes *it* think
of the clue). After 20 practice games, the learned memory said it was a direct thinker. The bug wasn't in the
learner: a careful clue-giver only gives clues where people's direct links are strong, and in exactly those
situations a backwards thinker and a direct thinker pick the same word. The diary never contained the
evidence. So practice games now **probe**: they favour clues on which one-habit hypotheses (only direct, only
reverse, only chains, only shared) predict different picks. With probing, the backwards thinker's learned
reverse weight rose to 4.0 (default 1.5).

What the memories learned:

| partner | direct | reverse | chain | shared |
|---|---|---|---|---|
| everyone's (default) | 3.0 | 1.5 | 1.5 | 1.5 |
| GloVe bot (competition) | 0.74 | 0.94 | 1.53 | **2.19** |
| word2vec bot (competition) | 0.83 | 0.96 | 0.90 | **1.95** |
| planted backwards thinker | 2.57 | **4.03** | 1.42 | 1.44 |
| planted two-step jumper | 3.15 | 1.70 | **2.81** | **2.85** |

The embedding bots lean on shared associates, which is how word vectors work: two words are close if they
appear in the same contexts. Nobody told Codebook that.

## Results

_Being filled in from the re-run (`final-20261017-1941-v2`). A code review of our own harness found two bugs
in the first run (a hidden forfeit rule, and AI set-ups that could borrow Codebook's clue), so the whole
pre-registered benchmark runs again; both are written up in [EVAL.md](EVAL.md)._

## Five things we learned about FalkorDB 6.0.2

1. **Bind the indexed node before you traverse.** `UNWIND $board AS bw MATCH (c)-[r]->(:Word {text: bw})` scans
   every link per row; `MATCH (t:Word) WHERE t.text = bw WITH t, bw MATCH (c)-[r]->(t)` uses the index. On 497k
   links: 3.1 s → 13 ms (direct), 17.6 s → 117 ms (two-step chains), same rows.
2. **Watch `OPTIONAL MATCH` after an aggregating `WITH`.** One reader of ours silently lost the second match's
   rows; `UNION ALL` of two plain patterns fixed it, and a contract test pins it.
3. **Read-only ACLs need a selector.** `GRAPH.RO_QUERY` is declared as read-write key access, so `%R~` doesn't
   work; `(~codebook:population +graph.ro_query)` does. One user per partner, locked to its own key.
4. **Graphs travel with `DUMP`/`RESTORE`.** Redis `COPY` refuses module keys, but an 11 MB dump of a
   half-million-link graph restores with its indexes. That's `codebook export` / `codebook import`.
5. **Keep same-named graphs apart across Redis databases.** Re-creating a graph in one database aborted a write
   on a same-named graph in another. Tests now run under their own key prefix.

## Why FalkorDB

Each partner's memory is its own graph, and FalkorDB treats a graph like a file: copy it in under a second,
lock it to one user, carry it to another server, and traverse it in milliseconds. Remove FalkorDB and nothing
runs; there is no fallback store, by design.

*Built with Claude Code as the coding assistant; Claude Haiku and Sonnet also appear inside the
product as partners and clue-givers.*
