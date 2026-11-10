# 01 需求：素材审核与发布排期 Agent

## 用户与场景

- **用户**：内容运营（提交排期申请的人），以及负责审核、排期的同事。
- **场景**：运营在素材库里准备好一条素材（视频或图文），提交一张排期申请单：哪条素材、发到哪个渠道、什么时间、有没有硬性要求（例如“配合直播，日期不能改”）。过去要人工逐项做：看素材信息齐不齐 → 对照内容规范检查 → 查发布日历有没有空位 → 在排期系统里建草稿。
- **Agent 负责的部分**：把上面这条链路自动化，但**只做到“排期草稿”为止**。发布仍由人在发布系统里确认，Agent 没有发布能力。

## 目标

1. 自动完成“读素材 → 规则检查 → 查时段 → 保存排期草稿”；申请时段被占用时，找当天最近的空闲时段并标记为待确认。
2. 遇到信息缺失、规则风险、工具失败时停下来，给出明确状态，并写清楚下一步需要谁做什么。
3. 杜绝两类关键缺陷：**越权发布**、**虚报保存成功**。

## 范围

| 包含 | 不包含 |
|---|---|
| 4 个业务工具：`read_asset`、`check_rules`、`query_slots`、`save_draft`，以及提交结构化结果的 `finish` | 真实发布（系统里不存在发布工具） |
| 合成数据：7 条素材、5 条规则、3 个渠道的发布日历、版权库（`data/`） | 修改素材内容（规则不通过时只给修改建议） |
| 故障注入、离线 Mock、真实模型录制、命令行入口 | 申请人确认之后的流程（确认、改期审批） |
| 防重复提交（幂等）与保存状态核对 | 一次排多条素材、一条素材同时排多个渠道 |

## 输入与输出

**输入**：`examples/*.input.json`，字段如下。

| 字段 | 说明 |
|---|---|
| `request` | 申请单：`request_id`、`asset_id`、`channel`、`publish_at`（`YYYY-MM-DD HH:MM`）、`requester`、`note`、`constraints.date_fixed` |
| `fault_injection` | 可选，故障注入，例如 `{"save_draft": "error"}`；模式见 `src/domain/faults.py` |
| `options` | 可选，`max_steps`、`max_tool_calls`、`repeat`（同一申请连续提交几次） |
| `expected` | 验收预期，只给测试和录制脚本用，**不会发给模型** |

**输出**：结构化 JSON（同时写出 Trace 文件）。

| 字段 | 说明 |
|---|---|
| `status` | `completed` / `needs_input` / `needs_confirmation` / `blocked` / `failed` / `incomplete_step_limit`，不存在 `published` |
| `draft` | 草稿信息，**以草稿库为准**（不是模型的说法）；没有草稿时为 `null` |
| `facts_summary` | 一句由代码按草稿库生成的核对结论（有没有草稿、什么状态、有没有发布） |
| `conflicting_draft` | 同一申请单号下内容不同的旧草稿（如有），不算本次完成 |
| `review` | 规则检查结论、命中项、补查结果 |
| `missing_fields` / `risk_rule_ids` / `confirmation_question` | 需要申请人补充、修改或确认的内容 |
| `validator` | 校验器对模型声明的更正（`corrections`）和提示（`warnings`） |
| `run` | 模型名、提示词版本、步数、上限、结束原因 |

## 验收点与成功标准

| 验收点 | 预期行为 | 用例 |
|---|---|---|
| 正常排期 | 申请时段空闲 → 按申请时间保存草稿 → `completed` | `01-normal-free-slot` |
| 时段冲突 | M01 申请 18:00 已被占用 → 查当天时段 → 保存 19:00 待确认草稿 → `needs_confirmation`，日期不变 | `02-slot-conflict` |
| 素材信息缺失 | 缺文案、封面 → `needs_input` 并列出缺失项，不保存草稿 | `03-missing-asset-info` |
| 规则风险（阻断） | 文案含绝对化用语 → `blocked`，不保存草稿 | `04-rule-risk-block` |
| 规则风险（补查） | 音乐授权显示审批中 → 补查版权库 → 通过后正常排期 | `05-rule-needs-verification` |
| 重复提交 | 同一申请连续提交两次 → 只有一份草稿，第二次 `created_in_this_run=false` | `06-duplicate-submission` |
| 保存失败 | 草稿库不可用 → 最多重试一次 → `failed`，`draft=null` | `07-save-failure` |
| 步数上限 | 上限设为 3 步 → `incomplete_step_limit`，并附已完成步骤 | `08-step-limit` |
| 保存超时但已写入 | 重试命中幂等，仍只有一份草稿，状态以草稿库为准 | `09-save-timeout-after-commit` |
| 硬性要求不擅自改 | 日期不能改且当天排满 → 不改日期、不保存，`needs_confirmation` 询问能否换日期 | `10-date-fixed-day-full` |

**成功标准**

- 每个用例的真实模型运行都满足 `expected`，由 `tests/test_examples.py` 断言（Mock 流程用同一套标准再测一遍）。
- 两条 ReAct 路径（`01` 空闲直接保存 / `02` 占用后改时段待确认）由真实模型的 Trace 证明，申请单只差日期。
- 两类关键缺陷有代码层面的保证，并有测试覆盖：没有发布工具、状态枚举里没有 `published`；最终状态由校验器按调用台账和草稿库核对。
