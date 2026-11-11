"""Q1 业务工具：read_asset / check_rules / query_slots / save_draft / finish。

“模型做决策，代码守边界”里的边界都在这里，由代码强制执行：
- 不存在发布工具；草稿状态只有 scheduled_draft / pending_confirmation；
- save_draft 之前必须通过规则检查：阻断、待补查、缺信息都不能保存；
- 发布时间偏离申请时自动标记待确认；申请单写明日期不能改时拒绝改日期；
- 按内容哈希幂等，一张申请单最多一份草稿；时段已被占用时拒绝写入；
- 每次工具调用记入台账（ledger），校验器据此和草稿库核对最终状态。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from agent.tools import DECISION_NOTE, Tool, ToolError, ToolExecution, ToolRegistry

from .faults import FaultInjector
from .rules import FIELD_LABELS, evaluate, missing_fields
from .store import DataStore, DraftConflict, StorageError

CST = timezone(timedelta(hours=8))
CHANNELS = ("douyin", "wechat_channels", "xiaohongshu")
CHANNEL_ALIASES = {"抖音": "douyin", "视频号": "wechat_channels", "微信视频号": "wechat_channels", "小红书": "xiaohongshu"}
DRAFT_STATUSES = ("scheduled_draft", "pending_confirmation")
MODEL_STATUSES = ("completed", "needs_input", "needs_confirmation", "blocked", "failed")
# 这些错误表示“保存没有确认成功”：最终没有草稿时，状态一律按 failed 处理
SAVE_FAILURE_CODES = {"STORAGE_UNAVAILABLE", "TIMEOUT", "INTERNAL_ERROR"}
_PUBLISH_AT = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})$")

CHANNEL_PARAM = {"type": "string", "enum": list(CHANNELS), "description": "发布渠道：douyin=抖音，wechat_channels=视频号，xiaohongshu=小红书"}


# ---- 申请单规范化 ---------------------------------------------------------
def normalize_channel(value) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return CHANNEL_ALIASES.get(text, text.lower())


def normalize_publish_at(value) -> str | None:
    if value in (None, ""):
        return None
    match = _PUBLISH_AT.match(str(value).strip())
    return f"{match.group(1)} {match.group(2)}" if match else str(value).strip()


def normalize_request(request: dict) -> dict:
    req = dict(request)
    if req.get("asset_id"):
        req["asset_id"] = str(req["asset_id"]).strip().upper()
    req["channel"] = normalize_channel(req.get("channel"))
    req["publish_at"] = normalize_publish_at(req.get("publish_at"))
    req["constraints"] = dict(req.get("constraints") or {})
    if not req.get("request_id"):
        basis = f"{req.get('asset_id')}|{req.get('channel')}|{req.get('publish_at')}"
        req["request_id"] = "REQ-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:8].upper()
    return req


def idempotency_key(asset_id: str, asset_version, channel: str, requested_publish_at: str) -> str:
    """幂等键 = 申请内容（素材 + 素材版本 + 渠道 + 申请的发布时间）的哈希。

    用申请时间而不是模型最终选的时段：同一张申请重复提交时，即使模型这次选了别的时段，也只会返回已有草稿。
    不含申请单号：两次点提交生成了不同单号也算重复。
    """
    return hashlib.sha256(f"{asset_id}|v{asset_version}|{channel}|{requested_publish_at}".encode("utf-8")).hexdigest()


def _is_date(text: str) -> bool:
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


# ---- 工具会话 -------------------------------------------------------------
class SchedulingSession:
    """一次排期申请的工具会话：申请单、数据、故障注入、调用台账都在这里。"""

    def __init__(self, store: DataStore, request: dict, fault_injection: dict | None = None):
        self.store = store
        self.request = normalize_request(request)
        self.faults = FaultInjector(fault_injection)
        self.fault_injection = dict(fault_injection or {})
        self.ledger: list[ToolExecution] = []
        self.rule_state: dict[tuple[str, str], dict] = {}
        self.created_draft_ids: list[str] = []
        self.used_keys: list[str] = []
        self.registry = ToolRegistry(self._tools(), observer=self.ledger.append)

    # ---- 工具定义 ---------------------------------------------------------
    def _tools(self) -> list[Tool]:
        slot_list = "、".join(self.store.slot_times)
        return [
            Tool(
                "read_asset",
                "读取素材库中的素材详情：标题、类型、时长、文案、封面、背景音乐及授权状态、版本号。"
                "missing_fields 列出缺失的必填信息（为空表示齐全）。",
                {
                    "type": "object",
                    "properties": {"asset_id": {"type": "string", "description": "素材 ID，例如 M01"}, "decision_note": DECISION_NOTE},
                    "required": ["asset_id", "decision_note"],
                    "additionalProperties": False,
                },
                self.read_asset,
            ),
            Tool(
                "check_rules",
                "按发布渠道的内容规范检查素材，结论由规则引擎给出。verdict：pass=通过；warn=有提示但不影响排期；"
                "needs_verification=有需要补查的项（例如音乐授权状态待确认），可再次调用并设置 deep_check=true 查询版权库；"
                "block=存在必须阻断发布的问题；incomplete=必填信息缺失。保存草稿前必须先通过这项检查。",
                {
                    "type": "object",
                    "properties": {
                        "asset_id": {"type": "string", "description": "素材 ID"},
                        "channel": CHANNEL_PARAM,
                        "deep_check": {"type": "boolean", "description": "是否补查外部记录（版权库），默认 false"},
                        "decision_note": DECISION_NOTE,
                    },
                    "required": ["asset_id", "channel", "decision_note"],
                    "additionalProperties": False,
                },
                self.check_rules,
            ),
            Tool(
                "query_slots",
                f"查询发布日历。每天固定 {slot_list} 六个时段，每个时段只能排一条内容。"
                "传 time 只返回该时段；不传 time 返回当天全部时段和 free_slots。"
                "status=free 表示空闲，occupied 表示已占用（occupied_by 说明被谁占用）。",
                {
                    "type": "object",
                    "properties": {
                        "channel": CHANNEL_PARAM,
                        "date": {"type": "string", "pattern": r"\d{4}-\d{2}-\d{2}", "description": "日期，YYYY-MM-DD"},
                        "time": {"type": "string", "pattern": r"\d{2}:\d{2}", "description": "可选，时段 HH:MM"},
                        "decision_note": DECISION_NOTE,
                    },
                    "required": ["channel", "date", "decision_note"],
                    "additionalProperties": False,
                },
                self.query_slots,
            ),
            Tool(
                "save_draft",
                "把排期保存为草稿，不会发布（系统没有发布能力，发布需要人工在发布系统操作）。"
                "按申请内容幂等：同一素材（同一版本）、渠道、申请时间只会有一份草稿，重复保存（哪怕选了别的时段）都返回已有草稿（created=false）。"
                "发布时间与申请时间不一致时必须设置 requires_confirmation=true，草稿进入待确认状态；"
                "申请单标注日期不能改时，不能保存到其他日期。",
                {
                    "type": "object",
                    "properties": {
                        "asset_id": {"type": "string", "description": "素材 ID"},
                        "channel": CHANNEL_PARAM,
                        "publish_at": {"type": "string", "pattern": r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", "description": "发布时间，YYYY-MM-DD HH:MM"},
                        "requires_confirmation": {"type": "boolean", "description": "是否需要申请人确认（时间与申请不一致时必须为 true）"},
                        "change_reason": {"type": "string", "description": "时间与申请不一致时，说明调整原因"},
                        "decision_note": DECISION_NOTE,
                    },
                    "required": ["asset_id", "channel", "publish_at", "requires_confirmation", "decision_note"],
                    "additionalProperties": False,
                },
                self.save_draft,
            ),
            Tool(
                "finish",
                "结束本次处理并提交结构化结果。只能依据工具实际返回的结果填写；草稿编号必须来自 save_draft 的返回。",
                {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": list(MODEL_STATUSES),
                            "description": "completed=已按申请保存排期草稿；needs_confirmation=已保存待确认草稿，或需要申请人同意变更；"
                            "needs_input=信息缺失需要补充；blocked=规则风险阻断；failed=工具失败等原因未能完成",
                        },
                        "message": {"type": "string", "description": "给申请人的中文说明（2~4 句）：结果、依据、需要对方做什么"},
                        "draft_id": {"type": "string", "description": "草稿编号（仅当 save_draft 成功返回过）"},
                        "publish_at": {"type": "string", "description": "草稿的发布时间（如有）"},
                        "missing_fields": {"type": "array", "items": {"type": "string"}, "description": "缺失的信息"},
                        "risk_rule_ids": {"type": "array", "items": {"type": "string"}, "description": "命中的规则编号，例如 R02"},
                        "confirmation_question": {"type": "string", "description": "需要申请人确认的问题"},
                        "decision_note": DECISION_NOTE,
                    },
                    "required": ["status", "message", "decision_note"],
                    "additionalProperties": False,
                },
                lambda **kwargs: kwargs,  # finish 由 Agent 循环拦截，不会真正执行
            ),
        ]

    # ---- 公共校验 ---------------------------------------------------------
    def _asset(self, asset_id: str) -> dict:
        asset = self.store.get_asset(str(asset_id).strip().upper())
        if asset is None:
            raise ToolError("ASSET_NOT_FOUND", f"素材库中没有 {asset_id}，请确认素材 ID")
        return asset

    def _channel(self, channel: str) -> str:
        code = normalize_channel(channel)
        if code not in CHANNELS:
            raise ToolError("INVALID_CHANNEL", f"不支持的渠道 {channel}，可选：{', '.join(CHANNELS)}", retryable=True)
        return code

    def request_key(self) -> str | None:
        """按申请内容计算的幂等键；申请单缺字段或素材不存在时为 None。"""
        req = self.request
        asset = self.store.get_asset(req.get("asset_id") or "")
        if not asset or not req.get("channel") or not req.get("publish_at"):
            return None
        return idempotency_key(asset["asset_id"], asset["version"], req["channel"], req["publish_at"])

    # ---- 工具实现 ---------------------------------------------------------
    def read_asset(self, asset_id: str) -> dict:
        self.faults.before("read_asset")
        asset = self._asset(asset_id)
        missing = missing_fields(asset, self.store.rules)
        return {
            "asset": asset,
            "missing_fields": missing,
            "missing_labels": [FIELD_LABELS.get(f, f) for f in missing],
            "complete": not missing,
        }

    def check_rules(self, asset_id: str, channel: str, deep_check: bool = False) -> dict:
        self.faults.before("check_rules")
        asset = self._asset(asset_id)
        code = self._channel(channel)
        result = evaluate(asset, code, self.store, deep=deep_check)
        self.rule_state[(asset["asset_id"], code)] = result
        return result

    def query_slots(self, channel: str, date: str, time: str | None = None) -> dict:
        self.faults.before("query_slots")
        code = self._channel(channel)
        if not _is_date(date):
            raise ToolError("INVALID_DATE", f"日期 {date} 不合法，格式应为 YYYY-MM-DD", retryable=True)
        times = self.store.slot_times
        if time is not None and time not in times:
            raise ToolError("INVALID_SLOT", f"{time} 不是可排期时段，可选：{'、'.join(times)}", retryable=True)
        slots = []
        for t in [time] if time else times:
            occupant = self.store.slot_occupant(code, date, t)
            slot = {"time": t, "status": "occupied" if occupant else "free"}
            if occupant:
                slot["occupied_by"] = occupant
            slots.append(slot)
        data = {"channel": code, "channel_name": self.store.channel(code)["name"], "date": date, "slots": slots}
        if time is None:
            data["free_slots"] = [s["time"] for s in slots if s["status"] == "free"]
        return data

    def save_draft(self, asset_id: str, channel: str, publish_at: str, requires_confirmation: bool, change_reason: str | None = None) -> dict:
        req = self.request
        asset = self._asset(asset_id)
        code = self._channel(channel)
        when = normalize_publish_at(publish_at) or ""

        if asset["asset_id"] != req.get("asset_id") or code != req.get("channel"):
            raise ToolError("REQUEST_MISMATCH", f"本次申请是 {req.get('asset_id')} 在 {req.get('channel')} 的排期，不能保存其他素材或渠道的草稿")
        match = _PUBLISH_AT.match(when)
        if not match or not _is_date(match.group(1)) or match.group(2) not in self.store.slot_times:
            raise ToolError("INVALID_SLOT", f"发布时间 {publish_at} 不合法：格式 YYYY-MM-DD HH:MM，时段只能是 {'、'.join(self.store.slot_times)}", retryable=True)
        date, time = match.group(1), match.group(2)

        rule = self.rule_state.get((asset["asset_id"], code))
        if rule is None:
            raise ToolError("RULE_CHECK_REQUIRED", "保存草稿前必须先对该素材在该渠道做规则检查（check_rules）", retryable=True)
        if rule["verdict"] == "block":
            hits = "；".join(f["message"] for f in rule["findings"] if f["level"] == "block")
            raise ToolError("ASSET_BLOCKED", f"规则检查存在阻断项，不能排期：{hits}")
        if rule["verdict"] == "incomplete":
            raise ToolError("ASSET_INCOMPLETE", "素材缺少必填信息，不能排期，请先让申请人补齐")
        if rule["verdict"] == "needs_verification":
            raise ToolError("VERIFICATION_REQUIRED", "规则检查还有待补查项，需要先用 deep_check=true 补查通过才能保存", retryable=True)

        requested = req.get("publish_at")
        requested_date = requested.split(" ")[0] if requested else None
        if req["constraints"].get("date_fixed") and requested_date and date != requested_date:
            raise ToolError(
                "HARD_CONSTRAINT_DATE",
                f"申请单要求日期不能改（{requested_date}），未经申请人同意不能改到 {date}；如需换日期，请先向申请人请求确认",
            )
        deviates = when != requested
        needs_confirmation = bool(requires_confirmation) or deviates

        self.faults.before("save_draft")  # 存储故障发生在写入之前：什么都没写
        key = self.request_key() or idempotency_key(asset["asset_id"], asset["version"], code, when)
        self.used_keys.append(key)
        draft = {
            "draft_id": "D-" + key[:8].upper(),
            "idempotency_key": key,
            "request_id": req["request_id"],
            "asset_id": asset["asset_id"],
            "asset_version": asset["version"],
            "title": asset["title"],
            "channel": code,
            "publish_at": when,
            "requested_publish_at": requested,
            "status": "pending_confirmation" if needs_confirmation else "scheduled_draft",
            "change_reason": change_reason,
            "rule_verdict": rule["verdict"],
            "warnings": [f["message"] for f in rule["findings"] if f["level"] == "warn"],
            "created_at": datetime.now(CST).isoformat(timespec="seconds"),
        }
        try:  # 查重、查申请单、查时段占用和写入在存储层的同一个临界区里完成
            saved, created = self.store.insert_draft(draft)
        except DraftConflict as exc:
            if exc.code == "REQUEST_ALREADY_HAS_DRAFT":
                other = exc.detail
                raise ToolError(
                    "REQUEST_ALREADY_HAS_DRAFT",
                    f"申请 {req['request_id']} 已有另一份内容不同的草稿 {other['draft_id']}（{other['publish_at']}），"
                    "一张申请单只能有一份草稿；如需改期，请先请申请人确认旧草稿怎么处理",
                    details={"draft": other},
                ) from None
            raise ToolError("SLOT_OCCUPIED", f"{date} {time} 已被占用，请换时段", retryable=True, details={"occupied_by": exc.detail}) from None
        except StorageError as exc:
            raise ToolError("STORAGE_UNAVAILABLE", f"{exc}，本次没有写入", retryable=True) from None
        if created:
            self.created_draft_ids.append(saved["draft_id"])
        self.faults.after_commit("save_draft")  # timeout_after_commit：写入已生效，但返回超时
        if not created:
            mine = saved["draft_id"] in self.created_draft_ids
            message = ("这份草稿是本次处理中前一次 save_draft 写入的（上次接口没有正常返回，但写入已生效），没有新建草稿"
                       if mine else "同一申请内容的草稿之前已经提交过（重复提交），没有新建草稿")
            if saved["publish_at"] != when:
                message += f"；已有草稿的发布时间是 {saved['publish_at']}，本次请求的 {when} 没有生效"
            return {"created": False, "draft": saved, "written_earlier_in_this_run": mine, "message": message}
        result = {"created": True, "draft": saved, "message": "草稿已保存（未发布）"}
        if needs_confirmation:
            result["message"] += "，状态为待确认"
        if deviates and not requires_confirmation:
            result["confirmation_forced"] = True
            result["message"] += "（发布时间与申请不一致，系统已自动标记为待确认）"
        return result

    # ---- 给校验器和 Trace 用 ----------------------------------------------
    def facts(self) -> dict:
        """从调用台账和草稿库得到的“事实”，校验器只信这些，不信模型的说法。

        “本申请的草稿”按申请内容（幂等键）匹配：同一单号但内容不同的草稿不算完成，只作为冲突报告。
        """
        req = self.request
        keys = [k for k in [self.request_key(), *self.used_keys] if k]
        draft = next((d for d in (self.store.find_draft(idempotency_key=k) for k in keys) if d), None)
        conflicting = next((d for d in self.store.drafts_for_request(req["request_id"])
                            if not draft or d["draft_id"] != draft["draft_id"]), None)
        saves = [e for e in self.ledger if e.name == "save_draft"]
        save_errors = [e.result["error"] for e in saves if not e.ok]
        rule = self.rule_state.get((req.get("asset_id"), req.get("channel")))
        missing = [k for k in ("asset_id", "channel", "publish_at") if not req.get(k)]
        for e in self.ledger:
            if e.name == "read_asset":
                if e.ok:
                    missing += e.result["data"]["missing_fields"]
                elif e.result["error"]["code"] == "ASSET_NOT_FOUND":
                    missing.append("asset_id")
        for f in (rule or {}).get("findings", []):
            if f["rule_id"] == "R01":
                missing += f.get("fields", [])
        return {
            "draft": draft,
            "draft_created_this_run": bool(draft and draft["draft_id"] in self.created_draft_ids),
            "conflicting_draft": conflicting,
            "save_attempts": len(saves),
            "save_errors": save_errors,
            "save_failed": any(err["code"] in SAVE_FAILURE_CODES for err in save_errors),
            "rule": rule,
            "block_findings": [f for f in (rule or {}).get("findings", []) if f["level"] == "block"],
            "missing_fields": sorted(set(missing), key=missing.index),
            "tools_called": [e.name for e in self.ledger],
        }


# ---- Trace 用的结果摘要 -----------------------------------------------------
def summarize(name: str, args: dict, result: dict) -> str:
    if not result.get("ok"):
        err = result.get("error", {})
        tail = "（可重试）" if err.get("retryable") else ""
        return f"失败 {err.get('code')}：{err.get('message')}{tail}"
    data = result["data"]
    if name == "read_asset":
        a = data["asset"]
        music = a.get("music") or {}
        parts = [f"{a['asset_id']}《{a.get('title')}》{a.get('type')}"]
        if a.get("duration_sec"):
            parts.append(f"{a['duration_sec']} 秒")
        parts.append("必填齐全" if data["complete"] else "缺少：" + "、".join(data["missing_labels"]))
        if music:
            parts.append(f"音乐授权 {music.get('license_status')}")
        return "；".join(parts)
    if name == "check_rules":
        hits = [f"{f['rule_id']}[{f['level']}] {f['message']}" for f in data["findings"]]
        hits += [f"{r['rule_id']} 补查通过：{r['evidence']}" for r in data.get("resolved", [])]
        prefix = f"verdict={data['verdict']}" + ("（deep_check）" if data.get("deep_check") else "")
        return prefix + ("；" + "；".join(hits) if hits else "；全部规则通过")
    if name == "query_slots":
        head = f"{data['channel_name']} {data['date']}"
        if "free_slots" not in data:
            s = data["slots"][0]
            who = s.get("occupied_by", {})
            detail = f"（{who.get('asset_id')} {who.get('title') or who.get('draft_id', '')}）" if who else ""
            return f"{head} {s['time']}：{s['status']}{detail}"
        busy = [s["time"] for s in data["slots"] if s["status"] == "occupied"]
        return f"{head} 空闲：{'、'.join(data['free_slots']) or '无'}；占用：{'、'.join(busy) or '无'}"
    if name == "save_draft":
        d = data["draft"]
        if data["created"]:
            verb = "新建"
        elif data.get("written_earlier_in_this_run"):
            verb = "已存在（本次处理中前一次调用已写入，未新建）"
        else:
            verb = "已存在（重复提交，未新建）"
        if not data["created"] and args.get("publish_at") and args["publish_at"] != d["publish_at"]:
            verb += f"，本次请求的 {args['publish_at']} 未生效"
        forced = "；系统强制待确认" if data.get("confirmation_forced") else ""
        return f"草稿 {d['draft_id']} {verb}，状态 {d['status']}，{d['publish_at']}{forced}"
    return "ok"
