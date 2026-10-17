#!/usr/bin/env bash
# A partner's memory survives a database restart: the same frozen-memory games give the same
# fingerprint before and after `docker compose restart`, played by a fresh process each time.
# Usage: scripts/persistence_check.sh [partner] [games]
set -euo pipefail
P="${1:-w2v}"
N="${2:-10}"
OUT="results/persistence-$P.txt"
mkdir -p results
{
  echo "== before restart ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
  uv run codebook replay --partner "$P" --games "$N"
  echo "== docker compose restart falkordb"
  docker compose restart falkordb >/dev/null
  until uv run codebook status >/dev/null 2>&1; do sleep 2; done
  echo "== after restart, new process ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
  uv run codebook replay --partner "$P" --games "$N"
} | tee "$OUT"
before=$(grep fingerprint "$OUT" | head -1 | awk '{print $2}')
after=$(grep fingerprint "$OUT" | tail -1 | awk '{print $2}')
if [ "$before" = "$after" ]; then
  echo "SAME MEMORY AFTER RESTART: fingerprint $before" | tee -a "$OUT"
else
  echo "DIFFERENT: $before vs $after" | tee -a "$OUT"
  exit 1
fi
