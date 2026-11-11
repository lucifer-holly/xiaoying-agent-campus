# 部署交接：xiaoying.gret.me（Q1 演示）

> 读者：在本机运行的 Claude Code，或本人。
> 演示已上线：首次部署 2026-11-10 22:31，最近一次部署 2026-11-11 11:44（版本 `4d512fa`：收尾测试和第二次独立复核的修复、补充说明评测；此前的节点图回放、新建任务与补充说明、页面改版、取消口令、数据接入入口都已包含；回滚已于 09:12 验证）。
> 本文件记录实际做了什么、日常怎么运维、怎么回滚、怎么做健康检查。
> 分工：服务器环境、模型 API Key、域名 `xiaoying.gret.me` 与 DNS 解析由本人配置；部署脚本和配置由 AI 编写，最终部署由本机 Claude Code 在本人授权下通过 SSH 执行。

## 0. 红线（任何操作前先读）

- **不得改动 booksprite / gamesci.gret.me 的任何配置和服务**：`/srv/shuling`、`shuling.service`、Caddyfile 里的 `gamesci.gret.me` 站点块、`/var/log/caddy/access.log`。
- Caddy 只 `reload`，不 `restart`。改 Caddyfile 前先备份，改后先 `caddy validate`。
- 密钥只放服务器 `/srv/xiaoying-agent/.env`（root 所有，权限 600），不进仓库。本机副本是 `.env.server`，已被 `.gitignore` 排除。
- 提交不带 AI 署名。本机 `~/.claude/settings.json` 已配置 `"attribution": {"commit": "", "pr": ""}`，不要改回去。

## 1. 现状

| 项 | 值 |
|---|---|
| 地址 | <https://xiaoying.gret.me/>（回放 + 新建任务）；静态回放 <https://lucifer-holly.github.io/xiaoying-agent-campus/demo/>（GitHub Pages，`main` 分支根目录，分支更新后自动重建） |
| DNS / 证书 | A 记录 → 47.99.125.122；Let's Encrypt 证书由 Caddy 自动签发和续期（首张有效期至 2027-02-08） |
| 服务器 | SSH 别名 `aliyun`（root）；Ubuntu 24.04.4，Caddy 2.11.4，Python 3.12.3（已装 `python3.12-venv`），systemd 255，cgroup v2；内存约 1.6G |
| 服务 | `xiaoying-agent.service`：User=caddy，只监听 `127.0.0.1:8710`；`ProtectSystem=strict`，只有 `state/` 可写；`/srv/shuling`、`/var/lib/caddy`、`/etc/caddy` 对它不可见；`MemoryMax=300M`（实际约 40M）；`systemd-analyze security` 评分 4.6 |
| 目录 | `/srv/xiaoying-agent/`：`app/`（代码，root 所有、对服务只读）、`app.prev/`（上一版，用于回滚）、`venv/`、`state/`（caddy 可写，只有每日计数 `quota.json`）、`.env`（root 600） |
| Caddy | 在 `/etc/caddy/Caddyfile` 末尾追加了 `deploy/Caddyfile.xiaoying` 的站点块，没有改动已有内容。修改前的备份：`/etc/caddy/Caddyfile.bak-20261110-223022` |
| 防护 | 无需口令，打开即可新建任务（真实模型现场运行）；每个 IP 5 次/600 秒；每天 50 次（落盘，跨重启累计）；并发 2。超限时页面给出提示和对应场景的回放入口 |
| 版本 | `/api/health` 的 `version` 字段是部署时 main 分支的提交短 SHA |

**已验证**（都在服务器上经公网 DNS 完成）：

