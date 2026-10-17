#!/usr/bin/env bash
# Removal control from EVAL.md: with FalkorDB stopped, every command must exit with an error that names
# FalkorDB, and nothing may fall back to another store. Writes results/removal-check.txt, then starts
# FalkorDB again. Every command checks the database before doing anything, so none of them can write.
set -u
cd "$(dirname "$0")/.."
out=results/removal-check.txt
port=${CODEBOOK_DB_PORT:-6390}

docker compose stop falkordb >/dev/null 2>&1
if uv run --quiet python -c "import socket; socket.create_connection(('127.0.0.1', $port), 2)" 2>/dev/null; then
  echo "FalkorDB still answers on port $port; not running the check" >&2
  exit 1
fi

pass=0
total=0
check() {
  local label=$1 msg code line verdict
  shift
  total=$((total + 1))
  msg=$(timeout 120 "$@" 2>&1 < /dev/null)
  code=$?
  line=$(printf '%s\n' "$msg" | grep -i -m1 "falkordb" | cut -c1-110)
  if [ "$code" -ne 0 ] && [ -n "$line" ]; then pass=$((pass + 1)); verdict=ok; else verdict=FAIL; fi
  printf '%-4s exit %-3s %s\n      %s\n' "$verdict" "$code" "$label" "${line:-<no message naming FalkorDB>}"
}

mcp_call=$'from codebook.mcp_server import list_partners\ntry:\n    list_partners()\nexcept RuntimeError as exc:\n    raise SystemExit(f"error: {exc}")'

{
  echo "== FalkorDB stopped ($(date -u +%Y-%m-%dT%H:%M:%SZ)): every command must fail and name FalkorDB"
  check "codebook setup --source conceptnet" uv run --quiet codebook setup --source conceptnet
  check "codebook status" uv run --quiet codebook status
  check "codebook play --partner glove" uv run --quiet codebook play --partner glove
  check "codebook train removal-test --games 1" uv run --quiet codebook train removal-test --games 1
  check "codebook replay --partner glove --games 1" uv run --quiet codebook replay --partner glove --games 1
  check "codebook eval --partners glove --train 1 --test 1" uv run --quiet codebook eval --partners glove --train 1 --test 1
  check "codebook report <latest run>" uv run --quiet codebook report "$(cat results/LATEST_RUN)"
  check "codebook export glove" uv run --quiet codebook export glove --out removal-test.codebook
  check "codebook import removal-test.codebook" uv run --quiet codebook import removal-test.codebook --as removal-test
  check "codebook acl removal-test" uv run --quiet codebook acl removal-test
  check "codebook reset removal-test" uv run --quiet codebook reset removal-test
  check "codebook ui" uv run --quiet codebook ui --port 7898
  check "MCP tool list_partners" uv run --quiet python -c "$mcp_call"
  echo "$pass / $total commands failed loudly and named FalkorDB; nothing fell back"
} | tee "$out"

docker compose start falkordb >/dev/null 2>&1
for _ in $(seq 60); do
  uv run --quiet codebook status >/dev/null 2>&1 && { echo "FalkorDB is back"; exit 0; }
  sleep 2
done
echo "FalkorDB did not come back within 2 minutes: docker compose logs falkordb" >&2
exit 1
