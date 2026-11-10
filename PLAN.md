# 工作计划与交接文档

> 本文件是主 Agent 的交接文档：新会话先读这里，再继续工作。
> 最后更新：2026-11-10（前期准备阶段）

## 0. 当前状态

- [x] 仓库已创建并推送：`lucifer-holly/xiaoying-agent-campus`（公开）
- [x] 四道题已拆解（第 2 节）
- [x] 共用骨架设计已定（第 3 节）
- [x] 范围已定：**只做 Q1（素材审核与发布排期）**，由主 Agent 在云端全程规划、开发、测试、验收；不使用用户自有服务器（规则不要求部署，部署不加分）
- [x] 模型已定：阿里云百炼 Qwen3.8 系列（OpenAI 兼容接口，见第 3.1 节）
- [x] 用户已配置网络密钥与环境变量（见第 3.1 节）
- [ ] 编写共用骨架（Mock 先跑通）
- [ ] 分派子 Agent 逐题实现
- [ ] 真实模型录制 Trace（需要 Key，须在新会话中进行）
- [ ] 主 Agent 逐题验收 → 选题 → `git subtree split` 导出提交分支

提交约定：commit 不加任何 AI 署名（用户红线）。仓库本地 git 身份为 `lucifer-holly <63133305+lucifer-holly@users.noreply.github.com>`，`commit.gpgsign=false`。新会话中须重新执行：

```bash
git config user.name "lucifer-holly" && git config user.email "63133305+lucifer-holly@users.noreply.github.com" && git config commit.gpgsign false
```

## 0.1 新会话执行顺序（Q1）

1. 恢复 git 身份配置（见上），`git pull`
2. 冒烟测试：用 `openai` SDK 对 `LLM_BASE_URL` 发一个极短请求 + 一个带工具的请求，确认认证注入与 function calling 可用（失败按第 3.1 节处理）
3. 在 `q1-asset-scheduling/` 实现骨架（第 3 节）+ 业务工具 + 合成数据 + 校验器
4. 单元测试与 Mock 流程测试全绿
5. 真实模型录制全部验收用例 Trace；未走出预期路径时调整提示词并如实记录迭代过程
6. 写 docs/01–05、README；更新根 README 进度
7. 主 Agent 自验收（对照第 2 节 Q1 验收点 + 根 README 清单），可派一个独立子 Agent 只读复核“越权发布 / 虚报保存成功 / 防重复”
8. `git subtree split` 导出提交分支并推送，把 SHA 交给用户
9. 实际用时、AI 使用范围如实写入 docs/04、docs/05
10. （核心验收通过后）做演示，见第 6 节：云端完成回放页、HTTP 服务、`deploy/` 与 `scripts/deploy.sh`，并在云端本地端口实跑验证；**部署由用户在本地 Claude Code 完成**
11. 写 `DEPLOY_HANDOFF.md`：给本地 Claude Code 的部署交接说明（前置检查、步骤、回滚、健康检查；明确不得改动 booksprite / gamesci.gret.me 的任何配置和服务）
12. 本地部署后的提交（如 README 演示链接确认）同样不得带 AI 署名：本地 `~/.claude/settings.json` 需关闭 co-author（如 `"includeCoAuthoredBy": false`，以所用版本文档为准）

## 6. 演示链接（核心完成后再做，用时单独记录）

