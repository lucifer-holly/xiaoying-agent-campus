/* 回放页：读取 data/replay.js（由 scripts/build_demo.py 从 examples/ 生成），逐步展示真实模型的 Trace。
 * 部署在演示服务上时，/api/health 可用，页面会多出“实时运行”。
 * 所有文本都用 textContent 写入，模型输出不会被当成 HTML 执行。 */
(function () {
  "use strict";

  var DATA = window.Q1_REPLAY || { cases: [], iterations: [] };
  var STATUS = {
    completed: ["已保存草稿", "ok"],
    needs_confirmation: ["待确认", "warn"],
    needs_input: ["需补充信息", "info"],
    blocked: ["规则阻断", "bad"],
    failed: ["失败", "bad"],
    incomplete_step_limit: ["触顶未完成", "muted"]
  };
  var TOOL_LABEL = { read_asset: "读取素材", check_rules: "规则检查", query_slots: "查询时段", save_draft: "保存草稿", finish: "提交结果" };
  var CHANNEL = { douyin: "抖音", wechat_channels: "视频号", xiaohongshu: "小红书" };
  var DRAFT_STATUS = { scheduled_draft: "已排期草稿（未发布）", pending_confirmation: "待确认草稿（未发布）" };
  var COMPARE_PAIRS = [
    { a: "01-normal-free-slot", b: "02-slot-conflict", note: "两张申请单只差日期（11/13 与 11/12）。第 3 步查到的 18:00 状态不同，模型此后走了不同的路径。" },
    { a: "02-slot-conflict.q1-v1", b: "02-slot-conflict", iterationA: true, note: "同一用例、两版提示词。q1-v1 下模型找到 19:00 后没有先保存待确认草稿，等待确认期间时段可能被占；q1-v2 明确了“待确认草稿只是先占位”。" }
  ];
  var timers = [];

  // ---- 小工具 ----------------------------------------------------------------
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
  function pill(status) {
    var s = STATUS[status] || [status, "muted"];
    return el("span", { class: "pill pill-" + s[1], text: s[0] });
  }
  function fmt(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }
  function findCase(id) {
    var all = DATA.cases.concat(DATA.iterations || []);
    for (var i = 0; i < all.length; i++) if (all[i].case === id) return all[i];
    return null;
  }
  function clearTimers() { timers.forEach(clearTimeout); timers = []; }

  // ---- 申请单 -----------------------------------------------------------------
  function renderRequest(req, faults, options) {
    var rows = [
      ["素材", req.asset_id],
      ["渠道", (CHANNEL[req.channel] || req.channel) + "（" + req.channel + "）"],
      ["申请时间", req.publish_at],
      ["日期不能改", req.constraints && req.constraints.date_fixed ? "是" : "否"],
      ["申请人", req.requester],
      ["备注", req.note]
    ];
    var tags = [];
    Object.keys(faults || {}).forEach(function (tool) {
      tags.push(el("span", { class: "tag tag-fault", text: "故障注入：" + tool + " = " + faults[tool] }));
    });
    if (options && options.repeat > 1) tags.push(el("span", { class: "tag", text: "同一申请连续提交 " + options.repeat + " 次（共用草稿库）" }));
    if (options && options.max_steps) tags.push(el("span", { class: "tag", text: "步数上限 " + options.max_steps }));
    return el("section", { class: "card request" },
      el("h3", { text: "排期申请单 " + (req.request_id || "") }),
      el("dl", { class: "kv" }, rows.filter(function (r) { return r[1]; }).map(function (r) {
        return [el("dt", { text: r[0] }), el("dd", { text: fmt(r[1]) })];
      })),
      tags.length ? el("div", { class: "tags" }, tags) : null
    );
  }

  // ---- 步骤 -------------------------------------------------------------------
  function renderArgs(args) {
    var keys = Object.keys(args || {}).filter(function (k) { return k !== "message"; });
    if (!keys.length) return null;
    return el("div", { class: "args" }, keys.map(function (k) {
      return el("code", { text: k + "=" + fmt(args[k]) });
    }));
  }
  function renderStep(step) {
    var ok = step.ok;
    var tool = step.tool || "（未调用工具）";
    var latency = step.llm && step.llm.latency_ms ? (step.llm.latency_ms / 1000).toFixed(1) + " 秒" : null;
    return el("li", { class: "step " + (ok ? "step-ok" : "step-err") + (step.tool === "finish" ? " step-finish" : "") },
      el("div", { class: "step-head" },
        el("span", { class: "num", text: "#" + step.step }),
        el("span", { class: "tool tool-" + (step.tool || "none"), text: tool }),
        el("span", { class: "tool-label", text: TOOL_LABEL[step.tool] || "" }),
        el("span", { class: ok ? "badge badge-ok" : "badge badge-err", text: ok ? "ok" : "失败" }),
        latency ? el("span", { class: "latency", title: "这一步模型调用耗时", text: latency }) : null
      ),
      renderArgs(step.tool === "finish" ? pick(step.args, ["status", "draft_id", "publish_at", "risk_rule_ids", "missing_fields"]) : step.args),
      step.decision_note ? el("blockquote", { class: "note" }, el("span", { class: "label", text: "决策依据" }), step.decision_note) : null,
      el("p", { class: "result" }, el("span", { class: "label", text: "返回摘要" }), step.result_summary),
      step.next_action ? el("p", { class: "next", text: "→ 下一步：" + step.next_action }) : null,
      step.observation ? el("details", null,
        el("summary", { text: step.tool === "finish" ? "校验器结果" : "模型看到的完整返回" }),
        el("pre", { text: JSON.stringify(step.observation, null, 2) })) : null
    );
  }
  function pick(obj, keys) {
    var out = {};
    keys.forEach(function (k) { if (obj && obj[k] !== undefined) out[k] = obj[k]; });
    return out;
  }

  // ---- 最终输出 -----------------------------------------------------------------
  function renderFinal(out, trace) {
    var d = out.draft;
    var rows = [];
    if (d) {
      rows.push(["草稿编号", d.draft_id + (d.created_in_this_run ? "（本次新建）" : "（已存在，未新建）")]);
      rows.push(["草稿状态", DRAFT_STATUS[d.status] || d.status]);
      rows.push(["发布时间", d.publish_at + (d.requested_publish_at && d.requested_publish_at !== d.publish_at ? "（申请 " + d.requested_publish_at + "）" : "")]);
      if (d.change_reason) rows.push(["调整原因", d.change_reason]);
    } else {
      rows.push(["草稿", "无（草稿库里没有本申请的草稿）"]);
    }
    if (out.review) rows.push(["规则结论", out.review.verdict + (out.review.deep_check ? "（已补查）" : "")]);
    if (out.missing_fields && out.missing_fields.length) rows.push(["缺失信息", out.missing_fields.join("、")]);
    if (out.risk_rule_ids && out.risk_rule_ids.length) rows.push(["命中规则", out.risk_rule_ids.join("、")]);
    if (out.confirmation_question) rows.push(["待确认问题", out.confirmation_question]);
    var corrections = (out.validator && out.validator.corrections) || [];
    var warnings = (out.validator && out.validator.warnings) || [];
    var run = out.run || {};
    var usage = trace && trace.llm_usage;
    var meta = [
      "模型 " + (run.model || "—"), "提示词 " + (run.prompt_version || "—"),
      "用了 " + run.steps_used + " 步（上限 " + run.max_steps + "）", "结束原因 " + run.end_reason
    ];
    if (usage && usage.calls) meta.push("模型耗时 " + (usage.latency_ms / 1000).toFixed(1) + " 秒", "tokens " + usage.prompt_tokens + " + " + usage.completion_tokens);
    return el("section", { class: "card final" },
      el("div", { class: "final-head" }, el("h3", { text: "最终输出" }), pill(out.status)),
      el("p", { class: "message", text: out.message }),
      el("dl", { class: "kv" }, rows.map(function (r) { return [el("dt", { text: r[0] }), el("dd", { text: r[1] })]; })),
      corrections.length ? el("div", { class: "corrections" },
        el("h4", { text: "校验器更正" }),
        el("ul", null, corrections.map(function (c) { return el("li", { text: fmt(c.from) + " → " + fmt(c.to) + "：" + c.reason }); }))) :
        el("p", { class: "muted small", text: "校验器：模型的结论与草稿库一致，无需更正。" }),
      warnings.length ? el("ul", { class: "warnings" }, warnings.map(function (w) { return el("li", { text: w }); })) : null,
      el("p", { class: "run-meta", text: meta.join(" · ") })
    );
  }

  // ---- 一次运行（可能是多次提交中的一次）------------------------------------------
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
    var body = el("div");
    var head = el("header", { class: "detail-head" },
      el("div", null,
        el("p", { class: "case-id", text: entry.case }),
        el("h2", { text: entry.title || entry.case }),
        entry.covers && entry.covers.length ? el("div", { class: "tags" }, entry.covers.map(function (c) { return el("span", { class: "tag", text: c }); })) : null
      ),
      el("div", { class: "actions" },
        el("button", { type: "button", class: "btn", onclick: function () { renderInto(entry, true); } , text: "逐步播放" }),
        el("button", { type: "button", class: "btn btn-ghost", onclick: function () { toggleDetails(body); }, text: "展开 / 收起返回" })
      )
    );
    var parts = [head, renderRequest(entry.request, entry.fault_injection, entry.options)];
    if (traces.length > 1) {
      var tabs = el("div", { class: "run-tabs", role: "tablist" });
      var holder = el("div");
      traces.forEach(function (t, i) {
        tabs.appendChild(el("button", {
          type: "button", role: "tab", class: "btn btn-tab", "aria-selected": i === 0 ? "true" : "false",
          text: "第 " + (i + 1) + " 次提交 · " + (STATUS[outs[i].status] || [outs[i].status])[0],
          onclick: function (ev) {
            Array.prototype.forEach.call(tabs.children, function (b) { b.setAttribute("aria-selected", "false"); });
            ev.currentTarget.setAttribute("aria-selected", "true");
            clearTimers();
            holder.replaceChildren(renderRun(traces[i], outs[i], false));
          }
        }));
      });
      holder.appendChild(renderRun(traces[0], outs[0], opts.animate));
      parts.push(tabs, holder);
      var sc = entry.output.store_check;
      if (sc) parts.push(el("p", { class: "store-check", text: "草稿库核对：申请 " + sc.request_id + " 共有 " + sc.drafts_for_request + " 份草稿（" + sc.draft_ids.join("、") + "），草稿库合计 " + sc.total_drafts_in_store + " 份。" }));
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
    var detail = document.getElementById("case-detail");
    detail.replaceChildren(renderEntry(entry, { animate: animate }));
  }

  // ---- 回放视图 -----------------------------------------------------------------
  function renderCaseList(activeId) {
    var box = document.getElementById("case-list");
    box.replaceChildren();
    function item(entry, extraClass) {
      return el("button", {
        type: "button", class: "case-item" + (entry.case === activeId ? " active" : "") + (extraClass || ""),
        onclick: function () { selectCase(entry.case); }
      },
        el("span", { class: "case-title", text: entry.title || entry.case }),
        pill(lastStatus(entry))
      );
    }
    box.appendChild(el("h2", { class: "list-title", text: "验收用例" }));
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
      return el("li", { class: (s.ok ? "" : "err ") + (diverge !== null && i >= diverge ? "diverged" : "") },
        el("span", { class: "tool tool-" + (s.tool || "none"), text: s.tool || "—" }),
        el("span", { class: "c-args", text: Object.keys(s.args || {}).filter(function (k) { return ["time", "date", "publish_at", "requires_confirmation", "deep_check", "status"].indexOf(k) >= 0; }).map(function (k) { return k + "=" + fmt(s.args[k]); }).join("  ") }),
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
          el("p", { class: "case-id", text: entry.case + " · 提示词 " + trace.prompt_version }),
          el("h3", { text: entry.title || entry.case }),
          el("p", { class: "muted small", text: "申请：" + entry.request.asset_id + " " + (CHANNEL[entry.request.channel] || entry.request.channel) + " " + entry.request.publish_at }),
          compactSteps(trace, diverge),
          el("div", { class: "final-head" }, pill(out.status), el("span", { class: "small", text: out.draft ? out.draft.publish_at + " · " + (DRAFT_STATUS[out.draft.status] || out.draft.status) : "未保存草稿" })),
          el("p", { class: "small", text: out.message })
        );
      }
      view.appendChild(el("section", { class: "compare" },
        el("p", { class: "compare-note", text: pair.note + (diverge !== null ? "（高亮部分从第 " + (diverge + 1) + " 步开始不同）" : "") }),
        el("div", { class: "compare-grid" }, column(A, ta), column(B, tb))
      ));
    });
  }

  // ---- 实时运行 -----------------------------------------------------------------
  function renderLive(health) {
    var view = document.getElementById("view-live");
    view.replaceChildren();
    if (!health.live_enabled) {
      view.appendChild(el("p", { class: "card", text: "实时运行未开启：服务端没有配置模型密钥或访问口令。可以先看“运行回放”。" }));
      return;
    }
    var presetSel = el("select", { id: "f-preset" }, DATA.cases.map(function (c) { return el("option", { value: c.case, text: c.title || c.case }); }));
    var f = {
      asset: el("input", { id: "f-asset", list: "asset-ids", maxlength: "12", required: true }),
      channel: el("select", { id: "f-channel" }, Object.keys(CHANNEL).map(function (k) { return el("option", { value: k, text: CHANNEL[k] }); })),
      date: el("input", { id: "f-date", type: "date", required: true }),
      time: el("select", { id: "f-time" }, ["09:00", "12:00", "18:00", "19:00", "20:00", "21:00"].map(function (t) { return el("option", { value: t, text: t }); })),
      fixed: el("input", { id: "f-fixed", type: "checkbox" }),
      note: el("input", { id: "f-note", maxlength: "200" }),
      fault: el("select", { id: "f-fault" }, [["", "无"], ["error", "save_draft 一直失败"], ["error_once", "save_draft 第一次失败"], ["timeout_after_commit", "save_draft 超时但已写入"]].map(function (o) { return el("option", { value: o[0], text: o[1] }); })),
      repeat: el("select", { id: "f-repeat" }, [["1", "1 次"], ["2", "连续 2 次（验证防重复）"]].map(function (o) { return el("option", { value: o[0], text: o[1] }); })),
      steps: el("input", { id: "f-steps", type: "number", min: "1", max: "8", value: "8" }),
      code: el("input", { id: "f-code", type: "password", autocomplete: "off", required: true })
    };
    var datalist = el("datalist", { id: "asset-ids" }, ["M01", "M02", "M03", "M04", "M05", "M06", "M07"].map(function (a) { return el("option", { value: a }); }));
    function fill(id) {
      var c = findCase(id);
      if (!c) return;
      var r = c.request;
      f.asset.value = r.asset_id; f.channel.value = r.channel;
      f.date.value = r.publish_at.slice(0, 10); f.time.value = r.publish_at.slice(11, 16);
      f.fixed.checked = !!(r.constraints && r.constraints.date_fixed); f.note.value = r.note || "";
      f.fault.value = (c.fault_injection && c.fault_injection.save_draft) || "";
      f.repeat.value = String((c.options && c.options.repeat) || 1);
      f.steps.value = String((c.options && c.options.max_steps) || 8);
    }
    presetSel.addEventListener("change", function () { fill(presetSel.value); });
    fill(presetSel.value);
    var status = el("p", { class: "live-status", role: "status" });
    var result = el("div", { class: "live-result" });
    var button = el("button", { type: "submit", class: "btn", text: "用真实模型运行" });
    var form = el("form", { class: "card live-form", onsubmit: function (ev) { ev.preventDefault(); submit(); } },
      el("h3", { text: "实时运行（真实模型）" }),
      el("p", { class: "muted small", text: "每次运行都用独立的内存草稿库，只读合成数据，不会真实发布。按 IP 限流：" + health.quota.per_ip + "；今天已用 " + health.quota.used_today + " / " + health.quota.daily_limit + " 次。" }),
      field("预设用例", presetSel), field("素材 ID", f.asset), datalist, field("渠道", f.channel),
      field("日期", f.date), field("时段", f.time), field("日期不能改", f.fixed), field("备注", f.note),
      field("故障注入", f.fault), field("提交次数", f.repeat), field("步数上限", f.steps), field("访问口令", f.code),
      el("div", { class: "form-actions" }, button, status)
    );
    function field(label, input) { return el("label", { class: "field" }, el("span", { text: label }), input); }
    function submit() {
      var payload = {
        case_id: presetSel.value,
        access_code: f.code.value,
        request: {
          asset_id: f.asset.value.trim(), channel: f.channel.value, publish_at: f.date.value + " " + f.time.value,
          note: f.note.value, constraints: { date_fixed: f.fixed.checked }
        },
        fault_injection: f.fault.value ? { save_draft: f.fault.value } : {},
        repeat: Number(f.repeat.value), max_steps: Number(f.steps.value)
      };
      button.disabled = true;
      var started = Date.now();
      var tick = setInterval(function () { status.textContent = "运行中…已等待 " + Math.round((Date.now() - started) / 1000) + " 秒（真实模型通常 5~25 秒）"; }, 500);
      result.replaceChildren();
      fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
        .then(function (resp) { return resp.json().then(function (body) { return { status: resp.status, body: body }; }); })
        .then(function (r) {
          if (r.body.ok) {
            status.textContent = "完成，用时 " + r.body.elapsed_s + " 秒；今天已用 " + r.body.quota.used_today + " / " + r.body.quota.daily_limit + " 次。";
            var entry = { case: r.body.case.case, title: "实时运行结果", covers: [], request: r.body.case.request, fault_injection: r.body.case.fault_injection, options: r.body.case.options, output: r.body.output, trace: r.body.trace };
            result.appendChild(renderEntry(entry, { animate: true }));
          } else {
            var err = r.body.error || {};
            status.textContent = err.message || ("请求失败（HTTP " + r.status + "）");
            if (err.fallback === "replay") {
              result.appendChild(el("p", { class: "card" }, "可以先看这个用例的真实录制：",
                el("button", { type: "button", class: "btn btn-ghost", text: "查看回放", onclick: function () { selectCase(presetSel.value); } })));
            }
          }
        })
        .catch(function () { status.textContent = "网络错误，已切换到回放。"; selectCase(presetSel.value); })
        .then(function () { clearInterval(tick); button.disabled = false; });
    }
    view.append(form, result);
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
    document.getElementById("meta").textContent = "真实模型 " + (DATA.model || "—") + " · 提示词 " + (DATA.prompt_version || "—") + " · " + DATA.cases.length + " 个验收用例";
    document.getElementById("generated").textContent = DATA.generated_at ? "回放数据生成于 " + DATA.generated_at : "";
    Array.prototype.forEach.call(document.querySelectorAll(".tabs [data-view]"), function (tab) {
      tab.addEventListener("click", function () {
        var v = tab.getAttribute("data-view");
        if (v === "compare") renderCompare();
        showView(v);
        setHash("view=" + v);
      });
    });
    var hash = location.hash.slice(1);
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
          if (hash.indexOf("view=live") === 0) showView("live");
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
