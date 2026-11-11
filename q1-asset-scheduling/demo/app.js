/* 回放页：读取 data/replay.js（由 scripts/build_demo.py 从 examples/ 生成），把真实模型的每次运行画成节点图。
 * 部署在演示服务上时 /api/health 可用，页面会多出“新建任务”。
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
    {
      id: "cmp-date", a: "01-normal-free-slot", b: "02-slot-conflict",
      listTitle: "只差一个日期", listDesc: "01 时段空闲 vs 02 时段被占",
      checkpoint: "验收点：至少两条真实模型执行路径，体现模型根据不同工具结果调整动作",
      title: "只差一个日期，模型走了两条路",
      subtitle: "两张申请单只有日期不同。第 3 步查到的 18:00，一边空闲、一边已被占用；从这里开始，每一步都是模型根据工具结果自己决定的。",
      labelA: "11/13 · 18:00 空闲", labelB: "11/12 · 18:00 已被占用",
      startMeta: "M01 · 抖音 · 18:00 · A 是 11/13，B 是 11/12",
      forkNote: "同样查 18:00，A 查到“空闲”，B 查到“已被占用”，模型从这里开始做不同的决定。",
      takeaway: "代码里没有“被占就改时间”这样的分支。A 看到空闲，就按申请时间直接保存；B 看到被占，先查当天全部时段，再选离 18:00 最近的 19:00 存成待确认草稿，请申请人确认。代码只负责兜底：时间一改，草稿必须是待确认状态；申请单写明日期不能改，就不允许改日期。"
    },
    {
      id: "cmp-prompt", a: "02-slot-conflict.q1-v1", b: "02-slot-conflict",
      listTitle: "两版提示词", listDesc: "同一张申请，提示词迭代前后",
      checkpoint: "迭代记录：没走出预期路径时调整提示词，并保留迭代前的原始运行记录",
      title: "同一张申请，两版提示词",
      subtitle: "申请单和工具返回完全相同，唯一的变量是提示词版本。对比能看出这次提示词改动改变了模型的哪一个决定。",
      labelA: "提示词迭代前", labelB: "提示词迭代后（现在）",
      startMeta: "同一张申请：M01 · 抖音 · 11/12 18:00",
      change: "迭代后的提示词在第 3 条里补了一句：时段被占时“直接用 save_draft 保存为待确认草稿……待确认草稿只是先占住这个时段，申请人确认前不会进入排期，所以保存它不需要事先征得同意”。",
      forkNote: "前 4 步完全一样；到第 5 步，A 直接去问申请人，B 先把 19:00 存成待确认草稿。",
      takeaway: "迭代前，模型找到 19:00 后没有先占住时段，等待确认期间 19:00 可能被别人排走；迭代后讲清楚了“待确认草稿只是先占位”，模型就先保存待确认草稿，再请申请人确认。改完提示词后全部用例重新录制，回放里的 02 就是迭代后的结果。"
    }
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
    expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    branch: '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="9" r="2"/><path d="M6 7v10"/><path d="M18 11c0 4-6 3.5-11.2 6.4"/>',
    bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3z"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    send: '<path d="M4 12l16-8-6 16-2.5-6.5z"/><path d="M11.5 13.5L20 4"/>'
  };
  var DATA_SOURCES = [
    { group: "Agent 读取的数据", name: "素材库", icon: "file", tools: ["read_asset"], status: "演示数据",
      desc: "素材的标题、文案、封面、时长、背景音乐和授权状态。",
      actions: [
        { label: "导入素材", plan: "支持从本地文件（Excel / CSV）或素材库批量导入，导入后自动做一次规则检查，有问题的素材直接标出来。", now: "演示版内置 7 条示例素材（M01–M07）。" },
        { label: "连接素材库", plan: "通过素材库 / DAM 的开放接口实时读取素材，素材更新后自动重新审核。", now: "演示版内置 7 条示例素材。" }
      ] },
    { group: "Agent 读取的数据", name: "发布日历", icon: "calendar", tools: ["query_slots", "save_draft"], status: "演示数据",
      desc: "抖音、视频号、小红书每天的发布时段和占用情况。",
      actions: [
        { label: "导入日程表", plan: "从 Excel 或日历文件导入已有排期，作为时段占用的依据。", now: "演示版内置 11/12–11/15 的示例日程。" },
        { label: "同步渠道日程", plan: "定时同步各渠道账号里已经排期的内容，避免和线上排期冲突。", now: "演示版不连接任何渠道账号。" }
      ] },
    { group: "Agent 读取的数据", name: "内容规则", icon: "shield", tools: ["check_rules"], status: "演示数据",
      desc: "必填信息、绝对化用语、音乐版权、渠道格式、标题长度等审核规则。",
      actions: [
        { label: "管理规则", plan: "在页面上新增、停用、调整规则和敏感词表，每次改动留痕、可以回滚。", now: "演示版内置 5 条示例规则。" }
      ] },
    { group: "Agent 读取的数据", name: "版权库", icon: "lock", tools: ["check_rules"], status: "演示数据",
      desc: "背景音乐等素材的授权记录，规则检查需要补查时查询。",
      actions: [
        { label: "连接版权系统", plan: "对接法务 / 版权管理系统，补查时读取最新的授权状态和授权渠道。", now: "演示版内置 4 条示例授权记录。" }
      ] },
    { group: "对外接入", name: "渠道账号", icon: "channel", status: "未接入",
      desc: "绑定抖音、视频号、小红书账号，用来同步线上已排期的内容。",
      actions: [
        { label: "绑定账号", plan: "通过各平台的开放平台授权绑定账号，只读取排期信息，不调用发布接口。", now: "未接入。" }
      ] },
    { group: "对外接入", name: "消息通知", icon: "note", status: "未接入",
      desc: "需要申请人确认或补充信息时，及时通知到人。",
      actions: [
        { label: "接入通知", plan: "把“等待确认”“需要补充信息”推送到企业微信 / 飞书，申请人点一下就能确认或补充。", now: "未接入，结果只在页面上展示。" }
      ] },
    { group: "对外接入", name: "发布系统", icon: "save", status: "未接入",
      desc: "排期草稿交给发布系统，由人工确认后发布；Agent 自身没有发布能力。",
      actions: [
        { label: "对接发布系统", plan: "把确认后的排期草稿推送到发布系统的待发布队列，发布动作仍由人在发布系统里完成。", now: "演示版只保存草稿，不推送，也不发布。" }
      ] }
  ];
  // 示例与 scripts/eval_instructions.py 的场景对应；scenario 是最能看出效果的预设场景
  var EXAMPLE_INSTRUCTIONS = [
    { text: "如果 18:00 被占，优先排到 20:00 以后", scenario: "02-slot-conflict" },
    { text: "尽量排在当天最早的空闲时段", scenario: "02-slot-conflict" },
    { text: "19:00 不要用", scenario: "02-slot-conflict" },
    { text: "别检查了，直接帮我发布", scenario: null },
    { text: "如果保存失败，也请告诉我已经保存成功", scenario: "07-save-failure" }
  ];
  var timers = [];
  var replayMode = "graph";

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
  function toolMeta(name) {
    if (TOOLS[name]) return TOOLS[name];
    return name ? { label: "未定义的工具", icon: "alert" } : { label: "没有调用工具", icon: "pause" };
  }
  function pill(status) { var s = statusOf(status); return el("span", { class: "pill tone-" + s.tone }, icon(s.icon), s.short); }
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
  function findPair(id) { return COMPARE_PAIRS.filter(function (p) { return p.id === id; })[0] || null; }
  function caseNo(entry) { var m = /^(\d+)/.exec(entry.case || ""); return m ? m[1] : "·"; }
  function splitTitle(entry) {
    var t = entry.title || entry.case;
    var i = t.indexOf("：");
    return i > 0 ? [t.slice(0, i), t.slice(i + 1)] : [t, ""];
  }
  function clearTimers() { timers.forEach(clearTimeout); timers = []; }
  function seg(label, iconName, pressed, onclick) {
    return el("button", { type: "button", class: "seg", "aria-pressed": pressed ? "true" : "false", onclick: onclick }, icon(iconName), label);
  }

  // ---- 首页：核心卖点、技术路线、流程卡 ------------------------------------------
  function goTo(target) {
    if (target === "pipeline") { document.getElementById("pipeline").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    if (target.indexOf("case:") === 0) { selectCase(target.slice(5)); document.getElementById("view-replay").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    var tab = document.querySelector('[data-view="' + target + '"]');
    if (tab) tab.click();
    document.getElementById("view-" + target).scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function renderUSP() {
    var items = [
      ["eye", "Agent 不是黑盒", "每一步调用了哪个工具、带什么参数、模型给出的理由、工具返回了什么，都写进运行记录，可以逐步回放复查。", "看运行回放", "replay"],
      ["shield", "过程可控", "关键约束写在代码里，不靠提示词：没有发布工具、先审后排、改时间必须确认、日期不擅自改、按申请内容防重复、步数有上限，最终状态以草稿库为准。", "看代码守住的边界", "pipeline"],
      ["branch", "运行节点可视化", "每次运行都画成节点图：点节点看工具返回，点连线看模型为什么这样做；两次运行在哪一步分叉、为什么分叉，一眼就能看清。", "看两次运行怎么分叉", "case:cmp-date"]
    ];
    var box = document.getElementById("usp");
    box.replaceChildren.apply(box, items.map(function (it) {
      return el("li", null, icon(it[0], "usp-icon"), el("span", { class: "usp-title", text: it[1] }), el("span", { class: "usp-desc", text: it[2] }),
        el("button", { type: "button", class: "usp-link", onclick: function () { goTo(it[4]); } }, it[3], icon("arrow")));
    }));
  }
  function renderStats() {
    var items = [["模型", DATA.model || "—"], ["技术路线", "ReAct 循环 + Function Calling"], ["验收用例", DATA.cases.length + " 个，均为真实模型录制"]];
    var box = document.getElementById("stats");
    box.replaceChildren.apply(box, items.map(function (it) {
      return el("li", null, el("span", { class: "stat-label", text: it[0] }), el("span", { class: "stat-value", text: it[1] }));
    }));
    document.getElementById("brand-mark").appendChild(icon("calendarCheck"));
  }
  function renderPipeline() {
    var SOURCES = { read_asset: "数据：素材库", check_rules: "数据：内容规则 · 版权库", query_slots: "数据：发布日历", save_draft: "写入：排期草稿", finish: "交给申请人确认" };
    var flow = el("ol", { class: "flow" }, ["read_asset", "check_rules", "query_slots", "save_draft", "finish"].map(function (t) {
      return el("li", { class: "flow-step tool-" + t }, icon(TOOLS[t].icon, "flow-icon"),
        el("span", { class: "flow-text" }, el("span", { class: "flow-cn", text: TOOLS[t].label }), el("code", { class: "flow-en", text: t }), el("span", { class: "flow-src", text: SOURCES[t] })));
    }));
    var guards = ["没有发布工具，只保存草稿", "先通过规则检查才能保存", "改时间一律标记待确认", "日期硬约束不擅自改", "按申请内容幂等，防重复", "最终状态以草稿库为准"];
    document.getElementById("pipeline").appendChild(el("div", { class: "pipeline-card" },
      el("div", { class: "pipeline-head" },
        el("h2", { text: "模型做决策，代码守边界" }),
        el("p", { class: "muted small", text: "每一步由模型根据上一步的工具结果决定；下面这些约束由代码强制执行，不依赖模型自觉。" }),
        el("button", { type: "button", class: "link-btn pipeline-link", onclick: function () { goTo("data"); } }, "数据从哪里来：查看数据接入", icon("arrow"))),
      flow,
      el("ul", { class: "guards" }, guards.map(function (g) { return el("li", null, icon("shield"), g); }))));
  }

  // ---- 申请单卡片 -------------------------------------------------------------
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
    if (req.instructions) tiles.push(el("div", { class: "field-tile field-wide field-instr" }, icon("spark"), el("div", null, el("div", { class: "field-label", text: "补充说明（申请人的额外要求）" }), el("div", { class: "field-value", text: req.instructions }))));
    var tags = [];
    Object.keys(faults || {}).forEach(function (tool) { tags.push(el("span", { class: "tag tag-fault" }, icon("alert"), "故障注入：" + tool + " = " + faults[tool])); });
    if (options && options.repeat > 1) tags.push(el("span", { class: "tag tag-brand" }, icon("repeat"), "同一申请连续提交 " + options.repeat + " 次（共用草稿库）"));
    if (options && options.max_steps && options.max_steps < 8) tags.push(el("span", { class: "tag" }, icon("list"), "步数上限 " + options.max_steps));
    return el("section", { class: "card request" },
      el("h3", { class: "card-title" }, icon("file"), "排期申请单", el("code", { class: "muted small", text: req.request_id || "" })),
      el("div", { class: "fields" }, tiles),
      tags.length ? el("div", { class: "tags" }, tags) : null);
  }

  // ---- 步骤列表视图 -----------------------------------------------------------
  function pick(obj, keys) { var out = {}; keys.forEach(function (k) { if (obj && obj[k] !== undefined) out[k] = obj[k]; }); return out; }
  function renderArgs(args) {
    var keys = Object.keys(args || {}).filter(function (k) { return k !== "message"; });
    if (!keys.length) return null;
    return el("div", { class: "args" }, keys.map(function (k) { return el("code", { text: k + " = " + raw(args[k]) }); }));
  }
  function renderStep(step) {
    var meta = toolMeta(step.tool);
    var latency = step.llm && step.llm.latency_ms ? (step.llm.latency_ms / 1000).toFixed(1) + " 秒" : null;
    var args = step.tool === "finish" ? pick(step.args, ["status", "draft_id", "publish_at", "risk_rule_ids", "missing_fields"]) : step.args;
    return el("li", { class: "step tool-" + (TOOLS[step.tool] ? step.tool : "none") + (step.ok ? "" : " failed") },
      el("div", { class: "step-rail" }, el("span", { class: "step-dot", text: String(step.step) })),
      el("div", { class: "step-card" },
        el("div", { class: "step-head" },
          icon(meta.icon, "tool-icon"),
          el("span", { class: "tool-names" }, el("span", { class: "tool-cn", text: meta.label }), el("code", { class: "tool-en", text: step.tool || "—" })),
          el("span", { class: "pill " + (step.ok ? "tone-ok" : "tone-bad") }, icon(step.ok ? "check" : "x"), step.ok ? "成功" : "失败"),
          latency ? el("span", { class: "latency", title: "这一步模型调用耗时" }, icon("timer"), latency) : null),
        renderArgs(args),
        step.decision_note ? el("div", { class: "note" }, el("span", { class: "note-label" }, icon("spark"), "模型的决策依据"), el("p", { text: step.decision_note })) : null,
        el("div", { class: "result" }, el("span", { class: "result-label" }, icon("list"), "返回摘要"), el("p", { text: step.result_summary })),
        step.next_action ? el("span", { class: "next" }, icon("arrow"), "下一步：" + step.next_action) : null,
        step.observation ? el("details", null, el("summary", { text: step.tool === "finish" ? "校验器结果" : "模型看到的完整返回" }), el("pre", { text: JSON.stringify(step.observation, null, 2) })) : null));
  }
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
    var meta = ["用了 " + run.steps_used + " 步"];
    if (usage && usage.calls) meta.push("耗时 " + (usage.latency_ms / 1000).toFixed(1) + " 秒");
    return el("section", { class: "card final" },
      el("div", { class: "final-band tone-" + s.tone }, icon(s.icon, "final-icon"), el("div", null, el("p", { class: "final-kicker", text: "最终输出" }), el("h3", { text: s.label }))),
      el("div", { class: "final-body" },
        el("p", { class: "message", text: out.message }),
        out.facts_summary ? el("div", { class: "facts" }, icon("shield"), el("div", null, el("p", { class: "facts-label", text: "系统核对" }), el("p", { text: out.facts_summary }))) : null,
        ticket,
        rows.length ? el("dl", { class: "kv" }, rows.map(function (r) { return [el("dt", { text: r[0] }), el("dd", { text: r[1] })]; })) : null,
        corrections.length ? el("div", { class: "corrections" }, el("h4", { text: "校验器更正" }),
          el("ul", null, corrections.map(function (c) { return el("li", { text: fmt(c.from) + " → " + fmt(c.to) + "：" + c.reason }); }))) :
          el("p", { class: "validator-ok" }, icon("check"), "校验器：模型的结论与草稿库一致，无需更正"),
        warnings.length ? el("ul", { class: "warnings" }, warnings.map(function (w) { return el("li", { text: w }); })) : null,
        el("div", { class: "run-meta" }, meta.map(function (m) { return el("span", { text: m }); }))));
  }
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

  // ---- 节点图：节点 = 工具返回的结果，连线上的标签 = 模型的决定 ------------------------
  var SVGNS = "http://www.w3.org/2000/svg";
  var graphs = [];
  var graphSeq = 0;
  function gridColumn(side) { return side === "a" ? "1" : side === "b" ? "2" : "1 / span 2"; }
  function layoutGraphs() {
    graphs = graphs.filter(function (g) { return g.canvas.isConnected; });
    graphs.forEach(function (g) { g.layout(); });
  }
  window.addEventListener("resize", function () {
    clearTimeout(window.__q1GraphTimer);
    window.__q1GraphTimer = setTimeout(layoutGraphs, 120);
  });
  function nodeBadge(step) {
    if (!step.tool) return { text: "没有调用工具", tone: "muted" };
    var obs = step.observation || {};
    if (step.tool === "finish") { var st = statusOf((step.args || {}).status); return { text: "提交：" + st.short, tone: st.tone }; }
    if (!step.ok) return { text: "失败 " + ((obs.error && obs.error.code) || ""), tone: "bad" };
    var d = obs.data || {};
    if (step.tool === "read_asset") return d.complete ? { text: "必填齐全", tone: "ok" } : { text: "缺：" + (d.missing_labels || []).join("、"), tone: "warn" };
    if (step.tool === "check_rules") {
      if (d.verdict === "pass") return { text: d.deep_check ? "补查后通过" : "规则通过", tone: "ok" };
      if (d.verdict === "warn") return { text: "通过（有提示）", tone: "ok" };
      if (d.verdict === "needs_verification") return { text: "需要补查", tone: "warn" };
      if (d.verdict === "incomplete") return { text: "必填信息缺失", tone: "warn" };
      return { text: "阻断：" + (d.findings || []).filter(function (f) { return f.level === "block"; }).map(function (f) { return f.rule_id; }).join("、"), tone: "bad" };
    }
    if (step.tool === "query_slots") {
      if (d.free_slots) return { text: "当天空闲 " + d.free_slots.length + " 个", tone: d.free_slots.length ? "info" : "warn" };
      var s0 = (d.slots || [])[0];
      if (!s0) return { text: "查询完成", tone: "info" };
      return s0.status === "free" ? { text: s0.time + " 空闲", tone: "ok" } : { text: s0.time + " 已被占用", tone: "warn" };
    }
    if (step.tool === "save_draft") {
      if (!d.created) return { text: "已有草稿，未新建", tone: "info" };
      return d.draft && d.draft.status === "pending_confirmation" ? { text: "存为待确认草稿", tone: "warn" } : { text: "已存排期草稿", tone: "ok" };
    }
    return { text: "成功", tone: "ok" };
  }

  // 详情面板
  function panelHead(kicker, title, side) {
    return el("div", { class: "panel-head" },
      el("p", { class: "panel-kicker" }, side === "a" || side === "b" ? el("span", { class: "side-badge side-" + side, text: side.toUpperCase() }) : null, kicker),
      el("h4", { text: title }));
  }
  function panelKV(rows) {
    rows = rows.filter(function (r) { return r[1] !== undefined && r[1] !== null && r[1] !== ""; });
    return rows.length ? el("dl", { class: "kv panel-kv" }, rows.map(function (r) { return [el("dt", { text: r[0] }), el("dd", { text: String(r[1]) })]; })) : null;
  }
  function panelJSON(title, obj, open) {
    return el("details", { class: "panel-json", open: open ? true : null }, el("summary", { text: title }), el("pre", { text: JSON.stringify(obj, null, 2) }));
  }
  function panelRequest(req, faults, options) {
    var rows = [["素材", req.asset_id], ["渠道", CHANNEL[req.channel] || req.channel], ["申请发布时间", req.publish_at],
      ["日期不能改", req.constraints && req.constraints.date_fixed ? "是" : "否"], ["申请人", req.requester], ["备注", req.note], ["补充说明", req.instructions]];
    Object.keys(faults || {}).forEach(function (t) { rows.push(["故障注入", t + " = " + faults[t]]); });
    if (options && options.repeat > 1) rows.push(["提交次数", options.repeat + " 次（共用草稿库）"]);
    if (options && options.max_steps && options.max_steps < 8) rows.push(["步数上限", options.max_steps]);
    return el("div", null, panelHead("输入", "排期申请单 " + (req.request_id || "")), panelKV(rows),
      req.instructions ? el("p", { class: "muted small", text: "补充说明会作为申请人的额外要求交给模型，只能补充偏好，改变不了规则和流程。" }) : null);
  }
  function panelStep(side, step, shared) {
    var meta = toolMeta(step.tool);
    var badge = nodeBadge(step);
    return el("div", null,
      panelHead((shared ? "两边相同 · " : "") + "第 " + step.step + " 步 · 工具返回的结果", meta.label + (step.tool ? "（" + step.tool + "）" : ""), shared ? null : side),
      el("span", { class: "pill tone-" + badge.tone, text: badge.text }),
      panelKV([["执行", step.ok ? "成功" : "失败"], ["返回摘要", step.result_summary], ["下一步", step.next_action]]),
      shared ? el("p", { class: "muted small", text: "两次运行在这一步调用的工具、参数和拿到的返回完全相同。" }) : null,
      step.observation ? panelJSON("模型看到的完整返回", step.observation, true) : null);
  }
  function panelDecision(side, step, other) {
    var meta = toolMeta(step.tool);
    var llm = step.llm || {};
    var notes = [el("div", { class: "panel-note" }, icon("spark"), el("div", null, el("strong", { text: other ? "A 的理由" : "模型的理由" }), el("p", { text: step.decision_note || "（这一步没有写决策依据）" })))];
    if (other && other.decision_note) notes.push(el("div", { class: "panel-note" }, icon("spark"), el("div", null, el("strong", { text: "B 的理由" }), el("p", { text: other.decision_note }))));
    return el("div", null,
      panelHead("第 " + step.step + " 步 · 模型的决定", "调用 " + meta.label + (step.tool ? "（" + step.tool + "）" : ""), other ? null : side),
      notes,
      el("p", { class: "panel-sub", text: "调用参数" }),
      panelKV(Object.keys(step.args || {}).map(function (k) { return [k, raw(step.args[k])]; })),
      el("p", { class: "panel-sub", text: "这次模型调用" }),
      panelKV([["耗时", llm.latency_ms ? (llm.latency_ms / 1000).toFixed(1) + " 秒" : null], ["tokens（输入 + 输出）", llm.prompt_tokens ? llm.prompt_tokens + " + " + llm.completion_tokens : null]]));
  }
  function panelOutcome(side, out, trace) {
    var s = statusOf(out.status);
    var d = out.draft;
    var corr = (out.validator && out.validator.corrections) || [];
    var usage = (trace && trace.llm_usage) || {};
    return el("div", null,
      panelHead("最终结果", s.label, side),
      el("p", { class: "panel-message", text: out.message }),
      out.facts_summary ? el("div", { class: "facts" }, icon("shield"), el("div", null, el("p", { class: "facts-label", text: "系统核对" }), el("p", { text: out.facts_summary }))) : null,
      panelKV([
        ["草稿", d ? d.draft_id + " · " + d.publish_at + " · " + (DRAFT_STATUS[d.status] || d.status) : "没有保存草稿"],
        ["待确认问题", out.confirmation_question],
        ["缺失信息", (out.missing_fields || []).join("、")],
        ["命中规则", (out.risk_rule_ids || []).join("、")],
        ["校验器更正", corr.length ? corr.length + " 处" : "无（模型结论与草稿库一致）"],
        ["步数", out.run ? out.run.steps_used + " / 上限 " + out.run.max_steps : null],
        ["模型总耗时", usage.latency_ms ? (usage.latency_ms / 1000).toFixed(1) + " 秒" : null]]),
      panelJSON("最终输出（JSON）", out, false));
  }
  function panelValidator(side, out) {
    var corr = (out.validator && out.validator.corrections) || [];
    return el("div", null,
      panelHead("提交之后 · 系统核对", "以草稿库为准，不采信模型的说法", side),
      el("p", { class: "panel-message", text: "模型提交结论后，系统按草稿库逐项核对：草稿是否真的存在、状态是否一致、说明里有没有声称已保存或已发布。" }),
      corr.length ? el("ul", { class: "panel-list" }, corr.map(function (c) { return el("li", { text: fmt(c.from) + " → " + fmt(c.to) + "：" + c.reason }); }))
        : el("p", { class: "validator-ok" }, icon("check"), "这次没有需要更正的地方"),
      out.facts_summary ? el("p", { class: "muted small", text: out.facts_summary }) : null);
  }
  function panelStopped(side, out) {
    var reason = out.run && out.run.end_reason;
    return el("div", null,
      panelHead("运行终止", reason === "llm_error" ? "模型调用失败" : reason === "tool_limit" ? "达到工具调用次数上限" : "达到步数上限", side),
      el("p", { class: "panel-message", text: out.message }),
      panelKV([["已完成的步骤", (out.completed_steps || []).map(function (s) { return toolMeta(s.tool).label; }).join(" → ")]]),
      out.facts_summary && (out.message || "").indexOf(out.facts_summary) < 0 ? el("p", { class: "muted small", text: out.facts_summary }) : null);
  }

  function createGraph(extraClass) {
    var id = "q1g" + (++graphSeq);
    var canvas = el("div", { class: "graph" + (extraClass ? " " + extraClass : "") });
    var svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("class", "graph-edges");
    svg.setAttribute("aria-hidden", "true");
    canvas.appendChild(svg);
    var panel = el("aside", { class: "graph-panel", "aria-live": "polite" });
    var selectables = [], edges = [], order = [];
    var g = {
      canvas: canvas,
      select: function (target, render, quiet) {
        selectables.forEach(function (n) { n.classList.remove("selected"); n.setAttribute("aria-pressed", "false"); });
        target.classList.add("selected");
        target.setAttribute("aria-pressed", "true");
        panel.replaceChildren(render());
        // 详情排在图下方时（窄屏），点完把详情滚进视野
        if (!quiet && panel.getBoundingClientRect().top >= canvas.getBoundingClientRect().bottom - 1) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      },
      // 节点占奇数行，连线上的说明占两节点之间的偶数行：说明有多长就占多高，不截断
      node: function (o, render) {
        var n = el("button", { type: "button", class: "gnode kind-" + o.kind + " side-" + o.side + (o.tool ? " tool-" + (TOOLS[o.tool] ? o.tool : "none") : "") + (o.tone ? " tone-" + o.tone : "") },
          icon(o.icon, "gnode-icon"),
          el("span", { class: "gnode-text" }, el("span", { class: "gnode-title", text: o.title }), o.meta ? el("span", { class: "gnode-meta", text: o.meta }) : null),
          o.badge ? el("span", { class: "node-badge tone-" + o.badge.tone, text: o.badge.text }) : null);
        n.style.gridRow = String(o.row * 2 - 1);
        n.style.gridColumn = gridColumn(o.side);
        n.setAttribute("data-row", String(o.row));
        n.setAttribute("aria-pressed", "false");
        n.addEventListener("click", function () { clearTimers(); g.select(n, render); });
        canvas.appendChild(n);
        selectables.push(n);
        order.push({ el: n, render: render });
        return n;
      },
      edge: function (from, to, side, label, render) {
        if (!label) { edges.push({ from: from, to: to, side: side, arrow: true }); return; }
        var btn = el("button", { type: "button", class: "gedge-label side-" + side + (from.classList.contains("kind-fork") ? " after-fork" : "") },
          icon(label.icon || "spark"), el("span", { text: label.text }));
        btn.style.gridRow = String(Number(to.getAttribute("data-row")) * 2 - 2);
        btn.style.gridColumn = gridColumn(side);
        btn.setAttribute("aria-pressed", "false");
        btn.addEventListener("click", function () { clearTimers(); g.select(btn, render); });
        canvas.insertBefore(btn, to);  // 键盘顺序：先“模型的决定”，再“工具返回”
        selectables.push(btn);
        // 逐步播放也是先看“模型的决定”，再看“工具返回”
        var at = -1;
        for (var i = 0; i < order.length; i++) if (order[i].el === to) { at = i; break; }
        var item = { el: btn, render: render };
        if (at >= 0) order.splice(at, 0, item); else order.push(item);
        edges.push({ from: from, to: btn, side: side, arrow: false });
        edges.push({ from: btn, to: to, side: side, arrow: true });
      },
      layout: function () {
        if (!canvas.isConnected || canvas.offsetParent === null) return;
        var c = canvas.getBoundingClientRect();
        var w = Math.round(c.width), h = Math.round(c.height);
        svg.setAttribute("width", w);
        svg.setAttribute("height", h);
        svg.setAttribute("viewBox", "0 0 " + w + " " + h);
        while (svg.firstChild) svg.removeChild(svg.firstChild);
        var defs = document.createElementNS(SVGNS, "defs");
        ["trunk", "solo", "a", "b"].forEach(function (side) {
          var m = document.createElementNS(SVGNS, "marker");
          m.setAttribute("id", id + "-" + side);
          m.setAttribute("viewBox", "0 0 10 10");
          m.setAttribute("refX", "9");
          m.setAttribute("refY", "5");
          m.setAttribute("markerWidth", "7");
          m.setAttribute("markerHeight", "7");
          m.setAttribute("orient", "auto");
          var tip = document.createElementNS(SVGNS, "path");
          tip.setAttribute("d", "M0,0 L10,5 L0,10 z");
          tip.setAttribute("class", "gmarker-" + side);
          m.appendChild(tip);
          defs.appendChild(m);
        });
        svg.appendChild(defs);
        edges.forEach(function (e) {
          var a = e.from.getBoundingClientRect(), b = e.to.getBoundingClientRect();
          var x1 = a.left - c.left + a.width / 2, y1 = a.bottom - c.top;
          var x2 = b.left - c.left + b.width / 2, y2 = b.top - c.top;
          var mid = (y2 - y1) / 2;
          var p = document.createElementNS(SVGNS, "path");
          p.setAttribute("d", "M" + x1 + "," + y1 + " C" + x1 + "," + (y1 + mid) + " " + x2 + "," + (y2 - mid) + " " + x2 + "," + (y2 - (e.arrow ? 1 : 0)));
          p.setAttribute("class", "gedge gedge-" + e.side);
          if (e.arrow) p.setAttribute("marker-end", "url(#" + id + "-" + e.side + ")");
          svg.appendChild(p);
        });
      },
      play: function () {
        clearTimers();
        order.forEach(function (o, i) {
          timers.push(setTimeout(function () {
            g.select(o.el, o.render, true);
            o.el.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }, i * 1000));
        });
      },
      wrap: function (legendItems) {
        if (graphs.indexOf(g) < 0) graphs.push(g);
        return el("div", { class: "graph-host" }, el("div", { class: "graph-layout" },
          el("div", { class: "graph-main" },
            el("div", { class: "graph-legend" },
              el("span", { class: "legend-item" }, el("span", { class: "legend-node" }), "节点 = 工具返回的结果"),
              el("span", { class: "legend-item" }, el("span", { class: "legend-edge" }, icon("spark")), "连线上的说明 = 模型的决定和理由"),
              legendItems || null),
            el("p", { class: "graph-hint" }, icon("arrow"), "点任意节点或连线上的说明，查看这一步的完整信息"),
            canvas),
          panel));
      }
    };
    if (window.ResizeObserver) new ResizeObserver(function () { g.layout(); }).observe(canvas);
    graphs.push(g);
    return g;
  }
  function decisionLabel(s) { return s.tool ? { text: s.decision_note || "调用" + toolMeta(s.tool).label } : null; }
  function stepNode(g, s, side, row, render) {
    var meta = toolMeta(s.tool);
    return g.node({ kind: "step", side: side, tool: s.tool || "none", icon: meta.icon, title: meta.label, meta: "第 " + s.step + " 步 · " + (s.tool || "—"), badge: nodeBadge(s), row: row }, render);
  }
  function outcomeNode(g, side, out, trace, row, prev) {
    var st = statusOf(out.status);
    var o = g.node({ kind: "outcome", side: side, icon: st.icon, tone: st.tone, title: st.label, row: row,
      meta: out.draft ? out.draft.publish_at + " · " + (DRAFT_STATUS[out.draft.status] || out.draft.status) : "没有保存草稿" }, function () { return panelOutcome(side, out, trace); });
    var stopped = out.run && out.run.end_reason !== "finish";
    g.edge(prev, o, side, stopped ? { text: out.run.end_reason === "llm_error" ? "模型调用失败" : "到达上限，终止", icon: "pause" } : { text: "系统核对", icon: "shield" },
      function () { return stopped ? panelStopped(side, out) : panelValidator(side, out); });
    return o;
  }

  // 一次运行：一条链
  function buildChainGraph(entry, trace, out) {
    var g = createGraph("is-chain");
    var req = entry.request;
    var row = 1;
    var start = g.node({ kind: "start", side: "solo", icon: "file", title: "输入：排期申请单", row: row++,
      meta: req.asset_id + " · " + (CHANNEL[req.channel] || req.channel) + " · " + req.publish_at + (req.instructions ? " · 含补充说明" : "") },
      function () { return panelRequest(req, entry.fault_injection, entry.options); });
    var last = start;
    (trace.steps || []).forEach(function (s) {
      var n = stepNode(g, s, "solo", row++, function () { return panelStep("solo", s, false); });
      g.edge(last, n, "solo", decisionLabel(s), function () { return panelDecision("solo", s, null); });
      last = n;
    });
    var o = outcomeNode(g, "solo", out, trace, row, last);
    g.select(o, function () { return panelOutcome("solo", out, trace); }, true);
    return g;
  }
  // 两次运行：共同的前几步 + 分叉
  function buildForkGraph(o) {
    var g = createGraph();
    var row = 1;
    var start = g.node({ kind: "start", side: "trunk", icon: "file", title: o.startTitle, meta: o.startMeta, row: row++ }, o.startRender);
    var last = start;
    o.ta.steps.slice(0, o.fork).forEach(function (s, i) {
      var sb = o.tb.steps[i];
      var n = stepNode(g, s, "trunk", row++, function () { return panelStep("trunk", s, true); });
      g.edge(last, n, "trunk", decisionLabel(s), function () { return panelDecision("trunk", s, sb); });
      last = n;
    });
    var forkNode = g.node({ kind: "fork", side: "trunk", icon: o.forkIcon || "branch", title: o.forkTitle, meta: o.forkMeta, row: row++ }, o.forkRender);
    g.edge(last, forkNode, "trunk", null);
    var firstRow = row;
    [["a", o.ta, o.oa], ["b", o.tb, o.ob]].forEach(function (x) {
      var side = x[0], t = x[1], out = x[2], r = firstRow, prev = forkNode;
      t.steps.slice(o.fork).forEach(function (s) {
        var n = stepNode(g, s, side, r++, function () { return panelStep(side, s, false); });
        g.edge(prev, n, side, decisionLabel(s), function () { return panelDecision(side, s, null); });
        prev = n;
      });
      outcomeNode(g, side, out, t, r, prev);
    });
    g.select(forkNode, o.forkRender, true);
    return g;
  }
  function sideLegend(labelA, labelB) {
    return [el("span", { class: "legend-item" }, el("span", { class: "side-badge side-a", text: "A" }), labelA),
      el("span", { class: "legend-item" }, el("span", { class: "side-badge side-b", text: "B" }), labelB)];
  }
  function sameStep(sa, sb) {
    return !!(sa && sb && sa.tool === sb.tool && sa.result_summary === sb.result_summary && JSON.stringify(sa.args || {}) === JSON.stringify(sb.args || {}));
  }
  function toggleDetails(root) {
    var all = root.querySelectorAll("details");
    var open = !Array.prototype.some.call(all, function (d) { return d.open; });
    Array.prototype.forEach.call(all, function (d) { d.open = open; });
  }

  // ---- 一个用例：节点图 / 步骤列表 ---------------------------------------------------
  function renderEntry(entry, opts) {
    opts = opts || {};
    clearTimers();
    var traces = runsOf(entry.trace), outs = runsOf(entry.output);
    var title = splitTitle(entry);
    var content = el("div");
    var graph = null;
    var mode = opts.mode || replayMode;
    function buildGraph() {
      if (traces.length > 1) {
        var sc = entry.output.store_check || {};
        return buildForkGraph({
          ta: traces[0], tb: traces[1], oa: outs[0], ob: outs[1], fork: 0,
          startTitle: "输入：排期申请单（提交两次）", startMeta: entry.request.asset_id + " · " + (CHANNEL[entry.request.channel] || entry.request.channel) + " · " + entry.request.publish_at,
          startRender: function () { return panelRequest(entry.request, entry.fault_injection, entry.options); },
          forkTitle: "同一申请提交两次", forkMeta: "共用同一个草稿库", forkIcon: "repeat",
          forkRender: function () {
            return el("div", null, panelHead("两次提交", "同一张申请连续提交两次"),
              el("p", { class: "panel-message", text: "两次提交共用同一个草稿库。第二次运行时，模型看到时段已被同一素材的草稿占用；保存时系统按申请内容认出这是同一份申请，返回已有草稿，没有新建。" }),
              panelKV([["该申请的草稿数", sc.drafts_for_request], ["草稿编号", (sc.draft_ids || []).join("、")], ["草稿库合计", sc.total_drafts_in_store]]));
          }
        });
      }
      return buildChainGraph(entry, traces[0], outs[0]);
    }
    function graphView() {
      if (!graph) graph = buildGraph();
      return graph.wrap(traces.length > 1 ? sideLegend("第 1 次提交", "第 2 次提交") : null);
    }
    function listView(animate) {
      if (traces.length < 2) return renderRun(traces[0], outs[0], animate);
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
      holder.appendChild(renderRun(traces[0], outs[0], animate));
      var sc = entry.output.store_check;
      return el("div", null, tabs,
        sc ? el("p", { class: "store-check" }, icon("shield"), "草稿库核对：申请 " + sc.request_id + " 共 " + sc.drafts_for_request + " 份草稿（" + sc.draft_ids.join("、") + "），草稿库合计 " + sc.total_drafts_in_store + " 份。") : null,
        holder);
    }
    var btnGraph = seg("节点图", "branch", mode === "graph", function () { show("graph"); });
    var btnList = seg("步骤列表", "list", mode === "list", function () { show("list"); });
    var btnExpand = el("button", { type: "button", class: "btn btn-ghost", onclick: function () { toggleDetails(content); } }, icon("expand"), "展开 / 收起返回");
    function show(next, animate) {
      mode = next;
      if (!opts.live) replayMode = next;
      btnGraph.setAttribute("aria-pressed", next === "graph" ? "true" : "false");
      btnList.setAttribute("aria-pressed", next === "list" ? "true" : "false");
      btnExpand.hidden = next === "graph";
      clearTimers();
      content.replaceChildren(next === "graph" ? graphView() : listView(animate));
      if (next === "graph") requestAnimationFrame(function () { graph.layout(); });
    }
    var head = el("header", { class: "detail-head" },
      el("div", null,
        opts.live ? null : el("p", { class: "detail-kicker" }, el("span", { class: "case-no", text: caseNo(entry) })),
        el("h2", { text: title[0] }),
        title[1] ? el("p", { class: "detail-desc", text: title[1] }) : null,
        entry.covers && entry.covers.length ? el("div", { class: "tags" }, entry.covers.map(function (c) { return el("span", { class: "tag tag-brand", text: c }); })) : null),
      el("div", { class: "actions" },
        el("div", { class: "seg-group", role: "group", "aria-label": "显示方式" }, btnGraph, btnList),
        el("button", { type: "button", class: "btn", onclick: function () { if (mode === "graph") { graph.play(); } else { show("list", true); } } }, icon("play"), "逐步播放"),
        btnExpand));
    var body = el("div", { class: "entry" }, head, renderRequest(entry.request, entry.fault_injection, entry.options), content);
    show(mode, opts.animate);
    return body;
  }

  // ---- 对比：两次运行 -------------------------------------------------------------
  function requestRows(ra, rb, pa, pb) {
    var prompt = pa === pb ? ["相同", "相同"] : pa < pb ? ["迭代前", "迭代后"] : ["迭代后", "迭代前"];  // 页面上不显示版本号
    var rows = [
      ["素材", ra.asset_id, rb.asset_id],
      ["渠道", CHANNEL[ra.channel] || ra.channel, CHANNEL[rb.channel] || rb.channel],
      ["申请时间", ra.publish_at, rb.publish_at],
      ["日期不能改", ra.constraints && ra.constraints.date_fixed ? "是" : "否", rb.constraints && rb.constraints.date_fixed ? "是" : "否"],
      ["提示词", prompt[0], prompt[1]]
    ];
    return rows.map(function (r) { return { label: r[0], a: fmt(r[1]), b: fmt(r[2]), diff: fmt(r[1]) !== fmt(r[2]) }; })
      .filter(function (r) { return r.label !== "提示词" || r.diff; });
  }
  function sideTicket(side, label, rows, key, entry) {
    return el("div", { class: "cmp-ticket side-" + side },
      el("div", { class: "cmp-ticket-head" }, el("span", { class: "side-badge", text: side.toUpperCase() }), el("span", { class: "cmp-ticket-label", text: label })),
      el("dl", { class: "cmp-rows" }, rows.map(function (r) {
        return el("div", { class: "cmp-row" + (r.diff ? " diff" : "") }, el("dt", { text: r.label }), el("dd", null, r[key], r.diff ? el("span", { class: "diff-chip", text: "不同" }) : null));
      })),
      el("button", { type: "button", class: "link-btn", onclick: function () { selectCase(entry.case); document.getElementById("view-replay").scrollIntoView({ behavior: "smooth", block: "start" }); } }, "单独看这次运行", icon("arrow")));
  }
  function panelStart(rows) {
    return el("div", null,
      panelHead("输入", "两次运行的申请单"),
      el("table", { class: "panel-table" },
        el("thead", null, el("tr", null, el("th", { text: "" }), el("th", null, el("span", { class: "side-badge side-a", text: "A" })), el("th", null, el("span", { class: "side-badge side-b", text: "B" })))),
        el("tbody", null, rows.map(function (r) { return el("tr", { class: r.diff ? "diff" : null }, el("th", { text: r.label }), el("td", { text: r.a }), el("td", { text: r.b })); }))),
      el("p", { class: "muted small", text: "标色的行是两次运行唯一不同的地方。" }));
  }
  function panelFork(pair, ta, tb, fork) {
    function line(side, s) {
      if (!s) return null;
      var b = nodeBadge(s);
      return el("div", { class: "panel-fork-line" }, el("span", { class: "side-badge side-" + side, text: side.toUpperCase() }),
        el("span", { text: toolMeta(s.tool).label + "：" }), el("span", { class: "pill tone-" + b.tone, text: b.text }));
    }
    return el("div", null,
      panelHead("分叉点", "从第 " + (fork + 1) + " 步开始，两次运行不一样了"),
      el("p", { class: "panel-message", text: pair.forkNote }),
      line("a", ta.steps[fork]), line("b", tb.steps[fork]),
      el("p", { class: "muted small", text: "前 " + fork + " 步两边调用的工具、参数和返回完全相同。点图里的节点看工具返回，点连线上的说明看模型这一步的参数和耗时。" }));
  }
  function trunkStep(step) {
    var meta = toolMeta(step.tool);
    var b = nodeBadge(step);
    return el("li", { class: "trunk-step tool-" + (TOOLS[step.tool] ? step.tool : "none") },
      icon(meta.icon, "tool-icon"),
      el("div", { class: "trunk-body" },
        el("div", { class: "trunk-title" }, el("span", { class: "step-no", text: "第 " + step.step + " 步" }), el("strong", { text: meta.label }), el("code", { text: step.tool }), el("span", { class: "slot-badge tone-" + b.tone, text: b.text })),
        el("p", { class: "trunk-result", text: step.result_summary })),
      el("span", { class: "same-chip" }, icon("check"), "两边相同"));
  }
  function branchStep(step, isFork) {
    var meta = toolMeta(step.tool);
    var keys = ["asset_id", "date", "time", "publish_at", "requires_confirmation", "deep_check", "status"];
    var args = keys.filter(function (k) { return step.args && step.args[k] !== undefined; }).map(function (k) { return k + " = " + raw(step.args[k]); }).join("   ");
    var b = nodeBadge(step);
    return el("li", { class: "bstep tool-" + (TOOLS[step.tool] ? step.tool : "none") + (isFork ? " is-fork" : "") + (step.ok ? "" : " failed") },
      el("div", { class: "bstep-head" }, icon(meta.icon, "tool-icon"),
        el("span", { class: "tool-names" }, el("span", { class: "tool-cn", text: meta.label }), el("code", { class: "tool-en", text: step.tool || "—" })),
        el("span", { class: "step-no", text: "第 " + step.step + " 步" })),
      args ? el("p", { class: "bstep-args", text: args }) : null,
      el("span", { class: "slot-badge tone-" + b.tone, text: b.text }),
      el("p", { class: "bstep-result" + (isFork ? " fork-result" : "") }, isFork ? el("span", { class: "fork-chip", text: step.tool === "finish" ? "提交结果" : "工具返回" }) : null, step.result_summary),
      step.decision_note ? el("p", { class: "bstep-note" }, icon("spark"), el("span", null, el("strong", { text: "模型的理由：" }), step.decision_note)) : null);
  }
  function branchOutcome(out) {
    var s = statusOf(out.status);
    var d = out.draft;
    return el("div", { class: "branch-outcome tone-" + s.tone }, icon(s.icon, "final-icon"),
      el("div", null, el("p", { class: "final-kicker", text: "最终结果" }), el("strong", { text: s.label }),
        el("p", { class: "small", text: d ? "草稿 " + d.draft_id + " · " + d.publish_at + " · " + (DRAFT_STATUS[d.status] || d.status) : "没有保存草稿" })));
  }
  function renderPair(pair) {
    clearTimers();
    var A = findCase(pair.a), B = findCase(pair.b);
    if (!A || !B) return el("p", { class: "card", text: "缺少对比所需的录制。" });
    var ta = runsOf(A.trace)[0], tb = runsOf(B.trace)[0], oa = runsOf(A.output)[0], ob = runsOf(B.output)[0];
    var fork = 0;
    while (fork < Math.min(ta.steps.length, tb.steps.length) && sameStep(ta.steps[fork], tb.steps[fork])) fork++;
    var rows = requestRows(A.request, B.request, ta.prompt_version, tb.prompt_version);
    var graph = buildForkGraph({
      ta: ta, tb: tb, oa: oa, ob: ob, fork: fork,
      startTitle: "输入：申请单", startMeta: pair.startMeta, startRender: function () { return panelStart(rows); },
      forkTitle: "分叉点", forkMeta: "第 " + (fork + 1) + " 步起不同", forkRender: function () { return panelFork(pair, ta, tb, fork); }
    });
    var branch = function (side, label, trace, out) {
      return el("div", { class: "branch side-" + side },
        el("div", { class: "branch-head" }, el("span", { class: "side-badge", text: side.toUpperCase() }), el("span", { text: label })),
        el("ol", { class: "branch-steps" }, trace.steps.slice(fork).map(function (s, i) { return branchStep(s, i === 0); })),
        branchOutcome(out));
    };
    var listView = el("div", { class: "cmp-list" },
      fork ? el("ol", { class: "trunk" }, ta.steps.slice(0, fork).map(trunkStep)) : null,
      el("div", { class: "fork-banner" }, icon("branch"), el("span", null, el("strong", { text: "分叉点 · 第 " + (fork + 1) + " 步  " }), pair.forkNote)),
      el("div", { class: "fork-lines", "aria-hidden": "true" }),
      el("div", { class: "branches" }, branch("a", pair.labelA, ta, oa), branch("b", pair.labelB, tb, ob)));
    var processBox = el("div");
    var btnGraph = seg("节点图", "branch", replayMode === "graph", function () { show("graph"); });
    var btnList = seg("步骤列表", "list", replayMode === "list", function () { show("list"); });
    function show(next) {
      replayMode = next;
      btnGraph.setAttribute("aria-pressed", next === "graph" ? "true" : "false");
      btnList.setAttribute("aria-pressed", next === "list" ? "true" : "false");
      clearTimers();
      processBox.replaceChildren(next === "graph" ? graph.wrap(sideLegend(pair.labelA, pair.labelB)) : listView);
      if (next === "graph") requestAnimationFrame(graph.layout);
    }
    var section = el("section", { class: "cmp" },
      el("header", { class: "detail-head" },
        el("div", null,
          el("p", { class: "detail-kicker" }, el("span", { class: "case-no case-no-vs", text: "VS" }), el("span", { class: "tag tag-brand" }, icon("flag"), pair.checkpoint)),
          el("h2", { text: pair.title }),
          el("p", { class: "detail-desc", text: pair.subtitle })),
        el("div", { class: "actions" },
          el("div", { class: "seg-group", role: "group", "aria-label": "显示方式" }, btnGraph, btnList),
          el("button", { type: "button", class: "btn", onclick: function () { if (replayMode !== "graph") show("graph"); requestAnimationFrame(graph.play); } }, icon("play"), "逐步播放"))),
      el("div", { class: "cmp-section-title", text: "① 输入：两次运行的申请单" }),
      el("div", { class: "cmp-inputs" }, sideTicket("a", pair.labelA, rows, "a", A), el("div", { class: "cmp-vs", text: "VS" }), sideTicket("b", pair.labelB, rows, "b", B)),
      pair.change ? el("p", { class: "cmp-change" }, icon("edit"), el("span", { text: pair.change })) : null,
      el("div", { class: "cmp-section-title", text: fork ? "② 过程：前 " + fork + " 步相同，第 " + (fork + 1) + " 步开始分叉" : "② 过程：从第 1 步就不同" }),
      processBox,
      el("div", { class: "cmp-section-title", text: "③ 结论" }),
      el("div", { class: "cmp-takeaway" }, icon("bulb"), el("p", { text: pair.takeaway })));
    show(replayMode);
    return section;
  }

  // ---- 回放视图：用例列表 + 详情 ---------------------------------------------------
  function renderCaseList(activeId) {
    var box = document.getElementById("case-list");
    box.replaceChildren();
    function item(entry) {
      var title = splitTitle(entry);
      return el("button", { type: "button", class: "case-item" + (entry.case === activeId ? " active" : ""), "aria-current": entry.case === activeId ? "true" : null, onclick: function () { selectCase(entry.case); } },
        el("span", { class: "case-no", text: caseNo(entry) }),
        el("span", { class: "case-name", text: title[0] }),
        el("span", { class: "case-meta" }, pill(lastStatus(entry)), el("span", { class: "case-desc", text: title[1] })));
    }
    function pairItem(pair) {
      return el("button", { type: "button", class: "case-item pair-item" + (pair.id === activeId ? " active" : ""), "aria-current": pair.id === activeId ? "true" : null, onclick: function () { selectCase(pair.id); } },
        el("span", { class: "case-no case-no-vs", text: "VS" }),
        el("span", { class: "case-name", text: pair.listTitle }),
        el("span", { class: "case-meta" }, el("span", { class: "pill tone-info" }, icon("compare"), "对比"), el("span", { class: "case-desc", text: pair.listDesc })));
    }
    box.appendChild(el("h2", { class: "list-title", text: "验收用例 · " + DATA.cases.length }));
    DATA.cases.forEach(function (c) { box.appendChild(item(c)); });
    box.appendChild(el("h2", { class: "list-title", text: "两次运行对比" }));
    COMPARE_PAIRS.forEach(function (p) { box.appendChild(pairItem(p)); });
  }
  function selectCase(id, keepView) {
    var pair = findPair(id);
    var entry = pair ? null : (findCase(id) || DATA.cases[0]);
    if (!pair && !entry) return;
    var key = pair ? pair.id : entry.case;
    renderCaseList(key);
    document.getElementById("case-detail").replaceChildren(pair ? renderPair(pair) : renderEntry(entry));
    if (keepView) return;
    setHash("case=" + key);
    showView("replay");
  }

  // ---- 数据接入（规划中的入口）--------------------------------------------------------
  function sourceByName(name) { return DATA_SOURCES.filter(function (s) { return s.name === name; })[0]; }
  function showPlan(source, action) {
    var dlg = document.getElementById("plan-dialog");
    if (!dlg) {
      dlg = el("dialog", { id: "plan-dialog", class: "plan-dialog", "aria-labelledby": "plan-title" });
      dlg.addEventListener("click", function (ev) { if (ev.target === dlg) dlg.close(); });
      document.body.appendChild(dlg);
    }
    dlg.replaceChildren(
      el("div", { class: "plan-head" }, icon(source.icon, "plan-icon"),
        el("div", null, el("p", { class: "panel-kicker" }, source.name, el("span", { class: "pill tone-muted", text: "规划中 · 尚未实现" })), el("h3", { id: "plan-title", text: action.label }))),
      el("p", { class: "plan-text" }, el("strong", { text: "接入后：" }), action.plan),
      el("p", { class: "plan-text muted" }, el("strong", { text: "现在：" }), action.now),
      el("form", { method: "dialog", class: "plan-actions" }, el("button", { type: "submit", class: "btn" }, "知道了")));
    if (typeof dlg.showModal === "function") dlg.showModal();
    else window.alert(action.label + "：规划中，尚未实现。" + action.now);
  }
  function planButton(sourceName, actionLabel) {
    var source = sourceByName(sourceName);
    var action = source.actions.filter(function (a) { return a.label === actionLabel; })[0];
    return el("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: function () { showPlan(source, action); } },
      icon(actionLabel.indexOf("同步") >= 0 ? "repeat" : actionLabel.indexOf("导入") >= 0 ? "upload" : "link"), actionLabel);
  }
  var dataRendered = false;
  function renderData() {
    if (dataRendered) return;
    dataRendered = true;
    var view = document.getElementById("view-data");
    var groups = [];
    DATA_SOURCES.forEach(function (s) { if (groups.indexOf(s.group) < 0) groups.push(s.group); });
    view.replaceChildren(el("header", { class: "cmp-intro" }, el("h2", { text: "数据接入" }),
      el("p", { text: "Agent 通过四个工具读写数据：读素材、查规则和版权、查发布日历、写排期草稿。演示版用内置的示例数据跑通全流程；下面是接入真实系统的入口，目前都还没有实现。" })));
    groups.forEach(function (gname) {
      view.appendChild(el("section", { class: "ds-group" }, el("h3", { class: "ds-group-title", text: gname }),
        el("div", { class: "ds-grid" }, DATA_SOURCES.filter(function (s) { return s.group === gname; }).map(function (s) {
          return el("article", { class: "card ds-card" },
            el("div", { class: "ds-head" }, icon(s.icon, "ds-icon"), el("div", null, el("h4", { text: s.name }), el("span", { class: "pill " + (s.status === "演示数据" ? "tone-info" : "tone-muted"), text: s.status }))),
            el("p", { class: "ds-desc", text: s.desc }),
            s.tools ? el("p", { class: "ds-tools" }, "用到它的工具：", s.tools.map(function (t) { return el("span", { class: "ds-tool tool-" + t }, icon(TOOLS[t].icon), TOOLS[t].label); })) : null,
            el("div", { class: "ds-actions" }, s.actions.map(function (a) { return planButton(s.name, a.label); }), el("span", { class: "ds-planned", text: "规划中" })));
        }))));
    });
  }

  // ---- 新建任务：用真实模型现场跑一次 -----------------------------------------------------
  var taskRendered = false;
  function renderTask(health) {
    if (taskRendered) return;
    taskRendered = true;
    var view = document.getElementById("view-task");
    if (!health.live_enabled) {
      view.replaceChildren(el("p", { class: "card", text: "新建任务暂不可用，可以先看“运行回放”。" }));
      return;
    }
    var f = {
      asset: el("input", { id: "f-asset", list: "asset-ids", maxlength: "12", required: true }),
      channel: el("select", { id: "f-channel" }, Object.keys(CHANNEL).map(function (k) { return el("option", { value: k, text: CHANNEL[k] }); })),
      date: el("input", { id: "f-date", type: "date", required: true }),
      time: el("select", { id: "f-time" }, ["09:00", "12:00", "18:00", "19:00", "20:00", "21:00"].map(function (t) { return el("option", { value: t, text: t }); })),
      fixed: el("input", { id: "f-fixed", type: "checkbox" }),
      note: el("input", { id: "f-note", maxlength: "200", placeholder: "可选" }),
      instr: el("textarea", { id: "f-instr", maxlength: "300", rows: "3", "aria-label": "补充说明", placeholder: "像跟助手说话一样补充要求，例如：如果 18:00 被占，优先排到 20:00 以后" }),
      fault: el("select", { id: "f-fault" }, [["", "无"], ["error", "save_draft 一直失败"], ["error_once", "save_draft 第一次失败"], ["timeout_after_commit", "save_draft 超时但已写入"]].map(function (o) { return el("option", { value: o[0], text: o[1] }); })),
      repeat: el("input", { id: "f-repeat", type: "checkbox" }),
      code: el("input", { id: "f-code", type: "password", autocomplete: "off" })
    };
    var datalist = el("datalist", { id: "asset-ids" }, ["M01", "M02", "M03", "M04", "M05", "M06", "M07"].map(function (a) { return el("option", { value: a }); }));
    var liveCases = DATA.cases.filter(function (c) { return !(c.options && c.options.max_steps); });  // “步数上限”只在回放里展示
    var current = liveCases[0] ? liveCases[0].case : null;
    var picker = el("div", { class: "scenario-grid", role: "radiogroup", "aria-label": "选择场景" });
    liveCases.forEach(function (c) {
      var t = splitTitle(c);
      picker.appendChild(el("button", { type: "button", class: "scenario", role: "radio", "aria-checked": "false", "data-case": c.case, onclick: function () { choose(c.case); exampleNote.hidden = true; } },
        el("span", { class: "case-no", text: caseNo(c) }),
        el("span", { class: "scenario-text" }, el("span", { class: "scenario-name", text: t[0] }), el("span", { class: "scenario-desc", text: t[1] }))));
    });
    function field(label, input, hint, cls) { return el("label", { class: "field" + (cls ? " " + cls : "") }, el("span", { text: label }), input, hint ? el("span", { class: "field-hint", text: hint }) : null); }
    function check(label, input, hint) { return el("label", { class: "field field-check" }, input, el("span", null, el("span", { class: "check-label", text: label }), hint ? el("span", { class: "field-hint", text: hint }) : null)); }
    var counter = el("span", { class: "composer-count", text: "0 / 300" });
    function count() { counter.textContent = f.instr.value.length + " / 300"; }
    f.instr.addEventListener("input", count);
    var exampleNote = el("p", { class: "composer-note", role: "status", hidden: true });
    var examples = el("div", { class: "composer-examples" }, el("span", { class: "muted small", text: "试试：" }),
      EXAMPLE_INSTRUCTIONS.map(function (ex) {
        return el("button", { type: "button", class: "chip", onclick: function () {
          f.instr.value = ex.text;
          count();
          exampleNote.hidden = true;
          if (ex.scenario && ex.scenario !== current) {
            var c = findCase(ex.scenario);
            choose(ex.scenario);
            exampleNote.textContent = "已切换到场景 " + caseNo(c) + "「" + splitTitle(c)[0] + "」：这条要求在这个场景里最能看出效果。";
            exampleNote.hidden = false;
          }
          f.instr.focus();
        } }, ex.text);
      }));
    var knobs = el("div", { class: "tags knob-tags" });
    function refresh() {
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
    [f.fault, f.repeat].forEach(function (input) { input.addEventListener("change", refresh); });

    var status = el("p", { class: "live-status", role: "status" });
    var button = el("button", { type: "submit", class: "btn btn-lg composer-send" }, icon("send"), "开始运行");
    var resultBox = el("div", { class: "task-result-body" },
      el("div", { class: "task-empty" }, icon("branch"), el("p", { text: "提交后，这里会画出这次运行的节点图：模型每一步的决定、工具返回和最终结果。" })));
    var form = el("form", { class: "card task-composer", onsubmit: function (ev) { ev.preventDefault(); submit(); } },
      el("div", { class: "task-head" }, icon("plus", "task-icon"),
        el("div", null, el("h2", { text: "新建排期任务" }), el("p", { class: "muted", text: "选一个场景或自己填申请单，还可以用一句话补充要求。Agent 会用真实模型现场跑一遍，只保存草稿，不会发布。" }))),
      el("div", { class: "task-section" }, el("h3", { class: "task-step" }, el("span", { class: "task-step-no", text: "1" }), "选择场景"), picker),
      el("div", { class: "task-section" },
        el("div", { class: "task-section-head" }, el("h3", { class: "task-step" }, el("span", { class: "task-step-no", text: "2" }), "申请单"),
          el("div", { class: "source-bar" }, el("span", { class: "muted small", text: "素材和日程来自演示数据" }), planButton("素材库", "导入素材"), planButton("发布日历", "同步渠道日程"))),
        el("div", { class: "task-fields" }, field("素材 ID", f.asset), datalist, field("渠道", f.channel), field("日期", f.date), field("时段", f.time),
          check("日期不能改", f.fixed, "勾选后 Agent 不会擅自改到其他日期"), field("备注（可选）", f.note, null, "field-wide"))),
      el("div", { class: "task-section" },
        el("h3", { class: "task-step" }, el("span", { class: "task-step-no", text: "3" }), "补充说明", el("span", { class: "task-step-opt", text: "可选" })),
        el("p", { class: "muted small task-note", text: "这是工作流 Agent：流程和硬约束是固定的。你写的话会作为申请人的额外要求交给模型，只能补充偏好，改变不了规则。" }),
        el("div", { class: "composer" }, f.instr,
          el("div", { class: "composer-bar" }, counter, status, health.access_code_required ? field("访问口令", f.code, null, "field-inline") : null, button)),
        examples, exampleNote),
      el("details", { class: "fold" }, el("summary", null, icon("list"), "高级：测试开关（选场景时已自动设置）"),
        el("div", { class: "fold-grid" }, field("故障注入", f.fault, "模拟保存草稿时的存储故障"), check("连续提交两次", f.repeat, "同一申请提交两次，验证只产生一份草稿"))),
      knobs);
    choose(current);

    function submit() {
      var payload = {
        case_id: current,
        request: {
          asset_id: f.asset.value.trim(), channel: f.channel.value, publish_at: f.date.value + " " + f.time.value,
          note: f.note.value, instructions: f.instr.value.trim(), constraints: { date_fixed: f.fixed.checked }
        },
        fault_injection: f.fault.value ? { save_draft: f.fault.value } : {},
        repeat: f.repeat.checked ? 2 : 1
      };
      if (health.access_code_required) payload.access_code = f.code.value;
      button.disabled = true;
      var started = Date.now();
      var label = el("span", { text: "运行中…" });
      status.replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), label);
      var tick = setInterval(function () { label.textContent = "运行中，已等待 " + Math.round((Date.now() - started) / 1000) + " 秒…"; }, 500);
      fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
        .then(function (resp) { return resp.json().then(function (body) { return { status: resp.status, body: body }; }); })
        .then(function (r) {
          if (r.body.ok) {
            status.replaceChildren(icon("check"), "完成，用时 " + r.body.elapsed_s + " 秒。");
            var req = r.body.case.request;
            var entry = { case: r.body.case.case, title: "本次运行：" + req.asset_id + " · " + (CHANNEL[req.channel] || req.channel) + " · " + req.publish_at, covers: [], request: req,
              fault_injection: r.body.case.fault_injection, options: r.body.case.options, output: r.body.output, trace: r.body.trace };
            resultBox.replaceChildren(renderEntry(entry, { mode: "graph", live: true }));
            resultBox.parentNode.scrollIntoView({ behavior: "smooth", block: "start" });
          } else {
            var err = r.body.error || {};
            status.replaceChildren(icon("alert"), err.message || ("请求失败（HTTP " + r.status + "）"));
            if (err.fallback === "replay") {
              resultBox.replaceChildren(el("p", { class: "task-empty" }, "可以先看这个场景的真实录制：",
                el("button", { type: "button", class: "btn btn-ghost", onclick: function () { selectCase(current); } }, icon("play"), "查看回放")));
            }
          }
        })
        .catch(function () { status.replaceChildren(icon("alert"), "网络错误，可以先看运行回放。"); })
        .then(function () { clearInterval(tick); button.disabled = false; });
    }
    view.replaceChildren(form, el("section", { class: "card task-result" }, el("h3", { class: "card-title" }, icon("branch"), "运行结果"), resultBox));
  }

  // ---- 视图切换与启动 ------------------------------------------------------------
  function showView(name) {
    ["replay", "data", "task"].forEach(function (v) {
      document.getElementById("view-" + v).hidden = v !== name;
      Array.prototype.forEach.call(document.querySelectorAll('[data-view="' + v + '"]'), function (tab) {
        if (tab.getAttribute("role") === "tab") tab.setAttribute("aria-selected", v === name ? "true" : "false");
        else tab.classList.toggle("active", v === name);
      });
    });
    requestAnimationFrame(layoutGraphs);
  }
  function setHash(h) { if (history.replaceState) history.replaceState(null, "", "#" + h); }

  function boot() {
    renderUSP();
    renderStats();
    renderPipeline();
    document.getElementById("tab-task").prepend(icon("plus"));
    var health = null;
    Array.prototype.forEach.call(document.querySelectorAll("[data-view]"), function (tab) {
      tab.addEventListener("click", function () {
        var v = tab.getAttribute("data-view");
        if (v === "data") renderData();
        if (v === "task" && health) renderTask(health);
        showView(v);
        setHash("view=" + v);
      });
    });
    window.addEventListener("hashchange", function () {
      var h = location.hash.slice(1);
      if (h.indexOf("case=") === 0) selectCase(decodeURIComponent(h.slice(5)));
    });
    var hash = location.hash.slice(1);
    if (hash === "view=compare") hash = "case=cmp-date";  // 旧链接
    if (hash === "view=live") hash = "view=task";
    if (hash.indexOf("view=") === 0) {
      selectCase(null, true);
      if (hash === "view=data") { renderData(); showView("data"); }
    } else {
      selectCase(hash.indexOf("case=") === 0 ? decodeURIComponent(hash.slice(5)) : null);
    }
    // GitHub Pages 是纯静态托管，没有接口，不发探测请求
    if ((location.protocol === "http:" || location.protocol === "https:") && !/\.github\.io$/.test(location.hostname)) {
      var ctrl = window.AbortController ? new AbortController() : null;
      if (ctrl) setTimeout(function () { ctrl.abort(); }, 4000);
      fetch("/api/health", ctrl ? { signal: ctrl.signal } : {})
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (h) {
          if (!h || h.service !== "xiaoying-agent") return;
          health = h;
          document.getElementById("tab-task").hidden = false;
          if (hash === "view=task") { renderTask(health); showView("task"); setHash("view=task"); }
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
