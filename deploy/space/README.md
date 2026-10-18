---
title: Codebook
emoji: 🧠
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: An AI teammate with one FalkorDB memory per partner
---

# Codebook · live demo

Codebook is a Codenames clue-giver that keeps one memory per partner, each its own graph in FalkorDB. This Space
runs its live view: watch a game, see every Cypher query FalkorDB runs, turn a partner's memory in 3D, or play as
the guesser yourself.

Graph Hacks 2026 (WeMakeDevs × FalkorDB), Track 02: Agent Memory and Coordination. Team Rubixx.
Code, setup and results: [repo URL]

## How this demo runs

- FalkorDB 6.0.2 runs inside this container, reachable only from inside it, with a password made at startup. It
  loads a snapshot of the memories behind the published results.
- Only the "you" memory learns here, and everyone who plays as the guesser on this demo shares it. The benchmark
  memories stay as they were logged, so every replay still matches its log. A restart resets everything to the
  snapshot.
- There are no AI keys here. The "another AI takes over" scenario replays Claude Sonnet's logged clues; live AI
  partners need a local install (see the repository).

## Data and licences

Everyone's memory is built from ConceptNet 5.7 (CC BY-SA 4.0), so the graph snapshot in this Space is shared under
CC BY-SA 4.0. The bots' word vectors are subsets of GloVe (Wikipedia + Gigaword, PDDL 1.0) and of the word2vec
Google News vectors. The Codenames AI Competition engine is MIT, and so is Codebook's own code.
