#!/bin/bash
# 安装/恢复 hourly reconcile（:25），含 govern + safe backfill
set -euo pipefail
BOT_DIR="${OKX_BOT_DIR:-/home/admin/okx_bot}"
LINE='25 * * * * cd /home/admin/okx_bot && /home/admin/okx_bot/venv/bin/python3 /home/admin/okx_bot/scripts/reconcile_all_from_okx.py >> /home/admin/okx_bot/logs/reconcile_cron.log 2>&1'
TMP=/tmp/crontab_okx_bot.tmp
crontab -l 2>/dev/null | grep -v 'reconcile_all_from_okx.py' > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "✅ reconcile cron installed (:25 hourly)"
crontab -l | grep reconcile || true
