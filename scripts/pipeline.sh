#!/usr/bin/env bash
# Daily ANEEL solar pipeline: download -> filter -> SQLite -> stats -> (optional) upload.
#
# Configuration (environment variables):
#   STATE        Brazilian state code to keep (default: MG)
#   DATA_DIR     where raw/, filtered/, db and stats go (default: ./data)
#   RETAIN_DAYS  days of dated snapshots to keep locally (default: 7)
#   S3_TARGET    optional MinIO client target, e.g. "myminio/aneel-solar". Requires `mc`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${STATE:-MG}"
DATA_DIR="${DATA_DIR:-$ROOT/data}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"
S3_TARGET="${S3_TARGET:-}"
DATE="$(date +%F)"

RAW="$DATA_DIR/raw/$DATE"
OUT="$DATA_DIR/filtered/$DATE"
DB="$DATA_DIR/aneel-solar.db"
STATS="$DATA_DIR/stats/$DATE"
mkdir -p "$RAW" "$OUT" "$STATS" "$DATA_DIR/logs"
exec > >(tee -a "$DATA_DIR/logs/pipeline-$DATE.log") 2>&1
echo "[$(date '+%F %T')] === ANEEL solar pipeline ($STATE) — $DATE ==="

# ANEEL open data portal (https://dadosabertos.aneel.gov.br). Resource ids are stable.
URLS=(
  "https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2/resource/b1bd71e7-d0ad-4214-9053-cbd58e9564a7/download/empreendimento-geracao-distribuida.csv"
  "https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2/resource/49fa9ca0-f609-4ae3-a6f7-b97bd0945a3a/download/empreendimento-gd-informacoes-tecnicas-fotovoltaica.csv"
  "https://dadosabertos.aneel.gov.br/dataset/6d90b77c-c5f5-4d81-bdec-7bc619494bb9/resource/11ec447d-698d-4ab8-977f-b424d5deee6a/download/siga-empreendimentos-geracao.csv"
)

echo "[1/5] Downloading ${#URLS[@]} datasets in parallel..."
pids=()
for url in "${URLS[@]}"; do
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 -o "$RAW/$(basename "$url")" "$url" & pids+=($!)
done
# `wait` without arguments ignores failures; wait on each pid so a failed download stops the run.
for pid in "${pids[@]}"; do wait "$pid"; done
ls -lh "$RAW"

echo "[2/5] Filtering solar projects in $STATE..."
python3 "$ROOT/src/filter.py" "$RAW" "$OUT" --state "$STATE"

echo "[3/5] Building SQLite database..."
python3 "$ROOT/src/build_db.py" "$OUT" "$DB"

echo "[4/5] Computing market statistics..."
python3 "$ROOT/src/market_stats.py" "$DB" "$STATS"
rm -rf "$DATA_DIR/stats/latest" && cp -R "$STATS" "$DATA_DIR/stats/latest"

if [[ -n "$S3_TARGET" ]]; then
  echo "[5/5] Uploading to $S3_TARGET..."
  mc cp --recursive "$OUT/"   "$S3_TARGET/filtered/$DATE/"
  mc cp --recursive "$STATS/" "$S3_TARGET/stats/$DATE/"
  mc rm --recursive --force "$S3_TARGET/stats/latest/" >/dev/null 2>&1 || true
  mc cp --recursive "$STATS/" "$S3_TARGET/stats/latest/"
else
  echo "[5/5] S3_TARGET not set, skipping upload."
fi

echo "Removing local snapshots older than $RETAIN_DAYS days..."
for dir in raw filtered stats; do
  find "$DATA_DIR/$dir" -mindepth 1 -maxdepth 1 -type d -mtime +"$RETAIN_DAYS" ! -name latest -exec rm -rf {} +
done

echo "[$(date '+%F %T')] === Done ==="
