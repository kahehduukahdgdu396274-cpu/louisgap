#!/bin/bash
# 安装每日凌晨 realized_legs 瘦身 cron（默认 04:20，保留 40 天）
set -euo pipefail
BOT_DIR="${OKX_BOT_DIR:-/home/admin/okx_bot}"
LINE='20 4 * * * cd /home/admin/okx_bot && /home/admin/okx_bot/venv/bin/python3 /home/admin/okx_bot/scripts/prune_old_realized_legs.py --refresh-war >> /home/admin/okx_bot/logs/prune_legs_cron.log 2>&1'
TMP=/tmp/crontab_prune_legs.tmp
crontab -l 2>/dev/null | grep -v 'prune_old_realized_legs.py' > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "✅ prune_legs cron installed (daily 04:20, keep 40d)"
crontab -l | grep prune_old || true
