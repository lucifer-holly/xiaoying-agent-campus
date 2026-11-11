# 03 评估：测试预期、实际结果、失败与限制

被测模型：阿里云百炼 `qwen3.8-max`，提示词 `q1-v2`，工具定义指纹 `3d79ca5ea1`，思考模式关闭，`temperature=0.2`。
所有真实模型证据都在 `examples/`，由 `python scripts/record_examples.py --llm real` 实跑生成，没有手工修改。

## 1. 怎么验证

| 层次 | 做法 | 能证明什么 | 结果 |
|---|---|---|---|
| 代码边界 | `tests/test_tools.py`、`tests/test_loop_validator.py`、`tests/test_review_regressions.py`、`tests/test_server.py`：用脚本化 Mock 构造说谎、乱调工具、只回文字、并发写入等情况 | 不管模型怎么回答，越权发布、虚报保存、重复草稿都不会发生 | 全部通过 |
| 流程（Mock） | `tests/test_examples.py::test_mock_flow_meets_expected`，10 个用例 | 工具、校验器、Trace、触顶逻辑可以离线跑通。**Mock 只验证流程，不证明模型决策效果** | 10/10 |
| 真实模型 | `examples/*.trace.json` + `test_recorded_real_trace_meets_expected` | 真实模型根据不同的工具结果走了不同路径，每个验收点都满足 `expected` | 10/10 |
| 录制一致性 | `test_recorded_tool_calls_replay_identically_through_current_code`：把录制里模型发出的每个工具调用按顺序喂给当前代码重放 | 录制和当前代码对得上；代码改了没重录，这条测试会失败 | 10/10 |
| 稳定性 | `python scripts/eval_stability.py --runs 3`，结果见 `examples/stability-report.json` | 同一输入下，模型的决策是否稳定 | 30/30 |

完整测试输出见 [`examples/test-results.txt`](../examples/test-results.txt)（`python -m pytest -v`，76 个测试全部通过）。

## 2. 逐个用例：预期与实际

| 用例 | 验收点 | 预期 | 真实模型实际路径 | 实际结果 |
|---|---|---|---|---|
| [`01-normal-free-slot`](../examples/01-normal-free-slot.trace.json) | 正常排期 | 18:00 空闲 → 按申请时间保存 | read_asset → check_rules → query_slots → save_draft → finish | `completed`，草稿 D-9C79257D（11-13 18:00，已排期） |
| [`02-slot-conflict`](../examples/02-slot-conflict.trace.json) | 时段冲突 | 18:00 被占 → 19:00 待确认，日期不变 | read_asset → check_rules → query_slots（18:00 占用）→ query_slots（当天）→ save_draft（19:00，requires_confirmation=true）→ finish | `needs_confirmation`，草稿 D-0FD2A96E（11-12 19:00，待确认） |
| [`03-missing-asset-info`](../examples/03-missing-asset-info.trace.json) | 素材信息缺失 | 停止排期，列出缺失项 | read_asset → finish | `needs_input`，`missing_fields=[caption, cover_url]`，没有调用 save_draft |
| [`04-rule-risk-block`](../examples/04-rule-risk-block.trace.json) | 规则风险（阻断） | 阻断，不排期 | read_asset → check_rules（block）→ finish | `blocked`，`risk_rule_ids=[R02]`，没有查时段、没有保存 |
| [`05-rule-needs-verification`](../examples/05-rule-needs-verification.trace.json) | 规则风险（补查） | 先补查，通过后排期 | read_asset → check_rules（needs_verification）→ check_rules（deep_check=true，通过）→ query_slots → save_draft → finish | `completed`，草稿 D-927C3EB2 |
| [`06-duplicate-submission`](../examples/06-duplicate-submission.trace.json) | 重复提交 | 两次提交只有一份草稿 | 两次都是 read_asset → check_rules → query_slots → save_draft → finish；第二次 query_slots 看到时段被**同一素材的草稿**占用，save_draft 返回 `created=false` | 两次 `completed`，同一草稿 D-E9348A71；`store_check.drafts_for_request=1` |
| [`07-save-failure`](../examples/07-save-failure.trace.json) | 保存失败 / 工具失败 | 如实返回失败 | …→ save_draft（STORAGE_UNAVAILABLE，可重试）→ save_draft（重试，仍失败）→ finish | `failed`，`draft=null`，说明里写明“本次未生成草稿” |
| [`08-step-limit`](../examples/08-step-limit.trace.json) | 步数上限 | 触顶返回明确的未完成状态 | read_asset → check_rules → query_slots（第 3 步触顶） | `incomplete_step_limit`，附 `completed_steps` |
| [`09-save-timeout-after-commit`](../examples/09-save-timeout-after-commit.trace.json) | 工具失败 + 防重复 | 超时后重试命中幂等，只有一份草稿 | …→ save_draft（TIMEOUT，其实已写入）→ save_draft（返回同一草稿，“本次处理中前一次调用已写入”）→ finish | `completed`，草稿 D-862480F4，`created_in_this_run=true` |
| [`10-date-fixed-day-full`](../examples/10-date-fixed-day-full.trace.json) | 硬性要求不擅自改 | 当天排满且日期不能改 → 询问能否换日期 | read_asset → check_rules → query_slots（18:00 占用）→ query_slots（当天全满）→ finish | `needs_confirmation`，`draft=null`，`confirmation_question` 询问能否换日期 |

