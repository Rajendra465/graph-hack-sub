# Submission form answers (WeMakeDevs · Graph Hacks)

The form's fields, in order. Copy each answer block as it is: the blocks are plain text, one paragraph per line,
because the form doesn't render Markdown. The team is set in the event panel, not in the form: **Rubixx**, one
member, Rajendra Sarpal (leader). The team can't be changed after you submit.

## Part 1 · Project details

**Project title** (required)

```text
Codebook: an AI teammate with one memory per partner
```

**Description** (required): What problem does your project solve, and who is it for?

```text
AI agents forget the people they work with. Every session starts from zero, everyone gets the same generic answers, and nothing one agent learns about you carries over to the next agent.

Codebook gives an agent a separate memory of each partner it works with. The memory persists, learns from every interaction and can be handed to another agent safely. Each partner's memory is its own graph in FalkorDB: it starts as a copy of everyone's memory (half a million word links) and learns that partner's habits.

To test whether that helps, we built a Codenames arena. An AI clue-giver must steer its partner to the right cards and away from the bomb, and the partner can be a bot, another AI or a person playing in the browser. On 200 boards it never saw, a partner's own memory beat everyone's memory for three of four partners; for the word2vec bot, bomb hits fell from 32% to 21%. We kept 3 of the 4 promises we wrote down before testing, and we report the one we missed.

It is for developers building agents that work with the same people again and again, such as coding assistants, support agents and tutors, who need per-user memory that persists, learns, stays isolated and moves between agents. Codebook ships as a Python package with a command line, six MCP tools and a live view that shows every Cypher query as it runs.

AI use: built with Claude Code as the coding assistant. The README's "AI use" section has the details.
```

**What track are you submitting for?** (required)

- Agent Memory and Coordination (Track 02).
- Optional second track: Agents That Act on Connected Data (Track 01). Each clue is a decision made by multi-hop
  Cypher over the graph, and a refusal shows the path to the bomb, so the claim is credible. Rule 5 allows
  entering several tracks.

**Repository** (required)

```text
https://github.com/Rajendra465/graph-hack-sub
```

**Demo video** (required): YouTube, public or unlisted

```text
https://youtu.be/eg9yptg7180
```

**Live demo or deployment** (optional): the live view on Google Cloud Run, with FalkorDB in the same container.

```text
https://codebook-755276882523.asia-south1.run.app
```

**How did you use FalkorDB in your project?** (required): Tell us what technical problems you solved using
FalkorDB.

```text
FalkorDB is Codebook's only database. With it stopped, all 13 commands and the MCP tools exit with an error; there is no fallback store.

The model: everyone's memory is one graph, codebook:population, with 39k (:Word) nodes and 497k weighted [:ASSOC] links. Every partner has their own graph key, codebook:partner:<id>, which holds learned link weights, a (:Partner) style node and a diary of (:Game)-[:HAS]->(:Turn)-[:GUESSED]->(:Word).

Problems we solved with it:
1. Separate memory per user: GRAPH.COPY gives a new partner a complete copy of everyone's memory in 0.7 s (497k links), so no query needs a tenant filter.
2. Isolation: each partner gets a Redis ACL user locked to its own key. GRAPH.RO_QUERY counts as read-write key access, so read-only access to everyone's memory uses a selector, (~codebook:population +graph.ro_query). A contract test confirms that a partner's user gets NOPERM on another partner's key and on writes to everyone's memory.
3. Deciding each clue: Cypher reads four kinds of link from each candidate clue to the board: direct, reverse, two-step chains and shared associates.
4. Traceable safety: a path query finds the strongest chain of at most two links from a clue to the bomb, and code blocks the clue and shows the path (for example "Blocked GLOBE: globe -> round reaches the bomb").
5. Learning: every graded guess MERGEs and re-weights links in that partner's graph (semantic memory). After each game the diary (episodic memory) is consolidated into the partner's style weights, which decide how clues are scored for that partner (procedural memory).
6. Persistence and handoffs: memory survives restarts (the same replay fingerprint before and after), another AI uses it through MCP tools without database credentials, and DUMP/RESTORE moves one memory to another server as an 11 MB file that restores in 0.4 s.
7. Learning curves: GRAPH.COPY snapshots after 5, 10 and 20 practice games.

Performance: binding the indexed word first under UNWIND took direct-link reads from 3.1 s to 13 ms and two-step chains from 17.6 s to 117 ms on the 497k-link graph, with identical rows.
```

**Blog link** (optional; the best blog post wins AirPods 5): post `BLOG.md` on dev.to or Hashnode first.

```text
[blog URL]
```

## Part 2 · Feedback

**What did you like about FalkorDB?** (required)

```text
Per-user memory became cheap. GRAPH.COPY cloned a 497k-link graph in 0.7 s, so every partner gets a full, independent graph key instead of a tenant ID in every query. One server holds all of them (15 graphs in our setup), and each can be locked to its own user with plain Redis ACLs.

Because FalkorDB speaks the Redis protocol, the standard redis client, AOF persistence, ACL users and DUMP/RESTORE all just worked, and the Docker image ran with one command. Reads were fast enough to run four kinds of Cypher traversal over the whole board on every turn, live, and GRAPH.EXPLAIN made the planner's choices easy to check.
```

**What improvements would you like to see in FalkorDB?** (required)

```text
1. Index use under UNWIND. "UNWIND $words AS w MATCH (c)-[r]->(:Word {text: w})" scans every edge for each row instead of using the Word.text index. Binding the node first ("MATCH (t:Word) WHERE t.text = w WITH t ...") took our reads from 3.1 s to 13 ms and from 17.6 s to 117 ms. The planner could do this rewrite itself.
2. OPTIONAL MATCH after an aggregating WITH silently returned no rows from the second OPTIONAL MATCH. We rewrote it as UNION ALL; a fix, or at least a warning, would help.
3. GRAPH.RO_QUERY is declared as read-write key access, so Redis's read-only key pattern (%R~) can't grant read-only graph access. Declaring it read-only would make per-tenant ACLs simple.
4. Moving a graph between servers: Redis COPY refuses graph keys, so we used DUMP/RESTORE. A documented, version-tolerant graph export and import would make that easier.
5. Re-creating a graph in one Redis database aborted a write to a same-named graph in another database ("graph was deleted or replaced"). Graphs in different databases should be fully independent.
```
