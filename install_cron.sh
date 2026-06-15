#!/bin/bash
# install_cron.sh - 在VPS上安装战报cron
# 在VPS上运行：cd /home/admin/okx_bot && bash install_cron.sh
CRON_LINE="10 0,16 * * * cd /home/admin/okx_bot && /usr/bin/python3 /home/admin/okx_bot/build_war_report.py >> logs/war_cron_\$(date +\\%Y\\%m\\%d).log 2>&1"
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
echo "CRON_INSTALLED"
crontab -l
