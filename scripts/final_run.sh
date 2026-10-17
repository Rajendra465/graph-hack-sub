#!/usr/bin/env bash
# The final benchmark, exactly as reported in results/. Needs FalkorDB up and `codebook setup` done.
# Usage: scripts/final_run.sh [run-id] [ai-clue-giver]     (ai: codex | claude-sonnet)
set -euo pipefail
RUN="${1:-final-$(date +%Y%m%d-%H%M)}"
AI="${2:-codex}"
cb() { uv run codebook "$@"; }

cb status
# 1. Bot and planted partners: 20 training games each (snapshots after 5 and 10), then everyone's,
#    own and wrong memory on the same 200 unseen boards (seeds 6000-6199).
cb eval --run "$RUN" --partners glove,w2v,persona-mirror,persona-leaper --conditions cold,warm,swap \
        --train 20 --test 200 --workers 10 --snapshots 5,10
# 2. Learning curve: the memory after 5 and 10 games, same boards.
cb eval --run "$RUN" --partners glove,w2v,persona-mirror,persona-leaper --conditions warm@5,warm@10 \
        --test 200 --workers 10 --skip-train
# 3. Claude as the partner: 20 training games, then the three set-ups on 40 boards (6000-6039).
cb train claude --games 20
cb eval --run "$RUN" --partners claude --conditions cold,warm,swap --test 40 --workers 8 --skip-train
# 4. An AI as clue-giver with the GloVe partner: alone (plain) and with GloVe's memory (handover).
cb eval --run "$RUN" --partners glove --conditions plain,handover --test 40 --workers 8 --skip-train --ai "$AI"
# 5. The scorecard and the four promises.
cb report "$RUN" --title "Codebook results ($RUN)"
