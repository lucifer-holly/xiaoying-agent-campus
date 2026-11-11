# 素材审核与发布排期 Agent（Q1）

运营提交一张排期申请单（素材、渠道、时间、硬性要求），Agent 用 ReAct 循环依次读取素材、做规则检查、查询发布时段，最后**只保存排期草稿**：时段被占用时改到当天最近的空闲时段并标记待确认，信息缺失、规则风险、工具失败时停下来，如实说明原因。

- 模型做决策：补查还是阻断、改到哪个时段、重试还是停止，都由模型根据工具结果决定；
- 代码守边界：没有发布工具；必须先通过规则检查；改时间强制待确认；日期硬约束；按申请内容哈希防重复；最终状态和说明由校验器按草稿库核对，杜绝虚报保存成功。

## 评审入口

| 想看什么 | 去哪里 |
|---|---|
| 两条 ReAct 路径（申请单只差日期） | [`examples/01-normal-free-slot.trace.json`](examples/01-normal-free-slot.trace.json)（18:00 空闲 → 直接保存）对比 [`examples/02-slot-conflict.trace.json`](examples/02-slot-conflict.trace.json)（18:00 占用 → 查当天 → 19:00 待确认） |
| 每个验收点的输入、输出、Trace | [`examples/`](examples/)，说明见 [`docs/03-evaluation.md`](docs/03-evaluation.md) |
| ReAct 循环 | [`src/agent/loop.py`](src/agent/loop.py) |
| 代码边界与校验器 | [`src/domain/scheduling.py`](src/domain/scheduling.py)、[`src/domain/validator.py`](src/domain/validator.py) |
| 测试结果 | [`examples/test-results.txt`](examples/test-results.txt) |
| 补充说明：偏好能改变选择、越权要求不会被执行 | [`examples/instructions-report.json`](examples/instructions-report.json)，说明见 [`docs/03-evaluation.md`](docs/03-evaluation.md) 第 9 节 |
| 演示（补充体验，不替代命令行） | 回放页：<https://lucifer-holly.github.io/xiaoying-agent-campus/demo/>（静态，也可本地双击 [`demo/index.html`](demo/index.html)）；实时演示：<https://xiaoying.gret.me/>，说明见下方“演示” |
| 需求 / 方案 / 评估 / AI 使用 / 复盘 | [`docs/`](docs/) |

## 环境与安装

- Python 3.10 及以上
- 依赖：`openai`（只有 `--llm real` 用到）、`pytest`（测试）

以下命令都在本 README 所在目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

真实模型需要阿里云百炼 API Key；只跑 Mock 和测试时**无需配置**：

```bash
cp .env.example .env
# 编辑 .env，填写 LLM_API_KEY；LLM_BASE_URL、LLM_MODEL 留空时使用默认值
```

| 变量 | 说明 | 默认值 |
|---|---|---|
| `LLM_API_KEY` | 百炼 API Key，空字符串按未配置处理 | 无 |
| `LLM_BASE_URL` | OpenAI 兼容端点 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `LLM_MODEL` | 模型名 | `qwen3.8-max` |
| `LLM_TIMEOUT_S` / `LLM_TEMPERATURE` / `LLM_ENABLE_THINKING` | 超时、温度、是否开启思考模式 | `60` / `0.2` / `false` |

## 运行

离线 Mock（不需要 Key）。**Mock 是一套写死的参考策略，只验证流程（工具、校验器、Trace、触顶），不证明模型的决策效果**：

```bash
python src/main.py --input examples/02-slot-conflict.input.json --llm mock
```

真实模型：

```bash
python src/main.py --input examples/02-slot-conflict.input.json --llm real
```

标准输出是结构化 JSON，标准错误是逐步摘要，Trace 默认写到 `runs/<用例>.<llm>.trace.json`（可用 `--trace-out` 指定）。

其他参数：

```bash
# 步数上限（触顶返回 incomplete_step_limit）
python src/main.py --input examples/01-normal-free-slot.input.json --llm real --max-steps 3
# 防重复（一条命令）：用例 06 自带 options.repeat=2，同一申请在一个进程里连续提交两次
python src/main.py --input examples/06-duplicate-submission.input.json --llm real
# 防重复（跨进程）：草稿库落盘后分两次运行，第二次 created_in_this_run=false，草稿库里仍只有一份
rm -f state/drafts.json
python src/main.py --input examples/06-duplicate-submission.input.json --llm real --store state/drafts.json --repeat 1
python src/main.py --input examples/06-duplicate-submission.input.json --llm real --store state/drafts.json --repeat 1
```

批量录制、稳定性评估、测试：

```bash
python scripts/record_examples.py --llm real      # 重录 examples/ 下全部用例
python scripts/eval_stability.py --runs 3         # 每个用例重复实跑 3 次，写 examples/stability-report.json
python scripts/eval_instructions.py --runs 3      # 补充说明：9 个场景各实跑 3 次，写 examples/instructions-report.json
python -m pytest -v                               # 单元测试 + Mock 流程 + 对已录制真实 Trace 的断言
```

## 用例一览

