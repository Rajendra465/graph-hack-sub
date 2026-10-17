"""Every Cypher statement Codebook runs, by name. The live view shows these texts verbatim.

Graph model (one graph per key):
  (:Word {text, cue, clue, pool, bias})
  (:Word)-[:ASSOC {p, n, pp, hits, misses, learned}]->(:Word)
  (:Partner {id, direct, reverse, chain, shared, games, turns, updated})  partner keys only
  (:Game {id, seed, condition, by, turns, won})-[:HAS]->(:Turn {n, clue, count, board, feats, by, ev})
  (:Turn)-[:INTENDED]->(:Word)   (:Turn)-[:GUESSED {order, outcome}]->(:Word)   (:Turn)-[:BY]->(:Agent {id})
  (:Source {dataset, version, sha256, loaded_at, words, links, min_count})

`p` is the share of people who gave the response (SWOW R123 strength), `n` the count.
`pp` is the partner's weight for a link: absent in everyone's memory, written by learning.
"""

from __future__ import annotations

SCHEMA = (
    "CREATE INDEX FOR (w:Word) ON (w.text)",
    "CREATE INDEX FOR (g:Game) ON (g.id)",
)

LOAD_WORDS = """
UNWIND $rows AS r
CREATE (:Word {text: r[0], cue: r[1], clue: r[2], pool: r[3]})
"""

LOAD_LINKS = """
UNWIND $rows AS r
MATCH (a:Word {text: r[0]}), (b:Word {text: r[1]})
CREATE (a)-[:ASSOC {p: r[2], n: r[3]}]->(b)
"""

SOURCE = """
CREATE (:Source {dataset: $dataset, version: $version, sha256: $sha256, loaded_at: $loaded_at,
                 words: $words, links: $links, min_count: $min_count})
"""

SOURCE_GET = """
MATCH (s:Source)
RETURN s.dataset AS dataset, s.version AS version, s.sha256 AS sha256, s.loaded_at AS loaded_at,
       s.words AS words, s.links AS links, s.min_count AS min_count
"""

COUNTS = """
MATCH (w:Word) WITH count(w) AS words
MATCH ()-[r:ASSOC]->()
RETURN words, count(r) AS links, sum(CASE WHEN r.pp IS NULL THEN 0 ELSE 1 END) AS reweighted
"""

# FalkorDB 6.0.2 plans `UNWIND .. MATCH (a)-[]->(:Word {text: x})` as a scan of every link
# per row. Binding the word first (MATCH .. WHERE .. WITH) gives a Node By Index Scan and a
# traversal from it: 12x faster for DIRECT and 46x for CHAIN, same rows.

# Score, step 1: every clue word with a link INTO a board word ("people shown CLUE say WORD").
DIRECT = """
UNWIND $board AS bw
MATCH (t:Word) WHERE t.text = bw
WITH t, bw
MATCH (c:Word)-[r:ASSOC]->(t)
WHERE c.clue AND coalesce(r.pp, r.p) > 0
RETURN c.text AS clue, bw AS word, coalesce(r.pp, r.p) AS s
"""

# Score, step 2: links the other way ("people shown WORD say CLUE").
REVERSE = """
UNWIND $board AS bw
MATCH (t:Word) WHERE t.text = bw
WITH t, bw
MATCH (t)-[r:ASSOC]->(c:Word)
WHERE c.clue AND coalesce(r.pp, r.p) > 0
RETURN c.text AS clue, bw AS word, coalesce(r.pp, r.p) AS s
"""

# Score, step 3: two-step chains from each shortlisted clue to every board word.
CHAIN = """
UNWIND $clues AS cw
MATCH (c:Word) WHERE c.text = cw
WITH c, cw
MATCH (c)-[r1:ASSOC]->(m:Word)-[r2:ASSOC]->(t:Word)
WHERE t.text IN $board AND m <> t AND t <> c
WITH cw, t.text AS word, max(coalesce(r1.pp, r1.p) * coalesce(r2.pp, r2.p)) AS s
WHERE s >= $floor
RETURN cw AS clue, word, s
"""

