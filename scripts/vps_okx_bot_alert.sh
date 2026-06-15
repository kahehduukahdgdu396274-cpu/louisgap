#!/bin/bash
# VPS alert probe — append to logs/alerts.log (no secrets)
set -euo pipefail
DIR=/home/admin/okx_bot
ALERT_LOG="$DIR/logs/alerts.log"
DAY=$(date +%Y%m%d)
mkdir -p "$DIR/logs"

log_alert() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" >> "$ALERT_LOG"
}

# Pick latest bot log
LOG=""
for f in "$DIR/logs/bot_systemd.log" "$DIR/bot_output_${DAY}.log"; do
  [ -f "$f" ] && LOG=$f && break
done

if ! pgrep -f "venv/bin/python3 -u /home/admin/okx_bot/main.py" >/dev/null \
   && ! pgrep -f "venv/bin/python3 -u main.py" >/dev/null; then
  log_alert "CRITICAL | bot process down"
fi

if [ -n "$LOG" ]; then
  LAST_HB=$(grep -F "BTC $" "$LOG" 2>/dev/null | tail -1 || true)
  if [ -z "$LAST_HB" ]; then
    log_alert "CRITICAL | no heartbeat line in $LOG"
  else
    # Log line starts with HH:MM:SS |
    TS=$(echo "$LAST_HB" | sed -n 's/^\([0-9][0-9]:[0-9][0-9]:[0-9][0-9]\).*/\1/p')
    if [ -n "$TS" ]; then
      NOW=$(date +%H:%M:%S)
      # Simple: if no heartbeat in last 200 lines within ~5 min window, warn
      RECENT=$(tail -80 "$LOG" | grep -cF "BTC $" || true)
      if [ "${RECENT:-0}" -eq 0 ]; then
        log_alert "WARNING | no heartbeat in last 80 log lines ($LOG)"
      fi
    fi
  fi
  DEV=$(tail -30 "$LOG" | grep "偏差过大" | tail -1 || true)
  if [ -n "$DEV" ]; then
    DEDUP="$DIR/logs/.ws_rest_warn_last"
    DEV_KEY=$(echo "$DEV" | tr -d '\r' | tail -c 200)
    if [ -f "$DEDUP" ] && [ "$(cat "$DEDUP")" = "$DEV_KEY" ]; then
      : # same WS/REST event — skip repeat WARNING
    else
      printf '%s' "$DEV_KEY" > "$DEDUP"
      log_alert "WARNING | $DEV"
    fi
  fi
else
  log_alert "CRITICAL | bot log missing"
fi

# War cron: last WAR_DONE today
WAR_LOG="$DIR/logs/war_cron_${DAY}.log"
if [ -f "$WAR_LOG" ]; then
  if ! grep -q "WAR_DONE" "$WAR_LOG" 2>/dev/null; then
    log_alert "WARNING | no WAR_DONE in today's war cron log"
  fi
else
  log_alert "INFO | war cron log not yet created today"
fi

# Rotate alert log (keep last 500 lines)
if [ -f "$ALERT_LOG" ]; then
  L=$(wc -l < "$ALERT_LOG")
  if [ "$L" -gt 500 ]; then
    tail -500 "$ALERT_LOG" > "${ALERT_LOG}.tmp" && mv "${ALERT_LOG}.tmp" "$ALERT_LOG"
  fi
fi