- 定位：补充体验，README 主入口仍是 CLI 命令；规则写明截图/视频不能替代代码
- ① 回放页（必做）：`q1-asset-scheduling/demo/` 静态页，读取 `examples/*.trace.json` 逐步展示真实模型 Trace；发布到 GitHub Pages
- ② 实时演示（已确认要做）：同一套 Agent 外包一层 HTTP API + 简单网页，部署方式**照搬 booksprite**（参考 `lucifer-holly/booksprite` 的 `scripts/deploy.sh` 与 `docs/DEVELOPMENT.md` 第 7 节）：
  - 地址：`https://xiaoying.gret.me/`（用户已确认，DNS 已配置）；用户已有 `gamesci.gret.me` 在同一台阿里云服务器上
  - 栈：Caddy（自动 HTTPS、反代）+ systemd 服务 `xiaoying-agent`（以 caddy 用户运行，`ProtectSystem=strict`）+ 目录 `/srv/xiaoying-agent`；应用监听 `127.0.0.1:<端口>`，不得与 booksprite 的 3000 冲突
  - 部署：`scripts/deploy.sh` 在**用户本机**执行，SSH 别名默认 `aliyun`（可用环境变量覆盖），rsync 同步代码 → 服务器 venv 安装依赖 → 重启 → HTTPS 健康检查 `/api/health`
  - 服务器约束：内存约 1.6G，依赖保持最少；脚本先检查 Python >= 3.10，不满足时给出安装指引
  - 密钥：只放服务器 `/srv/xiaoying-agent/.env`（`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`DEMO_ACCESS_CODE`、限流参数），部署脚本不覆盖
  - 防护：访问口令、按 IP 限流、每日调用上限，超限自动切回放；页面明确标注“仅保存草稿，不会真实发布”
  - 云端会话不持有服务器 SSH 凭据；交付 `deploy/`（Caddy 站点片段、systemd unit、.env 模板）+ `scripts/deploy.sh` + 分步说明
- 部署细节由执行 Agent 自行设计（用户授权）；用户部署时要做：① （DNS 已由用户完成）② 把 Caddy 片段加入服务器 Caddyfile 并 reload；③ 创建服务器 `.env`；④ 本机执行 `scripts/deploy.sh`

## 1. 总原则

1. **模型做决策，代码守边界。** 选择下一步动作（补查、换时段、改写查询、重规划、追问、停止）交给模型；硬约束由工具层或输出校验器强制执行，不依赖模型自觉。例如：不能发布、保存要幂等、保存状态如实返回、引用必须是原文子串、费用由代码计算。
2. **真实模型的证据和 Mock 分开写。** Mock（预设脚本）只验证流程；“模型根据工具结果调整动作”必须用真实模型的 Trace 证明，并在文档中写明这条边界。
3. **每个验收点 = 一个 example 文件组**（`*.input.json` / `*.output.json` / `*.trace.json`），由 `docs/03` 逐条引用。
4. **故障注入写在输入里**（例如 `"fault_injection": {"save_draft": "error"}`），保证“工具失败”场景能稳定复现，真实模型下也一样。

## 2. 四道题拆解

### Q1 素材审核与发布排期 → `q1-asset-scheduling/`

- 工具：`read_asset`（读取素材）、`check_rules`（规则检查）、`query_slots`（时段查询）、`save_draft`（保存排期草稿）
- 模型决策点：发现风险 → 补查或阻断；时段冲突 → 查替代时段，并标记待确认；硬性要求（如指定日期）未经同意不得更改 → 请求确认
- 代码守边界：
  - 不存在“发布”工具，输出状态里也没有 `published`
  - `save_draft` 按请求内容哈希做幂等，重复提交只产生一份草稿
  - 保存失败时，最终输出由校验器强制写成失败，不允许模型虚报成功
- 验收用例：正常排期 / 素材信息缺失 / 规则风险 / 时段冲突（M01 要 18:00 → 建议 19:00 并待确认）/ 重复提交 / 保存失败
- 关键缺陷：越权发布、虚报保存成功
- 两条 ReAct 路径：18:00 空闲 → 直接保存；18:00 占用 → 查询 19:00 → 标记待确认后保存

### Q2 内容任务规划 → `q2-campaign-planning/`

- 工具：`search_materials`（素材检索）、`generate_script`（脚本生成）、`estimate_cost`（成本估算）、`save_plan`（方案保存）
- 模型决策点：超预算 → 换替代方案；工具错误 → 重试、换方案或停止；部分成功 → 保留已成功步骤
- 代码守边界：
  - 步骤状态机（pending / running / succeeded / failed / skipped），失败不能记为成功
  - 费用由代码累加，不由模型计算
  - 运行状态持久化到 `state/`，支持续跑（加分项）
- 验收用例：正常完成 / 缺预算或截止时间 / 工具失败 / 预算超限（预算 10：方案 12 → 改选 8）/ 重复执行
- 关键缺陷：无状态、无失败处理（只能证明串行调用）
- 两条 ReAct 路径：首选方案在预算内 → 保存；超预算 → 换替代方案 → 再估算 → 保存

### Q3 企业知识问答 → `q3-knowledge-qa/`

- 工具：`search_docs`（文档检索，返回文档 ID、标题、版本日期、命中片段）、`read_doc`（读取原文片段）
- 模型决策点：检索为空或结果弱 → 改写查询再检索；命中后读原文；资料冲突 → 列出冲突并请求确认；资料外问题 → 说明缺口并停止
- 代码守边界：
  - 引用校验器：每条引用的原文必须是对应文档的子串，否则判为无效引用
  - 无有效引用时不允许给出“明确答案”状态
- 验收用例：明确答案 / 文档冲突（D01 写 30 天，D02 写 15 天）/ 资料外问题 / 改写后的相似问题 / 上下文追问 / 工具失败
- 关键缺陷：无依据回答、错误引用
- 两条 ReAct 路径：只命中 D01 → 读原文后回答；同时命中 D01 和 D02 → 读两份原文 → 指出冲突并请求确认

### Q4 短视频脚本 → `q4-video-script/`

- 工具：`search_materials`（素材检索）、`estimate_duration`（时长估算）、`check_rules`（规则检查）
- 模型决策点：检索无结果 → 改写查询或请求补充；超时长或规则不通过 → 改稿后再次检查，或明确说明无法满足
- 代码守边界：
  - 事实校验：脚本里的产品事实必须能对应到素材 ID
  - 时长由工具计算，不采信模型自报
  - 规则库包含“无数据不得写效果百分比”
- 验收用例：正常生成 / 缺关键信息 / 无素材 / 工具失败 / 超时长修正（38 秒 → 28 秒）或明确失败
- 关键缺陷：编造产品事实
- 注意：官方示例仓库用的就是这个场景，同质化风险最高

### 选题建议

| 题 | 工程亮点 | 难度 | 风险 | 推荐度 |
|---|---|---|---|---|
| Q1 | 幂等、确认边界、冲突调整，都能用测试硬性证明 | 中 | 低 | ★★★ 首选正式提交 |
| Q3 | 冲突处理、引用校验；改写问题的检索质量取决于检索器 | 中 | 中 | ★★★ |
| Q2 | 状态机、重规划、续跑 | 中高 | 中 | ★★ |
| Q4 | 改稿循环；与示例同质化 | 低 | 同质化 | ★ |

## 3. 共用骨架设计（每题目录内各放一份，保证导出后自包含）

```text
src/
├── main.py           # CLI：--input --llm {mock,real} --max-steps --trace-out
├── agent/loop.py     # ReAct 循环：调用模型 → 解析工具调用 → 执行 → 写回观察 → 直到 finish 或触顶
├── agent/llm.py      # LLM 接口：QwenLLM（百炼 OpenAI 兼容）/ ScriptedMockLLM（按脚本返回）
├── agent/tools.py    # 工具注册：JSON Schema、参数校验、异常统一封装为 {ok, data, error}
├── agent/trace.py    # Trace：step、tool、args、result_summary、next_action、decision_note
├── domain/           # 本题业务工具 + 输出校验器（硬约束）
tests/                # 工具单测、循环单测（Mock）、对已录制真实 Trace 的断言
examples/             # 每个验收点一组 input/output/trace + test-results.txt
scripts/record_examples.py   # 用真实模型批量跑 examples 并落盘
```

关键设计：

- **决策依据**：每个工具的参数里都有必填的 `decision_note`（一句话说明为什么调用），写入 Trace；不提交模型内部思维过程。
- **结束方式**：模型调用 `finish` 工具提交结构化结果，再由校验器修正或降级状态（例如保存失败时不允许写成已保存）。
- **触顶**：达到 `max_steps` 或工具调用次数上限时，返回 `status: "incomplete_step_limit"`，并附上已完成的步骤。
- **统一状态枚举**：`completed` / `needs_input` / `needs_confirmation` / `blocked` / `failed` / `incomplete_step_limit`，各题可增加业务状态。

### 3.1 模型接入（沿用 booksprite 的约定）

- 协议：OpenAI 兼容 Chat Completions + function calling，Python 依赖 `openai` SDK
- 端点：`LLM_BASE_URL`，默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`
- 密钥：`LLM_API_KEY`；为空字符串按缺失处理，此时只能使用 `--llm mock`，并给出明确提示
- **云端会话的密钥注入方式**：真实 Key 配在环境的「网络密钥」里（主机 = 用户百炼工作空间域名，与环境变量 `LLM_BASE_URL` 的域名一致；标头 `Authorization`，前缀 `Bearer`）；`LLM_BASE_URL` 已在环境变量中配置为用户专属工作空间端点，**不得写入仓库**，由出口代理加到请求头上；容器里的环境变量只有占位值 `LLM_API_KEY=injected-by-proxy`。新会话第一步：用一个极短请求验证代理会覆盖占位认证头；若返回 401，改为检测到占位值时不发送 Authorization 头，交由代理添加。评审本地运行时直接把 `LLM_API_KEY` 设为真实 Key，代码无需改动
- 模型：`LLM_MODEL`，默认 `qwen3.8-max`；录制 Trace 时把实际模型名写进 Trace 头部
- 思考模式：Qwen3.5 及以后默认开启思考，booksprite 实测 trivial prompt 也要 16 秒。本项目通过 `extra_body={"enable_thinking": False}` 显式关闭；决策依据改由工具参数 `decision_note` 提供。录制 Trace 前需先实测关闭思考后的工具调用质量，不够再评估是否开启
- 不提交真实密钥：`.env.example` 只列变量名