| 用例 | 场景 | 真实模型的结果 |
|---|---|---|
| `01-normal-free-slot` | 正常排期，18:00 空闲 | `completed`，按申请时间保存 |
| `02-slot-conflict` | M01 申请 18:00 已被占用，日期不能改 | `needs_confirmation`，19:00 待确认草稿 |
| `03-missing-asset-info` | 素材缺文案和封面 | `needs_input`，未保存 |
| `04-rule-risk-block` | 文案含绝对化用语 | `blocked`，未保存 |
| `05-rule-needs-verification` | 音乐授权显示审批中 | 补查版权库通过后 `completed` |
| `06-duplicate-submission` | 同一申请连续提交两次 | 两次都 `completed`，只有一份草稿 |
| `07-save-failure` | 草稿库不可用（故障注入） | 重试一次后 `failed`，`draft=null` |
| `08-step-limit` | 步数上限 3 | `incomplete_step_limit` |
| `09-save-timeout-after-commit` | 保存超时但其实已写入 | 重试命中幂等，`completed`，一份草稿 |
| `10-date-fixed-day-full` | 日期不能改且当天排满 | `needs_confirmation`，不改日期、不保存，询问能否换日期 |

## 输出状态

| status | 含义 |
|---|---|
| `completed` | 已按申请时间保存排期草稿（未发布） |
| `needs_confirmation` | 已保存待确认草稿，或需要申请人同意变更 |
| `needs_input` | 信息缺失，需要申请人补充 |
| `blocked` | 规则风险，已阻断，不排期 |
| `failed` | 工具失败等原因未能完成，草稿以 `draft` 字段为准 |
| `incomplete_step_limit` | 达到步数或工具调用上限，任务未完成 |

不存在“已发布”状态：本 Agent 没有发布能力，草稿需要人工在发布系统确认后才会发布。

## 演示

演示是补充体验，命令行仍是主入口。截图和录屏不能替代代码，评审请以上面的命令和 `examples/` 为准。

- **回放页**：`demo/index.html` 把 `examples/` 里真实模型的每次运行画成可点击的节点图（默认），也可以切换成步骤列表。节点是工具返回的结果，节点之间的说明是模型写下的决策依据（`decision_note`，整段显示）；点节点或说明，旁边显示完整的参数、返回和耗时，“逐步播放”按顺序走一遍。用例列表最后是“两次运行对比”：01 与 02 只差一个日期，图里标出前两步相同、第 3 步工具结果不同、之后两条分支各自的决定；另一组对比提示词 q1-v1 与 q1-v2。在线版：<https://lucifer-holly.github.io/xiaoying-agent-campus/demo/>（GitHub Pages）；本地直接双击打开也可以。数据由 `python scripts/build_demo.py` 从 `examples/` 生成，不做任何修改。
- **在线演示**：<https://xiaoying.gret.me/>。页面与回放页相同，多一个“新建任务”：选一个场景或自己填申请单，还可以在文字框里补充要求（例如“如果 18:00 被占，优先排到 20:00 以后”，最多 300 字），用真实模型现场跑一次，结果同样画成节点图。补充说明作为申请人的偏好交给模型，改变不了代码守住的边界（见 [docs/02 第 8 节](docs/02-solution.md)）。无需口令，按 IP 限流、有每日上限和并发上限，超限时页面给出提示和对应场景的回放入口。每次运行使用独立的内存草稿库，**只保存草稿，不会真实发布**。
- **数据接入**：页面上的“数据接入”列出素材库、发布日历、内容规则、版权库，以及渠道账号、消息通知、发布系统的接入入口。这些入口目前只有说明，没有实现，规划见 [`docs/02-solution.md`](docs/02-solution.md) 第 7 节。
- **本地启动演示服务**：`python src/server.py --port 8710`，然后打开 <http://127.0.0.1:8710/>。`.env` 里配置了 `LLM_API_KEY` 才会开启新建任务，否则只有回放；如需限制访问，可再设置 `DEMO_ACCESS_CODE`，页面会要求输入口令。
- **部署**：`deploy/` 里是 Caddy 站点片段、systemd unit 和服务器 `.env` 模板，`scripts/deploy.sh` 在本机执行，负责同步、装依赖、重启和健康检查，支持 `status` 与 `rollback`。

## 目录结构

```text
q1-asset-scheduling/
├── README.md
├── requirements.txt / requirements-dev.txt
├── .env.example
├── src/            # main.py（命令行）、server.py（演示服务）、agent/（循环、模型、工具注册、Trace）、domain/（业务工具、规则、校验器）
├── tests/          # 工具边界、循环与校验器、用例级验收
├── examples/       # 每个用例的 input / output / trace，test-results.txt，stability-report.json，instructions-report.json，prompt-iterations/
├── data/           # 合成素材、规则、发布日历、版权库
├── scripts/        # 批量录制、稳定性评估、生成回放数据、部署
├── demo/           # 回放页（静态）
├── deploy/         # Caddy 站点片段、systemd unit、服务器 .env 模板
└── docs/           # 01 需求、02 方案、03 评估、04 AI 使用、05 复盘
```

## 安全说明

- 仓库里没有真实密钥：`.env` 已被 `.gitignore` 排除，只提交 `.env.example`。
- 数据全部是合成的，不含真实用户或业务数据。
