# 小影校招 AI Agent 开发岗考核 · 题目 1：素材审核与发布排期 Agent

## 提交信息

| 项 | 内容 |
|---|---|
| 题号 | **1（素材审核与发布排期 Agent）** |
| 仓库 | <https://github.com/lucifer-holly/xiaoying-agent-campus> |
| 提交分支 | `submission`：由 `git subtree split --prefix=q1-asset-scheduling` 从 main 导出，分支根目录就是项目本身，符合交付规范的目录结构 |
| 最终 commit SHA | 以 `submission` 分支的最新提交为准 |

在 main 分支上，项目位于 [`q1-asset-scheduling/`](q1-asset-scheduling/)，内容与 `submission` 分支相同。

## 评审入口

| 想看什么 | 去哪里 |
|---|---|
| 环境、安装、运行命令、评审自测 | [`q1-asset-scheduling/README.md`](q1-asset-scheduling/README.md) |
| 验收点逐条对照（预期 / 实际 / Trace） | [`docs/03-evaluation.md`](q1-asset-scheduling/docs/03-evaluation.md) |
| 真实模型的输入、输出、Trace | [`examples/`](q1-asset-scheduling/examples/) |
| AI 辅助范围与本人贡献 | [`docs/04-ai-usage.md`](q1-asset-scheduling/docs/04-ai-usage.md) |
| 在线演示（补充体验，不替代命令行） | 回放页 <https://lucifer-holly.github.io/xiaoying-agent-campus/demo/>（静态）；实时演示 <https://xiaoying.gret.me/>（真实模型现场运行，无需口令，有限流） |

## 验收清单

| 要求 | 证据 |
|---|---|
| ReAct 循环：模型选择动作 → 执行工具 → 观察结果 → 调整下一步或结束 | [`src/agent/loop.py`](q1-asset-scheduling/src/agent/loop.py)；docs/02 第 1–2 节 |
| 至少两条真实模型执行路径，体现根据工具结果调整动作 | `01`（18:00 空闲 → 直接保存）对比 `02`（18:00 被占 → 查当天 → 19:00 待确认）；docs/03 第 3 节 |
| Trace 含步骤、工具参数、返回摘要、后续动作、决策依据 | `examples/*.trace.json`；docs/02 第 4 节 |
| 步数 / 工具调用上限，触顶返回未完成状态 | 用例 `08-step-limit` → `incomplete_step_limit` |
| 正常、信息不足、工具失败等场景的输入 + 实际输出 + 运行记录，覆盖全部必须验收点 | 10 个用例：正常排期、素材信息缺失、规则风险（阻断 / 补查）、时段冲突、重复提交、保存失败、保存超时已写入、步数上限、日期不能改且当天排满；docs/03 第 2 节 |
| 离线 Mock 入口，并标明 Mock 的边界 | `--llm mock`；docs/03 第 7 节 |
| 可复制的运行命令，测试可执行，结果在 examples/ | Q1 README；[`examples/test-results.txt`](q1-asset-scheduling/examples/test-results.txt) |
| AI 使用如实记录，含个人修改与验证 | docs/04 |
| 实际用时、未完成部分 | [`docs/05-retrospective.md`](q1-asset-scheduling/docs/05-retrospective.md) |
| 不提交真实密钥或隐私数据 | `.env` 已被排除，只提交 `.env.example`；数据全部是合成的 |

## 仓库里的其他文件

- [`PLAN.md`](PLAN.md)：前期规划记录，包括四道题的拆解、选题对比、骨架设计和交接计划。最终实现以 `q1-asset-scheduling/docs/` 为准。
- [`DEPLOY_HANDOFF.md`](DEPLOY_HANDOFF.md)：演示站点的部署记录、运维、回滚和健康检查。
