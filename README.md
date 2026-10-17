# Codebook

An AI clue-giver for Codenames that keeps a memory of each partner in FalkorDB:
it learns how you link words, remembers it next session, and can hand that memory to another AI.

Work in progress for Graph Hacks (Track 02, Agent Memory and Coordination). Full README coming.

```
docker compose up -d                 # FalkorDB 6.0.2 on 127.0.0.1:6390
uv sync --extra dev
uv run codebook setup --swow data/SWOW-EN18.zip --vectors
uv run codebook play --partner glove
```
