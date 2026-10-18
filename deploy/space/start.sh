#!/usr/bin/env bash
# Start FalkorDB inside the container (localhost only, a new random password each start, loaded from the
# snapshot, nothing written back), wait until the snapshot is loaded, then serve the live view on port 7860.
set -euo pipefail

data=/tmp/falkordb
mkdir -p "$data"
cp /home/user/falkordb/dump.rdb "$data/dump.rdb"
pass=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')

redis-server --bind 127.0.0.1 --port "$CODEBOOK_DB_PORT" --protected-mode yes --requirepass "$pass" \
  --dir "$data" --dbfilename dump.rdb --appendonly no --save "" \
  --loadmodule /var/lib/falkordb/bin/falkordb.so \
    MAX_QUEUED_QUERIES 1000 TIMEOUT_DEFAULT 30000 TIMEOUT_MAX 120000 RESULTSET_SIZE 1000000 &
db=$!

until [ "$(REDISCLI_AUTH="$pass" redis-cli -p "$CODEBOOK_DB_PORT" ping 2>/dev/null)" = "PONG" ]; do
  kill -0 "$db" 2>/dev/null || { echo "FalkorDB did not start" >&2; exit 1; }
  sleep 0.5
done

export CODEBOOK_DB_PASSWORD="$pass"
export CODEBOOK_PUBLIC_HOST="${SPACE_HOST:-$CODEBOOK_PUBLIC_HOST}"
exec /home/user/app/.venv/bin/codebook ui
