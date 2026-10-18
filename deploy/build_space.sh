#!/usr/bin/env bash
# Assemble the Hugging Face Space in deploy/out/space: the Dockerfile, start script and Space card, the repo at
# HEAD, the bots' word vectors, and a snapshot of the memory graphs in database 0, without "you" so that visitors
# start with a fresh memory of their own. Needs the local FalkorDB from compose.yml and `codebook setup --vectors`.
set -euo pipefail
cd "$(dirname "$0")/.."

out=deploy/out/space
rm -rf "$out"
mkdir -p "$out/app/data/vectors" "$out/falkordb"
cp deploy/space/Dockerfile deploy/space/start.sh deploy/space/README.md "$out/"
sed -i 's/\r$//' "$out/start.sh"  # a Windows checkout may add CRs, and bash in the container would choke
# `gcloud run deploy --source` skips whatever .gitignore lists, and app/.gitignore lists data/: upload it all.
echo "# Upload everything: the image needs app/data and app/results, which app/.gitignore lists." > "$out/.gcloudignore"
git archive HEAD | tar -x -C "$out/app"
cp data/vectors/glove.npz data/vectors/w2v.npz "$out/app/data/vectors/"

# Copy each graph into a throwaway FalkorDB of the same version, save it, and keep the file.
db=codebook-falkordb-1
snap=codebook-snapshot
docker rm -f "$snap" >/dev/null 2>&1 || true
docker run -d --name "$snap" --network codebook_default falkordb/falkordb:6.0.2 >/dev/null
until [ "$(docker exec "$snap" redis-cli ping 2>/dev/null)" = "PONG" ]; do sleep 0.5; done
graphs=$(docker exec "$db" redis-cli -n 0 GRAPH.LIST | tr -d '\r' | grep -vx 'codebook:partner:you')
# shellcheck disable=SC2086 # one argument per graph key
docker exec "$db" redis-cli -n 0 MIGRATE "$snap" 6379 "" 0 120000 COPY KEYS $graphs
docker exec "$snap" redis-cli SAVE >/dev/null
MSYS_NO_PATHCONV=1 docker cp "$snap:/var/lib/falkordb/data/dump.rdb" "$out/falkordb/dump.rdb"
docker rm -f "$snap" >/dev/null
echo "Space assembled in $out ($(du -sh "$out" | cut -f1)), graphs: $(echo $graphs | wc -w)"
