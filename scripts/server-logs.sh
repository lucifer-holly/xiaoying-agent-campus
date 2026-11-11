#!/usr/bin/env bash
# 查看线上日志（本机执行）：scripts/server-logs.sh [app|caddy] [行数]
set -euo pipefail
HOST="${XIAOYING_HOST:-aliyun}"
UNIT="${1:-app}"; N="${2:-80}"
case "$UNIT" in
  app)   ssh "$HOST" "journalctl -u xiaoying-agent -n $N --no-pager" ;;
  caddy) ssh "$HOST" "journalctl -u caddy -n $N --no-pager" ;;
  *)     echo "用法: $0 [app|caddy] [行数]"; exit 1 ;;
esac
