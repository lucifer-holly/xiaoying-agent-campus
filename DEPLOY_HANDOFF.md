# 部署交接：xiaoying.gret.me（Q1 演示）

> 读者：在本机运行的 Claude Code，或本人。
> 演示已上线：首次部署 2026-11-10 22:31，最近一次部署 2026-11-11 10:21（版本 `5e46a55`：页面改版、实时运行取消口令、“模型如何应变”节点图、首页核心卖点、页面去掉实现细节；回滚已于 09:12 验证）。
> 本文件记录实际做了什么、日常怎么运维、怎么回滚、怎么做健康检查。

## 0. 红线（任何操作前先读）

- **不得改动 booksprite / gamesci.gret.me 的任何配置和服务**：`/srv/shuling`、`shuling.service`、Caddyfile 里的 `gamesci.gret.me` 站点块、`/var/log/caddy/access.log`。
- Caddy 只 `reload`，不 `restart`。改 Caddyfile 前先备份，改后先 `caddy validate`。
- 密钥只放服务器 `/srv/xiaoying-agent/.env`（root 所有，权限 600），不进仓库。本机副本是 `q1-asset-scheduling/.env.server`，已被 `.gitignore` 排除。
- 提交不带 AI 署名。本机 `~/.claude/settings.json` 已配置 `"attribution": {"commit": "", "pr": ""}`，不要改回去。

## 1. 现状

| 项 | 值 |
|---|---|
| 地址 | <https://xiaoying.gret.me/>（回放 + 实时运行）；静态回放 <https://lucifer-holly.github.io/xiaoying-agent-campus/demo/>（GitHub Pages，`submission` 分支根目录，分支更新后自动重建） |
| DNS / 证书 | A 记录 → 47.99.125.122；Let's Encrypt 证书由 Caddy 自动签发和续期（首张有效期至 2027-02-08） |
| 服务器 | SSH 别名 `aliyun`（root）；Ubuntu 24.04.4，Caddy 2.11.4，Python 3.12.3（已装 `python3.12-venv`），systemd 255，cgroup v2；内存约 1.6G |
| 服务 | `xiaoying-agent.service`：User=caddy，只监听 `127.0.0.1:8710`；`ProtectSystem=strict`，只有 `state/` 可写；`/srv/shuling`、`/var/lib/caddy`、`/etc/caddy` 对它不可见；`MemoryMax=300M`（实际约 40M）；`systemd-analyze security` 评分 4.6 |
| 目录 | `/srv/xiaoying-agent/`：`app/`（代码，root 所有、对服务只读）、`app.prev/`（上一版，用于回滚）、`venv/`、`state/`（caddy 可写，只有每日计数 `quota.json`）、`.env`（root 600） |
| Caddy | 在 `/etc/caddy/Caddyfile` 末尾追加了 `q1-asset-scheduling/deploy/Caddyfile.xiaoying` 的站点块，没有改动已有内容。修改前的备份：`/etc/caddy/Caddyfile.bak-20261110-223022` |
| 防护 | 无需口令，打开即可实时运行；每个 IP 5 次/600 秒；每天 50 次（落盘，跨重启累计）；并发 2。超限时页面自动切到回放 |
| 版本 | `/api/health` 的 `version` 字段是部署时 main 分支的提交短 SHA |

**已验证**（都在服务器上经公网 DNS 完成）：

- `/api/health` 返回 200，证书校验通过；静态资源与 gzip 正常；路径穿越返回 404。
- 跑通实时运行：02 用例，11.7 秒，`needs_confirmation`，与录制一致（当时启用了口令，错误口令返回 403；之后按需求取消了口令）。
- `gamesci.gret.me/api/health` 在 Caddy reload 前后、每次部署后都是 200。
- `scripts/deploy.sh rollback` 能回到上一版，再部署能恢复。

## 2. 访问口令（当前未启用）

- 评审打开页面就能直接用真实模型运行，不需要口令。费用由按 IP 限流、每日上限（`DEMO_DAILY_LIMIT`，默认 50）和并发上限兜住。
- 如需临时限制访问：在服务器 `/srv/xiaoying-agent/.env` 里填写 `DEMO_ACCESS_CODE=…`，再 `ssh aliyun systemctl restart xiaoying-agent`，页面会自动出现口令输入框；清空这一行并重启即恢复开放。
- 调整每日上限：改 `.env` 里的 `DEMO_DAILY_LIMIT` 后重启服务。

## 3. 日常操作（本机执行，在 `q1-asset-scheduling/` 目录下）