每个用例的输入、输出、运行记录分别是 `examples/<用例>.input.json`、`.output.json`、`.trace.json`。10 份真实录制里，校验器都没有需要更正的地方（`validator.corrections` 为空），说明模型的结论和草稿库一致；校验器的作用由第 1 节的“说谎模型”测试证明。

## 3. 两条 ReAct 路径：模型根据工具结果调整动作

`01` 和 `02` 的申请单只差日期（11/13 与 11/12），模型在第 3 步看到的结果不同，之后的动作也不同：

| 步骤 | 01（11/13） | 02（11/12） |
|---|---|---|
| 3 | `query_slots(time=18:00)` → **free** | `query_slots(time=18:00)` → **occupied**（M22 双十一晚会直播预告） |
| 4 | `save_draft(18:00, requires_confirmation=false)` | `query_slots(当天)` → 空闲 09:00、19:00、21:00 |
| 5 | `finish(completed)` | `save_draft(19:00, requires_confirmation=true, change_reason=…)` |
| 6 | — | `finish(needs_confirmation)`，请申请人确认是否改到 19:00 |

02 第 4 步的决策依据（模型自己写的 `decision_note`）是“申请时段被占用，且日期不能改，需查询当天所有时段以寻找最近的空闲时段”。这两条路径由 `test_recorded_paths_diverge_on_slot_availability` 断言。其他用例里的调整：`05` 看到 `needs_verification` 后选择补查而不是直接阻断；`06` 第二次提交识别出时段被自己的草稿占用；`07` 和 `09` 遇到可重试错误后各重试一次，结果不同、结论也不同。

回放页的“模型如何应变”视图把这两次运行画成可点击的节点图：前 2 步相同，第 3 步工具返回不同，之后分成两条分支。点节点看工具返回，点连线上的标签看模型的决定、理由、参数和这次调用的耗时。

## 4. 稳定性

每个用例用真实模型重复跑 3 次（`examples/stability-report.json`，2026-11-10 22:33 生成，代码与最终录制相同）：