- `/api/health` 返回 200，证书校验通过；静态资源与 gzip 正常；路径穿越返回 404。
- 跑通实时运行：02 用例，11.7 秒，`needs_confirmation`，与录制一致（当时启用了口令，错误口令返回 403；之后按需求取消了口令）。
- 跑通带补充说明的新建任务（`477bcfd`）：02 场景加“如果 18:00 被占，优先排到 20:00 以后”，14.4 秒，选了 21:00 并存为待确认草稿，校验器无更正。
- 第二次复核的修复（`4d512fa`）：`repeat: 2.0`、只适用于保存的故障模式用在别的工具上、孤立代理项字符、`case_id` 不是字符串、`constraints` 不是对象，都在调用模型之前返回 400，额度不变；连续提交两次的真实任务（场景 06）20.5 秒，两次都完成，只有 1 份草稿；日志里没有堆栈。
- 收尾测试（`f27dcdd`）：不存在的日期（如 2 月 30 日）返回 400，不调用模型；超过 16KB 的请求体由 Caddy 的 `request_body` 上限直接返回 413，应用日志只记一行“客户端在响应写完之前断开”，属正常；带补充说明“19:00 不要用”的真实任务 14.2 秒，选 21:00 并存为待确认草稿。
- `gamesci.gret.me/api/health` 在 Caddy reload 前后、每次部署后都是 200。
- `scripts/deploy.sh rollback` 能回到上一版，再部署能恢复。

## 2. 访问口令（当前未启用）

- 评审打开页面就能直接用真实模型运行，不需要口令。费用由按 IP 限流、每日上限（`DEMO_DAILY_LIMIT`，默认 50）和并发上限兜住。
- 如需临时限制访问：在服务器 `/srv/xiaoying-agent/.env` 里填写 `DEMO_ACCESS_CODE=…`，再 `ssh aliyun systemctl restart xiaoying-agent`，页面会自动出现口令输入框；清空这一行并重启即恢复开放。
- 调整每日上限：改 `.env` 里的 `DEMO_DAILY_LIMIT` 后重启服务。

## 3. 日常操作（本机执行，在仓库根目录下）

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
- 页面只有回放、没有“新建任务”：`/api/health` 的 `live_enabled` 为 false，说明 `.env` 里缺 `LLM_API_KEY` 或 `DEMO_ACCESS_CODE`。
- 新建任务提示次数用完：`quota.used_today` 达到 `DEMO_DAILY_LIMIT`，次日自动清零；临时调整就改 `.env` 再重启。
- 证书问题：`ssh aliyun "journalctl -u caddy --no-pager | grep xiaoying | tail"`。

## 5. 从零重建（服务器重装时）

```bash
# 1) DNS：xiaoying.gret.me 的 A 记录指向服务器
# 2) Python venv 支持（Ubuntu 24.04）
ssh aliyun "apt install -y python3.12-venv"
# 3) 服务器 .env（模板见 deploy/server.env.example）
ssh aliyun 'mkdir -p -m 755 /srv/xiaoying-agent && (umask 077; cat > /srv/xiaoying-agent/.env)' < .env.server
# 4) Caddy：备份 → 只追加本站点块 → 校验 → reload（不要 restart）
ssh aliyun 'cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d-%H%M%S) && { printf "\n"; cat; } >> /etc/caddy/Caddyfile && caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && systemctl reload caddy' < deploy/Caddyfile.xiaoying
# 5) 部署
scripts/deploy.sh
```

## 6. 完全撤下（如需要）

```bash
ssh aliyun "systemctl disable --now xiaoying-agent && rm /etc/systemd/system/xiaoying-agent.service && systemctl daemon-reload"
# 从 /etc/caddy/Caddyfile 删除 xiaoying.gret.me 站点块（只删这一块，其余不动），validate 后 reload
ssh aliyun "rm -rf /srv/xiaoying-agent"
```

## 7. 仓库结构与提交 SHA

- 2026-11-11 起仓库只保留 `main` 一个分支，项目文件直接放在仓库根目录（原来的 `q1-asset-scheduling/` 目录和 `submission` 分支已合并掉）。最终提交的 commit SHA 以 `main` 的最新提交为准。
- GitHub Pages 的来源是 `main` 分支根目录，所以回放页地址仍是 <https://lucifer-holly.github.io/xiaoying-agent-campus/demo/>，`main` 更新后自动重建。
- 本机克隆在 `git pull` 之后，要把没进仓库的 `.env.server` 从原来的 `q1-asset-scheduling/` 目录手动移到仓库根目录（`mv q1-asset-scheduling/.env.server .`），否则第 5 节的重建命令找不到它。
