#!/bin/bash
# VPS safe cleanup — run ON server as admin. Never deletes live position/state/trades.
set -euo pipefail
DIR="${OKX_BOT_DIR:-/home/admin/okx_bot}"
DRY="${1:-}"
KEEP_BAK="${KEEP_BAK:-2}"

run() {
  if [ "$DRY" = "--dry-run" ]; then
    echo "[dry-run] $*"
  else
    echo "[run] $*"
    eval "$@"
  fi
}

prune_bak() {
  local pattern="$1"
  local keep="$2"
  local -a files
  mapfile -t files < <(ls -1t $pattern 2>/dev/null || true)
  local n=${#files[@]}
  if [ "$n" -le "$keep" ]; then
    return 0
  fi
  local i
  for ((i=keep; i<n; i++)); do
    run "rm -f '${files[$i]}'"
  done
}

echo "=== safe_cleanup_vps.sh $(date '+%F %T') dir=$DIR ==="

# Obvious junk
[ -f "$DIR/\$f" ] && run "rm -f '$DIR/\$f'"
run "find '$DIR/test_lab' -name '._*' -delete 2>/dev/null || true"

# Retired war report scripts (cron uses build + v3 only)
for f in generate_war_report.py generate_war_report_v2.py format_war_report.py fix_trades_csv.py patch_war_build.py hermes_latest_report.xlsx; do
  [ -f "$DIR/$f" ] && run "rm -f '$DIR/$f'"
done

# Duplicate one-shot / root copies (canonical under scripts/)
[ -f "$DIR/backfill_missing_legs.py" ] && [ -f "$DIR/scripts/backfill_missing_legs.py" ] && \
  run "rm -f '$DIR/backfill_missing_legs.py'"
[ -f "$DIR/deploy_war_fix_remote.py" ] && run "rm -f '$DIR/deploy_war_fix_remote.py'"

# Root stale log (systemd log is canonical)
[ -f "$DIR/bot.log" ] && run "rm -f '$DIR/bot.log'"

# Old bot_output_*.log (>7 days)
run "find '$DIR' -maxdepth 1 -name 'bot_output_*.log' -mtime +7 -delete 2>/dev/null || true"

# Prune backups — keep latest N per pattern
cd "$DIR"
prune_bak "position_*.json.bak_*" "$KEEP_BAK"
prune_bak "trades.csv.bak*" "$KEEP_BAK"
prune_bak "state.json.bak*" "$KEEP_BAK"
prune_bak "strategy_eq.json.bak*" "$KEEP_BAK"
prune_bak "main.py.bak*" 1
prune_bak "build_war_report.py.bak*" 1
prune_bak "generate_war_report_v3.py.bak*" 1

# Rotate large logs (existing cron helper)
[ -x "$DIR/scripts/rotate_bot_logs.sh" ] && run "bash '$DIR/scripts/rotate_bot_logs.sh'"

echo "=== done (VPS). Verify: systemctl is-active okx-bot; health_snapshot.py ==="