# Score, step 4: shared associates, clue -> m <- word ("both make people think of m").
# Similarity through shared associates predicts relatedness better than direct links
# (De Deyne et al.); it is how embedding-like partners see words.
SHARED = """
UNWIND $board AS bw
MATCH (t:Word) WHERE t.text = bw
WITH t, bw
MATCH (t)-[r2:ASSOC]->(m:Word)<-[r1:ASSOC]-(c:Word)
WHERE c.text IN $clues AND c <> t AND m <> c
WITH c.text AS clue, bw AS word, sum(coalesce(r1.pp, r1.p) * coalesce(r2.pp, r2.p)) AS s
WHERE s >= $floor
RETURN clue, word, s
"""

# One clue (any word) against the board: direct and reverse links in one round trip.
# (On 6.0.2, OPTIONAL MATCH -> WITH collect() -> a second OPTIONAL MATCH silently drops the second
# match's rows; UNION ALL of two plain patterns does not. tests/contract checks both readers agree.)
CLUE_LINKS = """
MATCH (c:Word {text: $clue})-[f:ASSOC]->(t:Word)
WHERE t.text IN $board
RETURN t.text AS word, coalesce(f.pp, f.p) AS s, 0 AS kind
UNION ALL
MATCH (c:Word {text: $clue})<-[b:ASSOC]-(t:Word)
WHERE t.text IN $board
RETURN t.text AS word, coalesce(b.pp, b.p) AS s, 1 AS kind
"""

# Block: the strongest chain of at most two links from the clue to the bomb, in this memory.
PATH_TO = """
MATCH p=(c:Word {text: $clue})-[:ASSOC*1..2]->(a:Word {text: $target})
RETURN [n IN nodes(p) | n.text] AS path,
       reduce(s = 1.0, r IN relationships(p) | s * coalesce(r.pp, r.p)) AS strength
ORDER BY strength DESC LIMIT 1
"""

# Learn, part 1: the partner picked WORD for CLUE, so this partner links them.
# Creates the link if everyone's memory does not have it.
LEARN_HITS = """
UNWIND $hits AS h
MATCH (c:Word {text: h[0]}), (g:Word {text: h[1]})
MERGE (c)-[r:ASSOC]->(g)
ON CREATE SET r.p = 0.0, r.n = 0, r.learned = true
SET r.hits = coalesce(r.hits, 0) + 1
SET r.pp = (r.p + $gain * r.hits) * pow($decay, coalesce(r.misses, 0))
"""

# Learn, part 2: we expected WORD for CLUE and the partner passed it over.
LEARN_MISSES = """
UNWIND $misses AS m
MATCH (c:Word {text: m[0]}), (w:Word {text: m[1]})
WITH c, w
MATCH (c)-[r:ASSOC]->(w)
SET r.misses = coalesce(r.misses, 0) + 1
SET r.pp = (r.p + $gain * coalesce(r.hits, 0)) * pow($decay, r.misses)
"""

PARTNER_SET = """
MERGE (p:Partner {id: $id})
SET p.direct = $direct, p.reverse = $reverse, p.chain = $chain, p.shared = $shared,
    p.games = $games, p.turns = $turns, p.updated = $updated
"""

PARTNER_GET = """
MATCH (p:Partner)
RETURN p.id AS id, p.direct AS direct, p.reverse AS reverse, p.chain AS chain, p.shared AS shared,
       p.games AS games, p.turns AS turns, p.updated AS updated
"""

BIAS_CLEAR = """
MATCH (w:Word) WHERE w.bias IS NOT NULL
SET w.bias = NULL
"""

BIAS_SET = """
UNWIND $rows AS r
MATCH (w:Word {text: r[0]})
SET w.bias = r[1]
"""