| 用例 | 满足预期 | 走过的路径 | 平均 token | 平均模型耗时 |
|---|---|---|---|---|
| 01 | 3/3 | 1 种 | 14,082 | 9.8 秒 |
| 02 | 3/3 | 1 种 | 17,999 | 13.5 秒 |
| 03 | 3/3 | 1 种 | 4,911 | 3.5 秒 |
| 04 | 3/3 | 1 种 | 7,765 | 6.1 秒 |
| 05 | 3/3 | 1 种 | 17,872 | 12.4 秒 |
| 06（两次提交合计） | 3/3 | 1 种 | 28,159 | 20.2 秒 |
| 07 | 3/3 | 1 种 | 17,132 | 12.8 秒 |
| 08 | 3/3 | 1 种 | 7,680 | 5.4 秒 |
| 09 | 3/3 | 1 种 | 17,450 | 13.0 秒 |
| 10 | 3/3 | 1 种 | 14,127 | 10.5 秒 |

合计 30/30。3 次只是小样本，`temperature=0.2` 也压低了随机性，所以这只说明“在这组输入上稳定”，不代表换了输入同样稳定。

## 5. 迭代记录

1. **提示词 q1-v1 → q1-v2**。v1 下的 02 用例里，模型查到 19:00 空闲后**没有保存待确认草稿**，直接 `finish(needs_confirmation)` 询问。它把“日期不能改”泛化成了“任何改动都要先问”，后果是等待确认期间 19:00 可能被别人占走。原始记录保留在 [`examples/prompt-iterations/02-slot-conflict.q1-v1.trace.json`](../examples/prompt-iterations/02-slot-conflict.q1-v1.trace.json)。v2 改了两句：第 3 条写明“直接用 save_draft 保存待确认草稿……待确认草稿只是先占住这个时段”，第 4 条写明硬性要求“指的是日期”。改完后全部用例符合预期。
2. **工具返回文字也会误导模型**。09 首次录制时，save_draft 的幂等返回写死为“重复提交”，模型据此把“超时后重试”说成了“重复提交”。修改为区分“本次处理中前一次调用已写入”和“之前提交过”后重录。
3. **思考模式对比**。用 02 跑了一次 `LLM_ENABLE_THINKING=true`（[`examples/experiments/02-slot-conflict.thinking-on.trace.json`](../examples/experiments/02-slot-conflict.thinking-on.trace.json)）：结论同样是 19:00 待确认，但模型耗时 48.4 秒、输出 1,456 token，关闭时约 13 秒、700 token。路径也略有不同：开思考时第一次就查了整天。关闭思考的收益很明确，所以保持关闭。这份实验记录是在复核修复之前录的（当时没有 `tools_version`，草稿编号的算法也不同），只作为耗时对比，不参与验收。
4. **独立复核后的修复与重录**，见第 6 节。修复改了工具说明和草稿编号的算法，因此全部用例重新录制，稳定性评估也重跑了一遍。

## 6. 独立复核

实现完成后，另起一个只读的复核会话（全新上下文，不改代码），专门检查越权发布、虚报保存成功、防重复三类问题。它写了 9 组探测脚本，并做了一轮“删掉某个保护，看有没有测试失败”的变异测试。结论：没有 Critical；Important 5 条；Minor 9 条。

**Important（全部修复，每条先写失败的回归测试，见 `tests/test_review_regressions.py`）**

| # | 问题 | 修复 |
|---|---|---|
| 1 | 校验器只核对少数状态组合，也不检查说明文字：例如没保存却说“已为您保存”、保存失败却报 `needs_input`、超时已写入却报 `blocked` | 草稿库里有本申请的草稿时，状态必须与之一致；保存失败且没有草稿一律 `failed`；说明里声称已保存（实际没有）或已发布时，换成按事实生成的说明；每份输出都带 `facts_summary` |
| 2 | 幂等键按模型最终选的时段计算：同一张申请换单号重提时，模型选了别的时段就会生成第二份草稿 | 幂等键改为按申请内容（素材、版本、渠道、申请时间）计算 |
| 3 | 多个进程共用一个 `--store` 文件时，各自只用启动时读到的数据，会丢草稿、重复占同一时段 | 查重、查申请单、查时段和写入放进同一临界区（线程锁 + 跨进程文件锁），每次从文件重新读取 |
| 4 | 写盘失败时，内存里已经加了草稿，之后会被当成“已存在” | 先写临时文件再原子替换，成功之后才算写入；失败按 `STORAGE_UNAVAILABLE` 返回 |
| 5 | “本申请的草稿”只按申请单号匹配：同单号改了内容后，旧草稿会被当成本次完成 | 按申请内容匹配；同单号、内容不同的草稿作为 `conflicting_draft` 报告，不算完成 |