```bash
scripts/deploy.sh             # 重新部署（同步代码 → 装依赖 → 重启 → 健康检查）
scripts/deploy.sh status      # 服务状态、本机端口与 HTTPS 健康检查
scripts/deploy.sh rollback    # 回到上一次部署的版本
scripts/server-logs.sh app 80 # 应用日志（访客 IP 只记哈希）
scripts/server-logs.sh caddy 80
```

重录 `examples/` 之后，先运行 `python scripts/build_demo.py` 更新回放数据，再提交、部署。

`deploy.sh` 会做的事：

1. 检查 root、caddy 用户、Python ≥ 3.10（含 venv / ensurepip）、`.env` 存在；端口没被其他进程占用，且不是 3000。
2. 把当前版本备份为 `app.prev`，再 rsync `src/`、`data/`、`demo/`、`examples/*.input.json`、`requirements.txt`。
3. 在 venv 里安装依赖（服务器已配置阿里云内网 pip 镜像），安装或更新 systemd unit，设置权限。
4. 重启，在本机端口做健康检查；失败时自动回滚到 `app.prev`。
5. HTTPS 健康检查，并对 `gamesci.gret.me` 做只读检查。

它不会做的事：不创建、不覆盖 `.env`；不改 Caddyfile；不碰 `/srv/shuling` 和 `shuling.service`。

## 4. 健康检查与排障

- 从任意网络：`curl -s https://xiaoying.gret.me/api/health`，应看到 `"ok": true, "live_enabled": true`。
- **注意**：本机（这台 Mac）当前的网络代理访问这台服务器的 HTTPS 会报 TLS 连接错误，访问 `gamesci.gret.me` 也一样，不是服务的问题。要验证，请在服务器上用 `curl --resolve xiaoying.gret.me:443:127.0.0.1 https://xiaoying.gret.me/api/health`，或用手机、其他网络打开。
- 502：应用没起来，看 `scripts/server-logs.sh app`，以及 `ssh aliyun systemctl status xiaoying-agent`。
- 页面只有回放、没有“实时运行”：`/api/health` 的 `live_enabled` 为 false，说明 `.env` 里缺 `LLM_API_KEY` 或 `DEMO_ACCESS_CODE`。
- 实时运行提示次数用完：`quota.used_today` 达到 `DEMO_DAILY_LIMIT`，次日自动清零；临时调整就改 `.env` 再重启。
- 证书问题：`ssh aliyun "journalctl -u caddy --no-pager | grep xiaoying | tail"`。

## 5. 从零重建（服务器重装时）

```bash
# 1) DNS：xiaoying.gret.me 的 A 记录指向服务器
# 2) Python venv 支持（Ubuntu 24.04）
ssh aliyun "apt install -y python3.12-venv"
# 3) 服务器 .env（模板见 q1-asset-scheduling/deploy/server.env.example）
ssh aliyun 'mkdir -p -m 755 /srv/xiaoying-agent && (umask 077; cat > /srv/xiaoying-agent/.env)' < q1-asset-scheduling/.env.server
# 4) Caddy：备份 → 只追加本站点块 → 校验 → reload（不要 restart）
ssh aliyun 'cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d-%H%M%S) && { printf "\n"; cat; } >> /etc/caddy/Caddyfile && caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && systemctl reload caddy' < q1-asset-scheduling/deploy/Caddyfile.xiaoying
# 5) 部署
cd q1-asset-scheduling && scripts/deploy.sh
```

## 6. 完全撤下（如需要）

```bash
ssh aliyun "systemctl disable --now xiaoying-agent && rm /etc/systemd/system/xiaoying-agent.service && systemctl daemon-reload"
# 从 /etc/caddy/Caddyfile 删除 xiaoying.gret.me 站点块（只删这一块，其余不动），validate 后 reload
ssh aliyun "rm -rf /srv/xiaoying-agent"
```

## 7. 提交 SHA

- 正式提交用 `submission` 分支，它由 `git subtree split --prefix=q1-asset-scheduling` 导出，分支根目录就是项目。
- 当前最终 SHA：`5c9423a971e1fad133b627e85faca8f6bff3b5d0`。
- 之后如果又改了 `q1-asset-scheduling/`（例如在 docs/04 补“本人修改记录”），在 main 上提交后重新导出：

```bash
git subtree split --prefix=q1-asset-scheduling -b submission   # 分支已存在时会快进更新
git push origin main submission
git rev-parse submission                                          # 新的提交 SHA
```

本文件和 `PLAN.md` 在仓库根目录，不属于 `q1-asset-scheduling/`，修改它们不会改变 `submission` 的 SHA。
