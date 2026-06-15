#!/bin/bash
# VPS alert probe — append to logs/alerts.log (no secrets)
set -euo pipefail
DIR=/home/admin/okx_bot
ALERT_LOG="$DIR/logs/alerts.log"
DAY=$(date +%Y%m%d)
umask 002
mkdir -p "$DIR/logs"
# 若历史文件被 root 创建导致不可写，回退到 admin 可写路径
if [ -f "$ALERT_LOG" ] && ! [ -w "$ALERT_LOG" ]; then
  ALERT_LOG="$DIR/logs/alerts_admin.log"
fi
touch "$ALERT_LOG" 2>/dev/null || ALERT_LOG="$DIR/logs/alerts_admin.log"
touch "$ALERT_LOG"

STALE_HEARTBEAT_SEC="${STALE_HEARTBEAT_SEC:-300}"
FROZEN_LOG_SEC="${FROZEN_LOG_SEC:-360}"
ALERT_DEDUP_SEC="${ALERT_DEDUP_SEC:-1800}"
# 冻结超过此秒数则自动重启 bot（兜底）
FROZEN_AUTO_RESTART_SEC="${FROZEN_AUTO_RESTART_SEC:-1800}"
RESTART_DEDUP_FILE="$DIR/logs/.alert_restarted"

log_alert() {
  local line
  line="$(date '+%Y-%m-%d %H:%M:%S') | $1"
  if ! echo "$line" >> "$ALERT_LOG" 2>/dev/null; then
    ALERT_LOG="$DIR/logs/alerts_admin.log"
    echo "$line" >> "$ALERT_LOG"
  fi
}

# 同类 CRITICAL 在 ALERT_DEDUP_SEC 内不重复刷屏；恢复后清除 dedup
should_alert() {
  local key="$1"
  local msg="$2"
  local dedup="$DIR/logs/.alert_${key}"
  local now last_ts last_msg
  now=$(date +%s)
  if [ -f "$dedup" ]; then
    read -r last_ts last_msg < "$dedup" || true
    if [ "${last_msg:-}" = "$msg" ] && [ $((now - ${last_ts:-0})) -lt "$ALERT_DEDUP_SEC" ]; then
      return 1
    fi
  fi
  printf '%s %s\n' "$now" "$msg" > "$dedup"
  return 0
}

clear_alert_dedup() {
  local key="$1"
  rm -f "$DIR/logs/.alert_${key}"
}

maybe_alert() {
  local key="$1"
  local level="$2"
  local msg="$3"
  if should_alert "$key" "$msg"; then
    log_alert "${level} | ${msg}"
  fi
}

proc_up() {
  pgrep -f "venv/bin/python3 -u /home/admin/okx_bot/main.py" >/dev/null \
    || pgrep -f "venv/bin/python3 -u main.py" >/dev/null
}

svc_active() {
  systemctl is-active okx-bot.service &>/dev/null \
    || systemctl is-active okx-bot &>/dev/null
}

# Pick latest bot log
LOG=""
for f in "$DIR/logs/bot_systemd.log" "$DIR/bot_output_${DAY}.log"; do
  [ -f "$f" ] && LOG=$f && break
done

if proc_up; then
  clear_alert_dedup "proc_down"
  clear_alert_dedup "svc_proc_mismatch"
else
  if svc_active; then
    maybe_alert "svc_proc_mismatch" "CRITICAL" "systemd active but main.py process missing (bot crashed?)"
  else
    maybe_alert "proc_down" "CRITICAL" "bot down (systemd inactive, no main.py process)"
  fi
fi