## 4. 执行编排

1. 主 Agent：在 `q1-asset-scheduling/` 写出骨架并用 Mock 跑通，再复制到另外三个目录。
2. 子 Agent（每题一个，可并行）：只改自己的目录，实现工具、合成数据、校验器、测试、文档；**不执行 git 操作**。
3. 主 Agent 逐题验收：跑测试，对照第 2 节验收点检查，审 Trace；通过后统一提交。
4. 新会话（已配好 Key）：运行 `scripts/record_examples.py` 录制真实 Trace，回填 `docs/03`；若真实模型没有走出预期路径，如实记录并调整提示词，**不得手工编造 Trace**。
5. 选题：用 `git subtree split --prefix=<目录> -b submission` 导出，推送后把提交分支的 SHA 给用户。

## 5. 需要用户完成的事项

| # | 事项 | 状态 |
|---|---|---|
| U1 | 决定范围：规则只要求一道；四道都做（最后选一道提交）还是只做一道 | 待定 |
| U2 | 网络密钥：主机 = 工作空间域名 + 令牌 = 百炼 Key；环境变量：`LLM_BASE_URL`（工作空间端点）、`LLM_API_KEY=injected-by-proxy`（占位） | 待定 |
| U3 | 记录开始时间（`docs/05` 要写实际用时） | 待定 |
| U4 | Key 加好后，开新会话并勾选本仓库，让新会话先读 `PLAN.md` | Key 加好后 |
| U5 | 完成后：亲手运行测试和用例，读懂 `agent/loop.py`，自己改一处并记入 `docs/04` | 实现完成后 |
| U6 | 提交：题号 + 仓库 URL + 主 Agent 给出的 commit SHA | 最后 |
