/* 回放页：读取 data/replay.js（由 scripts/build_demo.py 从 examples/ 生成），逐步展示真实模型的 Trace。
 * 部署在演示服务上时 /api/health 可用，页面会多出“实时运行”。
 * 模型和接口返回的文字一律用 textContent 写入，不会被当成 HTML；innerHTML 只用于下面固定的图标。 */
(function () {
  "use strict";

  var DATA = window.Q1_REPLAY || { cases: [], iterations: [] };
  var STATUS = {
    completed: { label: "已保存排期草稿", short: "已保存草稿", tone: "ok", icon: "check" },
    needs_confirmation: { label: "等待申请人确认", short: "待确认", tone: "warn", icon: "clock" },
    needs_input: { label: "需要补充信息", short: "需补充信息", tone: "info", icon: "edit" },
    blocked: { label: "规则风险，已阻断", short: "规则阻断", tone: "bad", icon: "shieldX" },
    failed: { label: "未完成（失败）", short: "失败", tone: "bad", icon: "x" },
    incomplete_step_limit: { label: "未完成（达到步数上限）", short: "触顶未完成", tone: "muted", icon: "pause" }
  };
  var TOOLS = {
    read_asset: { label: "读取素材", icon: "file" },
    check_rules: { label: "规则检查", icon: "shield" },
    query_slots: { label: "查询时段", icon: "calendar" },
    save_draft: { label: "保存草稿", icon: "save" },
    finish: { label: "提交结果", icon: "flag" }
  };
  var CHANNEL = { douyin: "抖音", wechat_channels: "视频号", xiaohongshu: "小红书" };
  var DRAFT_STATUS = { scheduled_draft: "已排期草稿（未发布）", pending_confirmation: "待确认草稿（未发布）" };
  var COMPARE_PAIRS = [
    { a: "01-normal-free-slot", b: "02-slot-conflict", note: "两张申请单只差日期（11/13 与 11/12）。第 3 步查到的 18:00 状态不同，模型此后走了不同的路径。" },
    { a: "02-slot-conflict.q1-v1", b: "02-slot-conflict", note: "同一用例、两版提示词。q1-v1 下模型找到 19:00 后没有先保存待确认草稿，等待确认期间时段可能被占；q1-v2 明确了“待确认草稿只是先占位”。" }
  ];
  var ICONS = {
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    shield: '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    shieldX: '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M10 10l4 4M14 10l-4 4"/>',
    calendar: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/><path d="M9 14h2v2H9z"/>',
    calendarCheck: '<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M8 3v4M16 3v4M4 10h16"/><path d="M9 15l2 2 4-4"/>',
    save: '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/><rect x="8" y="13" width="8" height="5" rx="1"/>',
    flag: '<path d="M5 21V4"/><path d="M5 4h11l-2 4 2 4H5"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    pause: '<circle cx="12" cy="12" r="8.5"/><path d="M10 9v6M14 9v6"/>',
    spark: '<path d="M12 3l1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7-4.7-1.8 4.7-1.8z"/><path d="M18.5 15l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
    alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.5"/>',
    lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1-3.5 3.8-5.5 7-5.5s6 2 7 5.5"/>',
    note: '<path d="M5 5h14v10l-4 4H5z"/><path d="M15 19v-4h4"/>',
    channel: '<path d="M4 18a10 10 0 0 1 16 0"/><path d="M8 18a5.5 5.5 0 0 1 8 0"/><circle cx="12" cy="18" r="1"/>',
    play: '<path d="M8 5l11 7-11 7z"/>',
    bolt: '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    repeat: '<path d="M4 12a8 8 0 0 1 13.7-5.7L20 8"/><path d="M20 4v4h-4"/><path d="M20 12a8 8 0 0 1-13.7 5.7L4 16"/><path d="M4 20v-4h4"/>',
    list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
    timer: '<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 1.5M9.5 3h5"/>',
    compare: '<rect x="3" y="4" width="7" height="16" rx="1.5"/><rect x="14" y="4" width="7" height="16" rx="1.5"/>',
    expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>'
  };
  var timers = [];

  // ---- 小工具 ----------------------------------------------------------------
  function icon(name, cls) {
    var span = document.createElement("span");
    span.className = "icon" + (cls ? " " + cls : "");
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || "") + "</svg>";
    return span;
  }
  function el(tag, props) {
    var node = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        var v = props[k];
        if (v === undefined || v === null || v === false) return;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k.indexOf("on") === 0) node.addEventListener(k.slice(2), v);
        else if (v === true) node.setAttribute(k, "");
        else node.setAttribute(k, v);
      });
    }
    for (var i = 2; i < arguments.length; i++) append(node, arguments[i]);
    return node;
  }
  function append(node, kid) {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { append(node, k); }); return; }
    node.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  function runsOf(doc) { return doc && doc.runs ? doc.runs : [doc]; }
  function lastStatus(entry) { var outs = runsOf(entry.output); return outs[outs.length - 1].status; }
  function statusOf(status) { return STATUS[status] || { label: status, short: status, tone: "muted", icon: "pause" }; }
  function pill(status) {
    var s = statusOf(status);
    return el("span", { class: "pill tone-" + s.tone }, icon(s.icon), s.short);
  }
  function fmt(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "object") return JSON.stringify(value);
    if (value === true) return "是";
    if (value === false) return "否";
    return String(value);
  }
  function raw(value) { return typeof value === "string" ? value : JSON.stringify(value); }  // 工具参数原样显示
  function findCase(id) {
    var all = DATA.cases.concat(DATA.iterations || []);
    for (var i = 0; i < all.length; i++) if (all[i].case === id) return all[i];
    return null;
  }
  function caseNo(entry) { var m = /^(\d+)/.exec(entry.case || ""); return m ? m[1] : "·"; }
  function splitTitle(entry) {
    var t = entry.title || entry.case;
    var i = t.indexOf("：");
    return i > 0 ? [t.slice(0, i), t.slice(i + 1)] : [t, ""];
  }
  function clearTimers() { timers.forEach(clearTimeout); timers = []; }

  // ---- 顶部指标与工作方式 ----------------------------------------------------
  function renderStats() {
    var items = [
      ["模型", DATA.model || "—", "阿里云百炼 · OpenAI 兼容接口 · 关闭思考模式"],
      ["技术路线", "ReAct 循环 + Function Calling", "Python 3.10+，只依赖 openai SDK，不用 Agent 框架；硬约束写在工具层和输出校验器里"],
      ["验收用例", DATA.cases.length + " 个，均为真实模型录制", "正常排期、信息不全、规则风险、时段冲突、工具失败、重复提交、步数上限"]
    ];
    var box = document.getElementById("stats");
    box.replaceChildren.apply(box, items.map(function (it) {
      return el("li", null, el("span", { class: "stat-label", text: it[0] }), el("span", { class: "stat-value", text: it[1] }), el("span", { class: "stat-sub", text: it[2] }));
    }));
    document.getElementById("brand-mark").appendChild(icon("calendarCheck"));
  }
  function renderPipeline() {
    var flow = el("ol", { class: "flow" }, ["read_asset", "check_rules", "query_slots", "save_draft", "finish"].map(function (t) {
      return el("li", { class: "flow-step tool-" + t }, icon(TOOLS[t].icon, "flow-icon"),
        el("span", { class: "flow-text" }, el("span", { class: "flow-cn", text: TOOLS[t].label }), el("code", { class: "flow-en", text: t })));
    }));
    var guards = ["没有发布工具，只保存草稿", "先通过规则检查才能保存", "改时间一律标记待确认", "日期硬约束不擅自改", "按申请内容幂等，防重复", "最终状态以草稿库为准"];
    document.getElementById("pipeline").appendChild(el("div", { class: "pipeline-card" },
      el("div", { class: "pipeline-head" },
        el("h2", { text: "模型做决策，代码守边界" }),
        el("p", { class: "muted small", text: "每一步由模型根据上一步的工具结果决定；下面这些约束由代码强制执行，不依赖模型自觉。" })),
      flow,
      el("ul", { class: "guards" }, guards.map(function (g) { return el("li", null, icon("shield"), g); }))
    ));
  }

  // ---- 申请单 -----------------------------------------------------------------
  function renderRequest(req, faults, options) {
    var fields = [
      ["file", "素材", req.asset_id],
      ["channel", "渠道", CHANNEL[req.channel] ? CHANNEL[req.channel] + " · " + req.channel : req.channel],
      ["calendar", "申请发布时间", req.publish_at],
      ["lock", "日期不能改", req.constraints && req.constraints.date_fixed ? "是" : "否"],
      ["user", "申请人", req.requester]
    ];
    var tiles = fields.filter(function (f) { return f[2]; }).map(function (f) {
      return el("div", { class: "field-tile" }, icon(f[0]), el("div", null, el("div", { class: "field-label", text: f[1] }), el("div", { class: "field-value", text: fmt(f[2]) })));
    });
    if (req.note) tiles.push(el("div", { class: "field-tile field-wide" }, icon("note"), el("div", null, el("div", { class: "field-label", text: "备注" }), el("div", { class: "field-value", text: req.note }))));
    var tags = [];
    Object.keys(faults || {}).forEach(function (tool) {
      tags.push(el("span", { class: "tag tag-fault" }, icon("alert"), "故障注入：" + tool + " = " + faults[tool]));
    });
    if (options && options.repeat > 1) tags.push(el("span", { class: "tag tag-brand" }, icon("repeat"), "同一申请连续提交 " + options.repeat + " 次（共用草稿库）"));
    if (options && options.max_steps) tags.push(el("span", { class: "tag" }, icon("list"), "步数上限 " + options.max_steps));
    return el("section", { class: "card request" },
      el("h3", { class: "card-title" }, icon("file"), "排期申请单", el("code", { class: "muted small", text: req.request_id || "" })),
      el("div", { class: "fields" }, tiles),
      tags.length ? el("div", { class: "tags" }, tags) : null
    );
  }

  // ---- 步骤 -------------------------------------------------------------------
  function pick(obj, keys) {
    var out = {};
    keys.forEach(function (k) { if (obj && obj[k] !== undefined) out[k] = obj[k]; });
    return out;
  }
  function renderArgs(args) {
    var keys = Object.keys(args || {}).filter(function (k) { return k !== "message"; });
    if (!keys.length) return null;
    return el("div", { class: "args" }, keys.map(function (k) { return el("code", { text: k + " = " + raw(args[k]) }); }));
  }
  function renderStep(step) {
    var meta = TOOLS[step.tool] || { label: "没有调用工具", icon: "pause" };
    var latency = step.llm && step.llm.latency_ms ? (step.llm.latency_ms / 1000).toFixed(1) + " 秒" : null;
    var args = step.tool === "finish" ? pick(step.args, ["status", "draft_id", "publish_at", "risk_rule_ids", "missing_fields"]) : step.args;
    return el("li", { class: "step tool-" + (step.tool || "none") + (step.ok ? "" : " failed") },
      el("div", { class: "step-rail" }, el("span", { class: "step-dot", text: String(step.step) })),
      el("div", { class: "step-card" },
        el("div", { class: "step-head" },
          icon(meta.icon, "tool-icon"),
          el("span", { class: "tool-names" }, el("span", { class: "tool-cn", text: meta.label }), el("code", { class: "tool-en", text: step.tool || "—" })),
          el("span", { class: "pill " + (step.ok ? "tone-ok" : "tone-bad") }, icon(step.ok ? "check" : "x"), step.ok ? "成功" : "失败"),
          latency ? el("span", { class: "latency", title: "这一步模型调用耗时" }, icon("timer"), latency) : null
        ),
        renderArgs(args),
        step.decision_note ? el("div", { class: "note" }, el("span", { class: "note-label" }, icon("spark"), "模型的决策依据"), el("p", { text: step.decision_note })) : null,
        el("div", { class: "result" }, el("span", { class: "result-label" }, icon("list"), "返回摘要"), el("p", { text: step.result_summary })),
        step.next_action ? el("span", { class: "next" }, icon("arrow"), "下一步：" + step.next_action) : null,
        step.observation ? el("details", null,
          el("summary", { text: step.tool === "finish" ? "校验器结果" : "模型看到的完整返回" }),
          el("pre", { text: JSON.stringify(step.observation, null, 2) })) : null
      )
    );
  }

  // ---- 最终输出 -----------------------------------------------------------------
  function renderFinal(out, trace) {
    var s = statusOf(out.status);
    var d = out.draft;
    var ticket = null;
    if (d) {
      var tiles = [
        ["save", "草稿编号", d.draft_id + (d.created_in_this_run ? "（本次新建）" : "（已存在，未新建）")],
        ["shield", "草稿状态", DRAFT_STATUS[d.status] || d.status],
        ["channel", "渠道", CHANNEL[d.channel] || d.channel],
        ["calendar", "发布时间", d.publish_at + (d.requested_publish_at && d.requested_publish_at !== d.publish_at ? "（申请 " + d.requested_publish_at + "）" : "")]
      ];
      if (d.change_reason) tiles.push(["note", "调整原因", d.change_reason]);
      ticket = el("div", { class: "ticket" }, tiles.map(function (t) {
        return el("div", { class: "field-tile" + (t[0] === "note" ? " field-wide" : "") }, icon(t[0]), el("div", null, el("div", { class: "field-label", text: t[1] }), el("div", { class: "field-value", text: t[2] })));
      }));
    }
    var rows = [];
    if (out.review) rows.push(["规则结论", out.review.verdict + (out.review.deep_check ? "（已补查版权库）" : "")]);
    if (out.missing_fields && out.missing_fields.length) rows.push(["缺失信息", out.missing_fields.join("、")]);
    if (out.risk_rule_ids && out.risk_rule_ids.length) rows.push(["命中规则", out.risk_rule_ids.join("、")]);
    if (out.confirmation_question) rows.push(["待确认问题", out.confirmation_question]);
    var corrections = (out.validator && out.validator.corrections) || [];
    var warnings = (out.validator && out.validator.warnings) || [];
    var run = out.run || {};
    var usage = trace && trace.llm_usage;
    var meta = ["模型 " + (run.model || "—"), "提示词 " + (run.prompt_version || "—"), "用了 " + run.steps_used + " 步 / 上限 " + run.max_steps, "结束原因 " + run.end_reason];
    if (usage && usage.calls) meta.push("模型耗时 " + (usage.latency_ms / 1000).toFixed(1) + " 秒", "tokens " + usage.prompt_tokens + " + " + usage.completion_tokens);
    return el("section", { class: "card final" },
      el("div", { class: "final-band tone-" + s.tone },
        icon(s.icon, "final-icon"),
        el("div", null, el("p", { class: "final-kicker", text: "最终输出" }), el("h3", { text: s.label })),
        el("code", { class: "final-code", text: out.status })
      ),
      el("div", { class: "final-body" },
        el("p", { class: "message", text: out.message }),
        out.facts_summary ? el("div", { class: "facts" }, icon("shield"), el("div", null, el("p", { class: "facts-label", text: "系统核对（由代码按草稿库生成，不采信模型的说法）" }), el("p", { text: out.facts_summary }))) : null,
        ticket,
        rows.length ? el("dl", { class: "kv" }, rows.map(function (r) { return [el("dt", { text: r[0] }), el("dd", { text: r[1] })]; })) : null,
        corrections.length ? el("div", { class: "corrections" },
          el("h4", { text: "校验器更正" }),
          el("ul", null, corrections.map(function (c) { return el("li", { text: fmt(c.from) + " → " + fmt(c.to) + "：" + c.reason }); }))) :
          el("p", { class: "validator-ok" }, icon("check"), "校验器：模型的结论与草稿库一致，无需更正"),
        warnings.length ? el("ul", { class: "warnings" }, warnings.map(function (w) { return el("li", { text: w }); })) : null,
        el("div", { class: "run-meta" }, meta.map(function (m) { return el("span", { text: m }); }))
      )
    );
  }

  // ---- 一个用例 -------------------------------------------------------------------
  function renderRun(trace, out, animate) {
    var list = el("ol", { class: "timeline" });
    var finalBox = el("div");
    var steps = trace.steps || [];
    function show(i) {
      if (i < steps.length) {
        list.appendChild(renderStep(steps[i]));
        if (animate) timers.push(setTimeout(function () { show(i + 1); }, 650));
        else show(i + 1);
      } else {
        finalBox.appendChild(renderFinal(out, trace));
      }
    }
    show(0);
    return el("div", { class: "run" }, list, finalBox);
  }
  function renderEntry(entry, opts) {
    opts = opts || {};
    clearTimers();
    var traces = runsOf(entry.trace);
    var outs = runsOf(entry.output);
    var title = splitTitle(entry);
    var body = el("div");
    var head = el("header", { class: "detail-head" },
      el("div", null,
        el("p", { class: "detail-kicker" }, el("span", { class: "case-no", text: caseNo(entry) }), el("code", { text: entry.case })),
        el("h2", { text: title[0] }),
        title[1] ? el("p", { class: "detail-desc", text: title[1] }) : null,
        entry.covers && entry.covers.length ? el("div", { class: "tags" }, entry.covers.map(function (c) { return el("span", { class: "tag tag-brand", text: c }); })) : null
      ),
      el("div", { class: "actions" },
        el("button", { type: "button", class: "btn", onclick: function () { renderInto(entry, true); } }, icon("play"), "逐步播放"),
        el("button", { type: "button", class: "btn btn-ghost", onclick: function () { toggleDetails(body); } }, icon("expand"), "展开 / 收起返回")
      )
    );
    var parts = [head, renderRequest(entry.request, entry.fault_injection, entry.options)];
    if (traces.length > 1) {
      var tabs = el("div", { class: "run-tabs", role: "tablist" });
      var holder = el("div");
      traces.forEach(function (t, i) {
        tabs.appendChild(el("button", {
          type: "button", role: "tab", "aria-selected": i === 0 ? "true" : "false",
          text: "第 " + (i + 1) + " 次提交 · " + statusOf(outs[i].status).short,
          onclick: function (ev) {
            Array.prototype.forEach.call(tabs.children, function (b) { b.setAttribute("aria-selected", "false"); });
            ev.currentTarget.setAttribute("aria-selected", "true");
            clearTimers();
            holder.replaceChildren(renderRun(traces[i], outs[i], false));
          }
        }));
      });
      holder.appendChild(renderRun(traces[0], outs[0], opts.animate));
      var sc = entry.output.store_check;
      parts.push(tabs);
      if (sc) parts.push(el("p", { class: "store-check" }, icon("shield"), "草稿库核对：申请 " + sc.request_id + " 共 " + sc.drafts_for_request + " 份草稿（" + sc.draft_ids.join("、") + "），草稿库合计 " + sc.total_drafts_in_store + " 份。"));
      parts.push(holder);
    } else {
      parts.push(renderRun(traces[0], outs[0], opts.animate));
    }
    append(body, parts);
    return body;
  }
  function toggleDetails(root) {
    var all = root.querySelectorAll("details");
    var open = !Array.prototype.some.call(all, function (d) { return d.open; });
    Array.prototype.forEach.call(all, function (d) { d.open = open; });
  }
  function renderInto(entry, animate) {
    document.getElementById("case-detail").replaceChildren(renderEntry(entry, { animate: animate }));
  }

  // ---- 回放视图 -----------------------------------------------------------------
  function renderCaseList(activeId) {
    var box = document.getElementById("case-list");
    box.replaceChildren();
    function item(entry, extraClass) {
      var title = splitTitle(entry);
      return el("button", {
        type: "button", class: "case-item" + (entry.case === activeId ? " active" : "") + (extraClass || ""),
        "aria-current": entry.case === activeId ? "true" : null,
        onclick: function () { selectCase(entry.case); }
      },
        el("span", { class: "case-no", text: caseNo(entry) }),
        el("span", { class: "case-name", text: title[0] }),
        el("span", { class: "case-meta" }, pill(lastStatus(entry)), el("span", { class: "case-desc", text: title[1] }))
      );
    }
    box.appendChild(el("h2", { class: "list-title", text: "验收用例 · " + DATA.cases.length }));
    DATA.cases.forEach(function (c) { box.appendChild(item(c)); });
    if (DATA.iterations && DATA.iterations.length) {
      box.appendChild(el("h2", { class: "list-title", text: "提示词迭代记录" }));
      DATA.iterations.forEach(function (c) { box.appendChild(item(c, " iteration")); });
    }
  }
  function selectCase(id, keepView) {
    var entry = findCase(id) || DATA.cases[0];
    if (!entry) return;
    renderCaseList(entry.case);
    renderInto(entry, false);
    if (keepView) return;
    setHash("case=" + entry.case);
    showView("replay");
  }

  // ---- 路径对比 -----------------------------------------------------------------
  function compactSteps(trace, diverge) {
    return el("ol", { class: "compact" }, trace.steps.map(function (s, i) {
      var meta = TOOLS[s.tool] || { label: "—", icon: "pause" };
      var keys = Object.keys(s.args || {}).filter(function (k) { return ["time", "date", "publish_at", "requires_confirmation", "deep_check", "status"].indexOf(k) >= 0; });
      return el("li", { class: "tool-" + (s.tool || "none") + (s.ok ? "" : " err") + (diverge !== null && i >= diverge ? " diverged" : "") },
        icon(meta.icon, "tool-icon"),
        el("span", { class: "c-args", text: (s.tool || "—") + (keys.length ? "  " + keys.map(function (k) { return k + "=" + raw(s.args[k]); }).join("  ") : "") }),
        el("span", { class: "c-result", text: s.result_summary })
      );
    }));
  }
  function renderCompare() {
    var view = document.getElementById("view-compare");
    view.replaceChildren();
    COMPARE_PAIRS.forEach(function (pair) {
      var A = findCase(pair.a), B = findCase(pair.b);
      if (!A || !B) return;
      var ta = runsOf(A.trace)[0], tb = runsOf(B.trace)[0];
      var diverge = null;
      for (var i = 0; i < Math.max(ta.steps.length, tb.steps.length); i++) {
        var sa = ta.steps[i], sb = tb.steps[i];
        if (!sa || !sb || sa.result_summary !== sb.result_summary || sa.tool !== sb.tool) { diverge = i; break; }
      }
      function column(entry, trace) {
        var out = runsOf(entry.output)[0];
        return el("div", { class: "card compare-col" },
          el("p", { class: "detail-kicker" }, el("span", { class: "case-no", text: caseNo(entry) }), el("code", { text: "提示词 " + trace.prompt_version })),
          el("h3", { text: splitTitle(entry)[0] }),
          el("p", { class: "muted small", text: "申请：" + entry.request.asset_id + " · " + (CHANNEL[entry.request.channel] || entry.request.channel) + " · " + entry.request.publish_at }),
          compactSteps(trace, diverge),
          el("div", { class: "compare-final" }, pill(out.status), el("span", { class: "small", text: out.draft ? out.draft.publish_at + " · " + (DRAFT_STATUS[out.draft.status] || out.draft.status) : "未保存草稿" }))
        );
      }
      view.appendChild(el("section", { class: "compare" },
        el("p", { class: "compare-note" }, icon("compare"), el("span", { text: pair.note + (diverge !== null ? "（高亮部分从第 " + (diverge + 1) + " 步开始不同）" : "") })),
        el("div", { class: "compare-grid" }, column(A, ta), column(B, tb))
      ));
    });
  }

  // ---- 实时运行 -----------------------------------------------------------------
  function renderLive(health) {
    var view = document.getElementById("view-live");
    view.replaceChildren();
    var intro = el("section", { class: "card live-intro" }, icon("bolt"), el("div", null,
      el("h3", { text: "用真实模型现场跑一次" }),
      el("ul", null,
        el("li", { text: "选一个场景直接运行，可以先改申请单；模型 " + (health.model || "—") + "，通常 5~25 秒。" }),
        el("li", { text: "每次运行使用独立的内存草稿库，只读合成数据，只保存草稿，不会真实发布。" }),
        el("li", { text: "按 IP 限流：" + health.quota.per_ip + "；今天已用 " + health.quota.used_today + " / " + health.quota.daily_limit + " 次，超限时自动切回回放。" })
      )));
    if (!health.live_enabled) {
      view.append(intro, el("p", { class: "card", text: "实时运行未开启：服务端没有配置模型密钥。可以先看“运行回放”。" }));
      return;
    }
    // 申请单字段（默认收起，只显示摘要）
    var f = {
      asset: el("input", { id: "f-asset", list: "asset-ids", maxlength: "12", required: true }),
      channel: el("select", { id: "f-channel" }, Object.keys(CHANNEL).map(function (k) { return el("option", { value: k, text: CHANNEL[k] }); })),
      date: el("input", { id: "f-date", type: "date", required: true }),
      time: el("select", { id: "f-time" }, ["09:00", "12:00", "18:00", "19:00", "20:00", "21:00"].map(function (t) { return el("option", { value: t, text: t }); })),
      fixed: el("input", { id: "f-fixed", type: "checkbox" }),
      note: el("input", { id: "f-note", maxlength: "200", placeholder: "可选" }),
      fault: el("select", { id: "f-fault" }, [["", "无"], ["error", "save_draft 一直失败"], ["error_once", "save_draft 第一次失败"], ["timeout_after_commit", "save_draft 超时但已写入"]].map(function (o) { return el("option", { value: o[0], text: o[1] }); })),
      repeat: el("input", { id: "f-repeat", type: "checkbox" }),
      code: el("input", { id: "f-code", type: "password", autocomplete: "off" })
    };
    var datalist = el("datalist", { id: "asset-ids" }, ["M01", "M02", "M03", "M04", "M05", "M06", "M07"].map(function (a) { return el("option", { value: a }); }));
    // 实时运行不提供“步数上限”场景（用例 08 只在回放里展示）
    var liveCases = DATA.cases.filter(function (c) { return !(c.options && c.options.max_steps); });
    var current = liveCases[0] ? liveCases[0].case : null;

    // 场景卡片
    var picker = el("div", { class: "scenario-grid", role: "radiogroup", "aria-label": "选择场景" });
    liveCases.forEach(function (c) {
      var t = splitTitle(c);
      var card = el("button", { type: "button", class: "scenario", role: "radio", "aria-checked": "false", "data-case": c.case, onclick: function () { choose(c.case); } },
        el("span", { class: "case-no", text: caseNo(c) }),
        el("span", { class: "scenario-text" }, el("span", { class: "scenario-name", text: t[0] }), el("span", { class: "scenario-desc", text: t[1] })));
      picker.appendChild(card);
    });

    var summary = el("div", { class: "request-summary" });
    var knobs = el("div", { class: "tags knob-tags" });
    function field(label, input, hint) {
      return el("label", { class: "field" }, el("span", { text: label }), input, hint ? el("span", { class: "field-hint", text: hint }) : null);
    }
    function check(label, input, hint) {
      return el("label", { class: "field field-check" }, input, el("span", null, el("span", { class: "check-label", text: label }), hint ? el("span", { class: "field-hint", text: hint }) : null));
    }
    var editBox = el("details", { class: "fold", open: true },
      el("summary", null, icon("edit"), "修改申请单"),
      el("div", { class: "fold-grid" }, field("素材 ID", f.asset), datalist, field("渠道", f.channel), field("日期", f.date), field("时段", f.time),
        check("日期不能改", f.fixed, "勾选后 Agent 不会擅自改到其他日期"), field("备注（可选）", f.note)));
    var advBox = el("details", { class: "fold" },
      el("summary", null, icon("list"), "高级：测试开关（选场景时已自动设置）"),
      el("div", { class: "fold-grid" },
        field("故障注入", f.fault, "模拟保存草稿时的存储故障"),
        check("连续提交两次", f.repeat, "同一申请提交两次，验证只产生一份草稿")));

    function refresh() {
      var parts = [
        ["file", f.asset.value || "—"],
        ["channel", CHANNEL[f.channel.value] || f.channel.value],
        ["calendar", (f.date.value || "—") + " " + f.time.value]
      ];
      if (f.fixed.checked) parts.push(["lock", "日期不能改"]);
      summary.replaceChildren.apply(summary, parts.map(function (p) { return el("span", { class: "summary-chip" }, icon(p[0]), p[1]); }));
      var tags = [];
      if (f.fault.value) tags.push(el("span", { class: "tag tag-fault" }, icon("alert"), "故障注入：" + f.fault.options[f.fault.selectedIndex].text));
      if (f.repeat.checked) tags.push(el("span", { class: "tag tag-brand" }, icon("repeat"), "连续提交两次"));
      knobs.replaceChildren.apply(knobs, tags);
      knobs.hidden = !tags.length;
    }
    function choose(id) {
      var c = findCase(id);
      if (!c) return;
      current = id;
      var r = c.request;
      f.asset.value = r.asset_id; f.channel.value = r.channel;
      f.date.value = r.publish_at.slice(0, 10); f.time.value = r.publish_at.slice(11, 16);
      f.fixed.checked = !!(r.constraints && r.constraints.date_fixed); f.note.value = r.note || "";
      f.fault.value = (c.fault_injection && c.fault_injection.save_draft) || "";
      f.repeat.checked = ((c.options && c.options.repeat) || 1) > 1;
      Array.prototype.forEach.call(picker.children, function (b) { b.setAttribute("aria-checked", b.getAttribute("data-case") === id ? "true" : "false"); });
      refresh();
    }
    [f.asset, f.channel, f.date, f.time, f.fixed, f.fault, f.repeat].forEach(function (input) {
      input.addEventListener("input", refresh);
      input.addEventListener("change", refresh);
    });

    var status = el("p", { class: "live-status", role: "status" });
    var result = el("div", { class: "live-result" });
    var button = el("button", { type: "submit", class: "btn btn-lg" }, icon("bolt"), "用真实模型运行");
    var form = el("form", { class: "card live-form", onsubmit: function (ev) { ev.preventDefault(); submit(); } },
      el("h3", { class: "card-title" }, icon("play"), "第一步：选一个场景"),
      picker,
      el("h3", { class: "card-title step-two" }, icon("file"), "第二步：确认申请单，然后运行"),
      summary, knobs, editBox, advBox,
      health.access_code_required ? field("访问口令", f.code) : null,
      el("div", { class: "form-actions" }, button, status)
    );
    choose(current);

    function submit() {
      var payload = {
        case_id: current,
        request: {
          asset_id: f.asset.value.trim(), channel: f.channel.value, publish_at: f.date.value + " " + f.time.value,
          note: f.note.value, constraints: { date_fixed: f.fixed.checked }
        },
        fault_injection: f.fault.value ? { save_draft: f.fault.value } : {},
        repeat: f.repeat.checked ? 2 : 1
      };
      if (health.access_code_required) payload.access_code = f.code.value;
      button.disabled = true;
      var started = Date.now();
      var label = el("span", { text: "运行中…" });
      status.replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), label);
      var tick = setInterval(function () { label.textContent = "运行中，已等待 " + Math.round((Date.now() - started) / 1000) + " 秒（真实模型通常 5~25 秒）"; }, 500);
      result.replaceChildren();
      fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
        .then(function (resp) { return resp.json().then(function (body) { return { status: resp.status, body: body }; }); })
        .then(function (r) {
          if (r.body.ok) {
            status.replaceChildren(icon("check"), "完成，用时 " + r.body.elapsed_s + " 秒；今天已用 " + r.body.quota.used_today + " / " + r.body.quota.daily_limit + " 次。");
            var req = r.body.case.request;
            var entry = { case: r.body.case.case, title: "实时运行结果：" + req.asset_id + " · " + (CHANNEL[req.channel] || req.channel) + " · " + req.publish_at, covers: [], request: req, fault_injection: r.body.case.fault_injection, options: r.body.case.options, output: r.body.output, trace: r.body.trace };
            result.appendChild(renderEntry(entry, { animate: true }));
            result.scrollIntoView({ behavior: "smooth", block: "start" });
          } else {
            var err = r.body.error || {};
            status.replaceChildren(icon("alert"), err.message || ("请求失败（HTTP " + r.status + "）"));
            if (err.fallback === "replay") {
              result.appendChild(el("p", { class: "card" }, "可以先看这个场景的真实录制：",
                el("button", { type: "button", class: "btn btn-ghost", onclick: function () { selectCase(current); } }, icon("play"), "查看回放")));
            }
          }
        })
        .catch(function () { status.replaceChildren(icon("alert"), "网络错误，已切换到回放。"); selectCase(current); })
        .then(function () { clearInterval(tick); button.disabled = false; });
    }
    view.append(intro, form, result);
  }

  // ---- 视图切换与启动 ------------------------------------------------------------
  function showView(name) {
    ["replay", "compare", "live"].forEach(function (v) {
      document.getElementById("view-" + v).hidden = v !== name;
      var tab = document.querySelector('.tabs [data-view="' + v + '"]');
      if (tab) tab.setAttribute("aria-selected", v === name ? "true" : "false");
    });
  }
  function setHash(h) { if (history.replaceState) history.replaceState(null, "", "#" + h); }

  function boot() {
    renderStats();
    renderPipeline();
    document.getElementById("generated").textContent = DATA.generated_at ? "回放数据生成于 " + DATA.generated_at + " · 提示词 " + (DATA.prompt_version || "—") : "";
    Array.prototype.forEach.call(document.querySelectorAll(".tabs [data-view]"), function (tab) {
      tab.addEventListener("click", function () {
        var v = tab.getAttribute("data-view");
        if (v === "compare") renderCompare();
        showView(v);
        setHash("view=" + v);
      });
    });
    var hash = location.hash.slice(1);
    window.addEventListener("hashchange", function () {  // 手动改地址栏的 #case=… 也能切换
      var h = location.hash.slice(1);
      if (h.indexOf("case=") === 0) selectCase(decodeURIComponent(h.slice(5)));
    });
    if (hash.indexOf("view=") === 0) {
      selectCase(null, true);
      if (hash === "view=compare") { renderCompare(); showView("compare"); }
    } else {
      selectCase(hash.indexOf("case=") === 0 ? decodeURIComponent(hash.slice(5)) : null);
    }
    if (location.protocol === "http:" || location.protocol === "https:") {
      var ctrl = window.AbortController ? new AbortController() : null;
      if (ctrl) setTimeout(function () { ctrl.abort(); }, 4000);
      fetch("/api/health", ctrl ? { signal: ctrl.signal } : {})
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (health) {
          if (!health || health.service !== "xiaoying-agent") return;
          document.getElementById("tab-live").hidden = false;
          renderLive(health);
          if (hash === "view=live") showView("live");
        })
        .catch(function () { /* 静态托管（GitHub Pages / 本地文件）时没有接口，只显示回放 */ });
    }
  }

  if (!DATA.cases.length) {
    document.getElementById("case-detail").textContent = "没有找到回放数据：请先运行 python scripts/build_demo.py。";
  } else {
    boot();
  }
})();