if [ -n "$LOG" ]; then
  LAST_HB=$(grep -F "BTC $" "$LOG" 2>/dev/null | tail -1 || true)
  if [ -z "$LAST_HB" ]; then
    maybe_alert "no_hb" "CRITICAL" "no heartbeat line in $LOG"
  else
    clear_alert_dedup "no_hb"
    HB_TIME=$(echo "$LAST_HB" | sed -n 's/^\([0-9][0-9]:[0-9][0-9]:[0-9][0-9]\).*/\1/p')
    if [ -n "$HB_TIME" ]; then
      NOW_EPOCH=$(date +%s)
      HB_EPOCH=$(date -d "$(date +%Y-%m-%d) ${HB_TIME}" +%s 2>/dev/null || echo 0)
      if [ "$HB_EPOCH" -gt 0 ]; then
        AGE=$((NOW_EPOCH - HB_EPOCH))
        # 跨午夜：心跳时间比当前时刻"晚很多"则视为昨天
        if [ "$AGE" -lt 0 ] || [ "$AGE" -gt 43200 ]; then
          HB_EPOCH=$((HB_EPOCH - 86400))
          AGE=$((NOW_EPOCH - HB_EPOCH))
        fi
        if [ "$AGE" -gt "$STALE_HEARTBEAT_SEC" ]; then
          maybe_alert "stale_hb" "CRITICAL" "bot heartbeat stale ${AGE}s (last ${HB_TIME}, threshold ${STALE_HEARTBEAT_SEC}s)"
        else
          clear_alert_dedup "stale_hb"
          clear_alert_dedup "frozen_log"
        fi
      fi
    fi
    RECENT=$(tail -80 "$LOG" | grep -cF "BTC $" || true)
    if [ "${RECENT:-0}" -eq 0 ]; then
      maybe_alert "recent_hb" "WARNING" "no heartbeat in last 80 log lines ($LOG)"
    else
      clear_alert_dedup "recent_hb"
    fi
  fi

  if proc_up || svc_active; then
    LOG_MTIME=$(stat -c %Y "$LOG" 2>/dev/null || stat -f %m "$LOG" 2>/dev/null || echo 0)
    NOW_EPOCH=$(date +%s)
    LOG_AGE=$((NOW_EPOCH - LOG_MTIME))
    if [ "$LOG_AGE" -gt "$FROZEN_LOG_SEC" ]; then
      maybe_alert "frozen_log" "CRITICAL" "bot log not updated for ${LOG_AGE}s ($LOG) — loop frozen?"
      # 兜底自动重启：冻结超过 FROZEN_AUTO_RESTART_SEC 秒且30分钟内未重启过
      if [ "$LOG_AGE" -gt "$FROZEN_AUTO_RESTART_SEC" ]; then
        if [ ! -f "$RESTART_DEDUP_FILE" ] || [ $((NOW_EPOCH - $(cat "$RESTART_DEDUP_FILE"))) -gt 1800 ]; then
          log_alert "ACTION | bot frozen ${LOG_AGE}s — triggering systemctl restart okx-bot"
          printf '%s' "$NOW_EPOCH" > "$RESTART_DEDUP_FILE"
          systemctl restart okx-bot 2>&1 || log_alert "ERROR | restart failed: $?"
        fi
      fi
    fi
  fi

  if tail -50 "$LOG" | grep -q Traceback; then
    maybe_alert "traceback" "WARNING" "Traceback in last 50 log lines — check bot_systemd.log"
  else
    clear_alert_dedup "traceback"
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
  maybe_alert "log_missing" "CRITICAL" "bot log missing"
fi

# OKX net vs state 张数对齐
if proc_up || svc_active; then
  ALIGN_OUT=$("$DIR/venv/bin/python3" "$DIR/scripts/okx_net_alignment.py" 2>/dev/null || true)
  if [ -n "$ALIGN_OUT" ]; then
    if echo "$ALIGN_OUT" | grep -q "'aligned': False"; then
      OKX_N=$(echo "$ALIGN_OUT" | sed -n "s/.*'okx_net': \([^,}]*\).*/\1/p")
      ST_N=$(echo "$ALIGN_OUT" | sed -n "s/.*'state_net': \([^,}]*\).*/\1/p")
      maybe_alert "okx_desync" "CRITICAL" "OKX net=${OKX_N} != state net=${ST_N} (对账未对齐)"
    else
      clear_alert_dedup "okx_desync"
    fi
  fi
fi

# War report: event-driven on close; alert if close logged but no refresh within 15m
WAR_TS_FILE="$DIR/logs/war_updated_at.txt"
WAR_ACC_LOG="$DIR/logs/war_accurate.log"
CLOSE_RECENT=0
if [ -f "$DIR/logs/bot_systemd.log" ]; then
  if tail -200 "$DIR/logs/bot_systemd.log" 2>/dev/null | grep -qE "执行平仓:|OKX校验写入"; then
    CLOSE_RECENT=1
  fi
fi
if [ "$CLOSE_RECENT" -eq 1 ]; then
  if [ -f "$WAR_ACC_LOG" ] && tail -30 "$WAR_ACC_LOG" 2>/dev/null | grep -q "WAR_ACC_DONE"; then
    clear_alert_dedup "war_stale"
  elif [ -f "$WAR_TS_FILE" ]; then
    WAR_AGE=$(( $(date +%s) - $(date -r "$WAR_TS_FILE" +%s 2>/dev/null || echo 0) ))
    if [ "$WAR_AGE" -gt 900 ]; then
      maybe_alert "war_stale" "WARNING" "recent close but war_updated_at stale ${WAR_AGE}s"
    fi
  else
    maybe_alert "war_stale" "WARNING" "recent close but war_updated_at.txt missing"
  fi
else
  clear_alert_dedup "war_stale"
fi

# Rotate alert log (keep last 500 lines; 避免 mv 竞态导致 Permission denied)
if [ -f "$ALERT_LOG" ] && [ -w "$ALERT_LOG" ]; then
  L=$(wc -l < "$ALERT_LOG" | tr -d ' ')
  if [ "${L:-0}" -gt 500 ]; then
    TMP="$(mktemp "${TMPDIR:-/tmp}/alerts.XXXXXX")"
    tail -500 "$ALERT_LOG" > "$TMP" && cat "$TMP" > "$ALERT_LOG" && rm -f "$TMP"
  fi
fi
