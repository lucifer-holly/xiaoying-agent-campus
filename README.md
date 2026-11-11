# 小影校招 AI Agent 开发岗考核

本仓库是考核工作区：四道项目题各占一个**自包含目录**，每个目录都按《GitHub 交付规范》组织。
正式提交时只选**一道题**：用 `git subtree split` 把该题目录导出为“根目录即项目”的分支，再提交题号、仓库 URL 和最终 commit SHA。

## 进度

| 题号 | 题目 | 目录 | 状态 |
|---|---|---|---|
| 1 | 素材审核与发布排期 Agent | [`q1-asset-scheduling/`](q1-asset-scheduling/) | **已完成，正式提交** |
| 2 | 内容任务规划 Agent | `q2-campaign-planning/` | 不做（规则只要求一道） |
| 3 | 企业知识问答 Agent | `q3-knowledge-qa/` | 不做 |
| 4 | 短视频脚本 Agent | `q4-video-script/` | 不做 |

## Q1 正式提交

- **提交分支**：`submission`，由 `git subtree split --prefix=q1-asset-scheduling` 导出，分支根目录就是项目本身。最终提交的 commit SHA 以该分支的最新提交为准。
- **评审入口**：[`q1-asset-scheduling/README.md`](q1-asset-scheduling/README.md)（运行命令）、[`docs/03-evaluation.md`](q1-asset-scheduling/docs/03-evaluation.md)（验收对照）、[`examples/`](q1-asset-scheduling/examples/)（真实模型的输入、输出、Trace）。
- **在线演示**：回放页 <https://lucifer-holly.github.io/xiaoying-agent-campus/demo/>（GitHub Pages，静态）；实时演示 <https://xiaoying.gret.me/>（回放 + 实时运行，实时运行需要访问口令）。部署记录与运维说明见 [DEPLOY_HANDOFF.md](DEPLOY_HANDOFF.md)。

详细拆解、设计与交接见 [PLAN.md](PLAN.md)。

## 每题目录结构

```text
<题目目录>/
├── README.md            # 环境、安装、运行、评审入口
├── requirements.txt     # 依赖
├── .env.example         # 所需变量；无变量时注明无需配置
├── src/                 # Agent 循环、模型接入、业务工具
├── tests/               # 可执行测试
├── examples/            # 输入、实际输出、Trace、测试结果
├── data/                # 合成资料和规则
└── docs/
    ├── 01-requirements.md   # 用户、目标、范围、成功标准
    ├── 02-solution.md       # 调用流程、动态决策、技术取舍
    ├── 03-evaluation.md     # 测试预期、实际结果、失败和限制
    ├── 04-ai-usage.md       # AI 辅助内容、个人修改及验证
    └── 05-retrospective.md  # 最难问题、学习收获、下一步
```

## 统一验收清单（每题都要满足）

- [ ] ReAct 循环：模型选择动作 → 执行工具 → 观察结果 → 模型决定下一步或结束；不能只靠固定分支、自动重试或预设日志
- [ ] 至少两条执行路径的**真实模型**运行记录，体现模型根据不同工具结果调整动作
- [ ] Trace 包含：步骤、工具参数、返回摘要、后续动作、简要决策依据
- [ ] 设置步数或工具调用次数上限，触顶时返回明确的未完成状态
- [ ] 至少 3 组“输入 + 实际输出 + 运行记录”，覆盖正常、信息或资料不足、工具失败三种场景，并覆盖本题全部验收点
- [ ] 提供离线 Mock 入口，并写明 Mock 只验证流程，不证明模型决策效果
- [ ] 给出可复制的运行命令；测试可执行，测试结果存放在 `examples/`
- [ ] `docs/03` 引用 `examples/` 中的具体文件；`docs/04` 如实记录 AI 辅助范围、个人修改与验证
- [ ] 记录实际用时与未完成部分；不提交真实密钥或隐私数据

## 统一技术约定（可按题调整）

- Python 3.10+，以 CLI（Command Line Interface，命令行界面）方式运行
- 模型接入做一层薄封装，提供“真实模型 / 离线 Mock”两种实现，用命令行参数切换
- 业务工具使用本地函数 + 合成数据，支持故障注入，便于稳定复现“工具失败”场景
- 每次运行输出结构化 JSON 结果，并把 Trace 写入文件
