#!/usr/bin/env bash
# Q1 演示部署（在本机执行，不在服务器上执行）：
#   本地检查 → 服务器检查（root、caddy 用户、Python >= 3.10、.env、端口）→ 备份当前版本
#   → rsync 代码 → 服务器 venv 安装依赖 → 安装/更新 systemd unit → 重启 → 本机端口与 HTTPS 健康检查
#
#   scripts/deploy.sh            部署（默认）
#   scripts/deploy.sh status     查看服务状态与健康检查
#   scripts/deploy.sh rollback   回滚到上一次部署的版本
#
# 环境变量：XIAOYING_HOST（SSH 别名，默认 aliyun）、XIAOYING_DOMAIN（默认 xiaoying.gret.me）、
#           XIAOYING_PIP_INDEX（可选，pip 镜像地址）
#
# 只会改动：/srv/xiaoying-agent/{app,app.prev,venv,state}、/etc/systemd/system/xiaoying-agent.service、
# xiaoying-agent 服务本身。不会创建或覆盖 /srv/xiaoying-agent/.env，不碰 Caddy 配置，
# 不碰 booksprite（/srv/shuling、shuling 服务、gamesci.gret.me）。
set -euo pipefail

HOST="${XIAOYING_HOST:-aliyun}"
DOMAIN="${XIAOYING_DOMAIN:-xiaoying.gret.me}"
PIP_INDEX="${XIAOYING_PIP_INDEX:-}"
REMOTE=/srv/xiaoying-agent
SERVICE=xiaoying-agent

cd "$(dirname "$0")/.."

step() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
warn() { printf "\033[33m! %s\033[0m\n" "$1"; }
die()  { printf "\033[31m✗ %s\033[0m\n" "$1" >&2; exit 1; }
remote() { ssh "$HOST" "$@"; }

remote_port() {
  # 端口以服务器 .env 为准（没写就是 unit 里的默认 8710）
  remote "grep -E '^PORT=' $REMOTE/.env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]\"'" || true
}

wait_local_health() {
  local port="$1"
  for _ in $(seq 1 15); do
    if remote "curl -sf -m 3 http://127.0.0.1:$port/api/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

check_https() {
  remote "curl -sf -m 10 --resolve $DOMAIN:443:127.0.0.1 https://$DOMAIN/api/health"
}

cmd="${1:-deploy}"
case "$cmd" in
  deploy|status|rollback) ;;
  *) echo "用法：$0 [deploy|status|rollback]"; exit 2 ;;
esac

remote true 2>/dev/null || die "无法通过 SSH 连接 $HOST（检查 ~/.ssh/config 里的别名，或设置 XIAOYING_HOST）"
PORT="$(remote_port)"; PORT="${PORT:-8710}"

if [ "$cmd" = "status" ]; then
  remote "systemctl --no-pager -n 20 status $SERVICE" || true
  step "本机端口 $PORT"; remote "curl -s -m 5 http://127.0.0.1:$PORT/api/health" || warn "本机端口无响应"
  step "HTTPS $DOMAIN"; check_https || warn "HTTPS 无响应"
  echo; exit 0
fi

if [ "$cmd" = "rollback" ]; then
  step "回滚到上一个版本"
  remote "test -d $REMOTE/app.prev" || die "没有可回滚的版本（$REMOTE/app.prev 不存在）"
  remote "rm -rf $REMOTE/app.failed && mv $REMOTE/app $REMOTE/app.failed && mv $REMOTE/app.prev $REMOTE/app && systemctl restart $SERVICE"
  wait_local_health "$PORT" || die "回滚后服务仍未就绪，看日志：scripts/server-logs.sh"
  remote "cat $REMOTE/app/VERSION 2>/dev/null" || true
  printf "\n\033[32m✅ 已回滚（出问题的版本保存在 %s/app.failed）\033[0m\n" "$REMOTE"
  exit 0
fi

# ---------------------------------------------------------------------------
step "本地检查"
[ -f demo/data/replay.js ] || die "缺少 demo/data/replay.js，先运行 python scripts/build_demo.py"
for f in src/server.py requirements.txt deploy/xiaoying-agent.service; do [ -f "$f" ] || die "缺少 $f"; done
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  VERSION="$(git rev-parse --short HEAD)"
  [ -z "$(git status --porcelain -- .)" ] || VERSION="$VERSION-dirty"
else
  VERSION="unknown"
fi
echo "  版本 $VERSION"

step "服务器检查"
remote 'test "$(id -u)" = 0' || die "需要以 root 登录 $HOST（与 booksprite 的部署方式一致）"
remote 'id caddy >/dev/null 2>&1' || die "服务器上没有 caddy 用户：服务按计划以 caddy 用户运行，请先确认 Caddy 的安装方式"
PY="$(remote 'for p in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c "import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then command -v "$p"; exit 0; fi
done; exit 1')" || die "服务器没有 Python 3.10+（含 venv / ensurepip 模块）。
  Ubuntu 24.04：apt install -y python3.12-venv
  Ubuntu 22.04：apt install -y python3.10-venv
  Alibaba Cloud Linux 3 / CentOS Stream 8：dnf install -y python3.11
  Debian 12：apt install -y python3-venv