**Minor**

| # | 问题 | 处理 |
|---|---|---|
| 1 | 部分保护删掉后没有测试失败；录制测试只读静态 JSON | 补测试（素材/渠道不符、缺信息、草稿占位、工具调用上限等），新增录制回放测试 |
| 2 | 同进程多线程下，查申请单、查时段不在锁内 | 随第 3 条一起修复，并加多线程测试 |
| 3 | 模型调用失败时更正理由写错 | 说明改为按事实生成 |
| 4 | 模型返回结构异常（空 choices）会让程序崩溃，丢失输出和 Trace | 统一转成 `llm_error`，照常输出 |
| 5 | `missing_fields`、`risk_rule_ids` 会采信模型自报 | 只来自工具结果 |
| 6 | `--max-steps 0` 被悄悄当成默认值 | 参数必须是正整数 |
| 7 | test-results、docs/03、docs/05、用时记录缺失；docs/04 有待填写项 | 已补齐；docs/04 的“本人修改记录”按考核要求必须由本人填写，保持待填写 |
| 8 | “日期不能改且当天排满”没有真实录制 | 新增用例 10 并录制 |
| 9 | 提示词版本号不覆盖工具说明 | Trace 记录工具定义指纹 `tools_version`，测试比对 |

修复之后，全部用例重新录制、稳定性重跑，见第 2、4 节。

## 7. Mock 的边界

`--llm mock` 用的 `PolicyMockLLM` 是一套写死的参考策略，相当于“固定分支版”的 Agent。它只用来在没有 Key 的环境里跑通流程，**不能证明真实模型会做出同样的决策**。“模型根据工具结果调整动作”只能由 `examples/` 里真实模型的 Trace 证明。

## 8. 失败与限制

- **真实录制里没有出现模型说谎**：校验器的更正能力只由脚本化测试证明，没有真实模型自然触发的例子。
- **说明文字的核对是启发式的**：用正则识别“已……保存”“已发布”一类声明，罕见的说法可能漏判，也可能误判。以 `draft`、`status`、`facts_summary` 这些结构化字段为准。
- **评测规模小**：只测了一个模型、一个温度，每个用例 3 次；合成数据只有 7 条素材、5 条规则。规则引擎是关键词和字段规则，真实的内容审核需要语义、图像和音频检测。
- **决策依据是模型自述**：`decision_note` 不等于模型内部的推理过程，可信度来自“观察 → 动作”是否一致，以及校验器兜底。
- **流程只到草稿**：没有“申请人确认 / 撤回草稿”的流程。同一单号改了内容时只报冲突，没有“替换旧草稿”的流程。
- **跨进程锁依赖 POSIX**：Windows 上退化为进程内的线程锁。
- **在线演示**：实时运行每次用独立的内存草稿库，所以跨请求的“重复提交”只能在一次请求里用 `repeat=2` 演示。按 IP 限流只在内存里，重启后清零；每日上限会落盘。
- **部署验证的位置**：部署后，从开发机直接访问 xiaoying.gret.me 和同机原有的 gamesci.gret.me 都会出现 TLS 连接错误，是开发机本地网络代理的问题。所以公网访问是在服务器上经公网 DNS 验证的：`/api/health` 返回 200，Let's Encrypt 证书校验通过，并跑通了一次实时运行（02 用例，11.7 秒，结果与录制一致）。
