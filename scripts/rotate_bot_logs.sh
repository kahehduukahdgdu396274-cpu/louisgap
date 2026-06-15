#!/bin/bash
# Rotate large bot logs without root — keep recent tail only.
set -euo pipefail
DIR=/home/admin/okx_bot
MAX_BOT_LINES=80000
MAX_PAPER_LINES=50000
MAX_PAPER_BYTES=300000

rotate_lines() {
  local file="$1"
  local keep="$2"
  [ -f "$file" ] || return 0
  local n
  n=$(wc -l < "$file" | tr -d ' ')
  if [ "$n" -gt "$keep" ]; then
    tail -n "$keep" "$file" > "${file}.rot"
    mv "${file}.rot" "$file"
    echo "$(date '+%Y-%m-%d %H:%M:%S') | rotated $file kept=$keep (was $n lines)"
  fi
}

rotate_bytes() {
  local file="$1"
  local maxb="$2"
  [ -f "$file" ] || return 0
  local sz
  sz=$(wc -c < "$file" | tr -d ' ')
  if [ "$sz" -gt "$maxb" ]; then
    tail -c "$maxb" "$file" > "${file}.rot"
    mv "${file}.rot" "$file"
    echo "$(date '+%Y-%m-%d %H:%M:%S') | rotated $file kept=${maxb}b (was ${sz}b)"
  fi
}

rotate_lines "$DIR/logs/bot_systemd.log" "$MAX_BOT_LINES"
rotate_lines "$DIR/test_lab/paper_cron.log" 20000
rotate_bytes "$DIR/test_lab/paper_signals.jsonl" "$MAX_PAPER_BYTES"
rotate_lines "$DIR/logs/alert_cron.log" 5000
rotate_lines "$DIR/logs/health_snapshot_cron.log" 5000

# Root bot_output_*.log (legacy nohup) — keep tail only
for f in "$DIR"/bot_output_*.log; do
  [ -f "$f" ] || continue
  rotate_lines "$f" 30000
done