装好后重新运行本脚本。"
echo "  Python：$PY（$(remote "$PY -V" 2>&1)）"
remote "test -f $REMOTE/.env" || die "缺少 $REMOTE/.env：按 DEPLOY_HANDOFF.md 用 deploy/server.env.example 创建（部署脚本不会替你创建或覆盖它）"
remote "grep -qE '^LLM_API_KEY=.+' $REMOTE/.env" || warn ".env 里 LLM_API_KEY 为空：页面只有回放，没有实时运行"
remote "grep -qE '^DEMO_ACCESS_CODE=.+' $REMOTE/.env" || warn ".env 里 DEMO_ACCESS_CODE 为空：实时运行会关闭"
[ "$PORT" != "3000" ] || die "端口 3000 是 booksprite 在用的，请在 $REMOTE/.env 里改 PORT"
OWNER_PID="$(remote "systemctl show -p MainPID --value $SERVICE 2>/dev/null || echo 0")"
LISTENER="$(remote "ss -ltnpH 'sport = :$PORT' 2>/dev/null" || true)"
if [ -n "$LISTENER" ] && ! printf '%s' "$LISTENER" | grep -q "pid=${OWNER_PID}[,)]"; then
  die "端口 $PORT 已被其他进程占用：$LISTENER"
fi
echo "  端口：$PORT"

step "备份当前版本"
remote "mkdir -p $REMOTE/app $REMOTE/state && if [ -d $REMOTE/app/src ]; then rm -rf $REMOTE/app.prev && cp -a $REMOTE/app $REMOTE/app.prev && echo '  已备份到 app.prev'; else echo '  首次部署，无需备份'; fi"

step "同步代码"
rsync -az --delete \
  --exclude '__pycache__/' --exclude '*.pyc' \
  --include '/src/***' --include '/data/***' --include '/demo/***' \
  --include '/examples/' --include '/examples/*.input.json' \
  --include '/requirements.txt' \
  --exclude '*' \
  ./ "$HOST:$REMOTE/app/"
remote "printf '%s\n' '$VERSION' > $REMOTE/app/VERSION"

step "安装依赖"
remote "if [ ! -x $REMOTE/venv/bin/python ] || ! $REMOTE/venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then rm -rf $REMOTE/venv && $PY -m venv $REMOTE/venv; fi"
remote "$REMOTE/venv/bin/pip install -q --disable-pip-version-check ${PIP_INDEX:+-i $PIP_INDEX} -r $REMOTE/app/requirements.txt"

step "安装 systemd unit"
scp -q deploy/xiaoying-agent.service "$HOST:/tmp/$SERVICE.service.new"
remote "if ! cmp -s /tmp/$SERVICE.service.new /etc/systemd/system/$SERVICE.service; then install -m 644 /tmp/$SERVICE.service.new /etc/systemd/system/$SERVICE.service && systemctl daemon-reload && echo '  unit 已更新'; else echo '  unit 无变化'; fi; rm -f /tmp/$SERVICE.service.new; systemctl enable --quiet $SERVICE"

step "设置权限"
# 代码和 venv 属 root、对服务用户只读；只有 state/ 归 caddy 可写；.env 只有 root 能读（systemd 以 root 读取）
remote "chown root:root $REMOTE && chmod 755 $REMOTE && chown -R root:root $REMOTE/app $REMOTE/venv && chmod -R a+rX $REMOTE/app $REMOTE/venv && chown caddy:caddy $REMOTE/state && chmod 700 $REMOTE/state && chown root:root $REMOTE/.env && chmod 600 $REMOTE/.env"

step "重启服务"
remote "systemctl restart $SERVICE"
if ! wait_local_health "$PORT"; then
  warn "服务在本机端口 $PORT 上没有就绪"
  remote "journalctl -u $SERVICE -n 30 --no-pager" || true
  if remote "test -d $REMOTE/app.prev"; then
    warn "自动回滚到上一个版本"
    remote "rm -rf $REMOTE/app.failed && mv $REMOTE/app $REMOTE/app.failed && mv $REMOTE/app.prev $REMOTE/app && systemctl restart $SERVICE"
    wait_local_health "$PORT" && die "新版本启动失败，已回滚并恢复服务；失败的版本在 $REMOTE/app.failed" || die "回滚后仍未就绪，请看日志"
  fi
  die "首次部署启动失败，请看上面的日志"
fi
remote "curl -s -m 5 http://127.0.0.1:$PORT/api/health"; echo

step "HTTPS 健康检查"
if ! check_https; then
  die "服务已在本机端口 $PORT 正常运行，但 https://$DOMAIN/api/health 不通。
  常见原因：Caddy 里还没加站点片段（deploy/Caddyfile.xiaoying）、Caddy 没 reload、DNS 未生效或证书仍在签发。
  排查：ssh $HOST 'journalctl -u caddy -n 50 --no-pager'"
fi
echo

step "确认同机的 booksprite 未受影响（只读检查）"
code="$(remote "curl -s -o /dev/null -w '%{http_code}' -m 10 --resolve gamesci.gret.me:443:127.0.0.1 https://gamesci.gret.me/api/health" || true)"
echo "  gamesci.gret.me/api/health → HTTP $code"
[ "$code" = "200" ] || warn "gamesci.gret.me 健康检查不是 200，请人工确认（本脚本没有改动它的任何配置）"

printf "\n\033[32m✅ 已上线  https://%s/   版本 %s\033[0m\n" "$DOMAIN" "$VERSION"