BIAS_GET = """
MATCH (w:Word) WHERE w.bias IS NOT NULL
RETURN w.text AS word, w.bias AS bias
"""

# Diary: one Game node per game, one Turn per clue, edges to the words involved.
DIARY_GAME = """
MERGE (g:Game {id: $game})
ON CREATE SET g.seed = $seed, g.condition = $condition, g.by = $by, g.started = $at
"""

DIARY_TURN = """
MATCH (g:Game {id: $game})
MERGE (a:Agent {id: $by})
CREATE (g)-[:HAS]->(t:Turn {n: $n, clue: $clue, count: $count, board: $board, feats: $feats, by: $by, ev: $ev})
CREATE (t)-[:BY]->(a)
WITH t
UNWIND $intended AS iw
MATCH (w:Word {text: iw})
CREATE (t)-[:INTENDED]->(w)
"""

DIARY_GUESSES = """
MATCH (:Game {id: $game})-[:HAS]->(t:Turn {n: $n})
UNWIND $guesses AS gs
MATCH (w:Word {text: gs[0]})
CREATE (t)-[:GUESSED {order: gs[1], outcome: gs[2]}]->(w)
"""

DIARY_END = """
MATCH (g:Game {id: $game})
SET g.turns = $turns, g.won = $won, g.ended = $at
"""

DIARY_TURNS = """
MATCH (g:Game)-[:HAS]->(t:Turn)
OPTIONAL MATCH (t)-[x:GUESSED]->(w:Word)
RETURN g.id AS game, g.seed AS seed, t.n AS n, t.clue AS clue, t.count AS count, t.board AS board,
       t.feats AS feats, t.by AS by, collect([x.order, w.text, x.outcome]) AS guesses
ORDER BY game, n
"""

DIARY_STATS = """
MATCH (g:Game)
OPTIONAL MATCH (g)-[:HAS]->(t:Turn)
RETURN count(DISTINCT g) AS games, count(t) AS turns,
       sum(CASE WHEN g.won THEN 1 ELSE 0 END) AS won_rows
"""

LEARNED_LINKS = """
MATCH (c:Word)-[r:ASSOC]->(w:Word)
WHERE r.hits > 0 OR r.misses > 0
RETURN c.text AS clue, w.text AS word, r.p AS p, r.pp AS pp,
       coalesce(r.hits, 0) AS hits, coalesce(r.misses, 0) AS misses, coalesce(r.learned, false) AS learned
ORDER BY hits + misses DESC, pp DESC LIMIT $limit
"""

WORD_LINKS = """
MATCH (c:Word {text: $word})-[r:ASSOC]->(w:Word)
RETURN w.text AS word, r.p AS p, coalesce(r.pp, r.p) AS w
ORDER BY w DESC LIMIT $limit
"""

ALL = {
    "load_words": LOAD_WORDS,
    "load_links": LOAD_LINKS,
    "source": SOURCE,
    "source_get": SOURCE_GET,
    "counts": COUNTS,
    "direct": DIRECT,
    "reverse": REVERSE,
    "chain": CHAIN,
    "shared": SHARED,
    "clue_links": CLUE_LINKS,
    "path_to": PATH_TO,
    "learn_hits": LEARN_HITS,
    "learn_misses": LEARN_MISSES,
    "partner_set": PARTNER_SET,
    "partner_get": PARTNER_GET,
    "bias_clear": BIAS_CLEAR,
    "bias_set": BIAS_SET,
    "bias_get": BIAS_GET,
    "diary_game": DIARY_GAME,
    "diary_turn": DIARY_TURN,
    "diary_guesses": DIARY_GUESSES,
    "diary_end": DIARY_END,
    "diary_turns": DIARY_TURNS,
    "diary_stats": DIARY_STATS,
    "learned_links": LEARNED_LINKS,
    "word_links": WORD_LINKS,
}
