"""规则检查：结论由代码给出，模型只决定“要不要补查、查完怎么办”。"""
from __future__ import annotations

from .store import DataStore

FIELD_LABELS = {"title": "标题", "caption": "文案", "cover_url": "封面", "duration_sec": "时长"}

# verdict 的优先级：缺信息 > 阻断 > 待补查 > 提示 > 通过
VERDICT_BY_LEVEL = [("missing", "incomplete"), ("block", "block"), ("verify", "needs_verification"), ("warn", "warn")]


def missing_fields(asset: dict, rules_cfg: dict) -> list[str]:
    required = list(rules_cfg["required_fields"]["common"])
    if asset.get("type") == "video":
        required += rules_cfg["required_fields"].get("video", [])
    return [f for f in required if asset.get(f) in (None, "", [])]


def evaluate(asset: dict, channel_code: str, store: DataStore, *, deep: bool = False) -> dict:
    rules_cfg = store.rules
    rule = {r["rule_id"]: r for r in rules_cfg["rules"]}
    channel = store.channel(channel_code) or {}
    channel_name = channel.get("name", channel_code)
    findings: list[dict] = []
    resolved: list[dict] = []

    # R01 必填信息
    missing = missing_fields(asset, rules_cfg)
    if missing:
        findings.append({
            "rule_id": "R01", "name": "必填信息", "level": "missing", "fields": missing,
            "message": "缺少必填信息：" + "、".join(FIELD_LABELS.get(f, f) for f in missing),
            "suggestion": "请申请人在素材库补齐后重新提交",
        })

    # R02 绝对化用语
    text = " ".join(str(asset.get(k) or "") for k in ("title", "caption"))
    hits = [t for t in rule["R02"]["terms"] if t in text]
    if hits:
        findings.append({
            "rule_id": "R02", "name": "绝对化用语", "level": "block", "evidence": hits,
            "message": "标题或文案含绝对化用语：" + "、".join(hits),
            "suggestion": "删除或改写这些表述后重新提交审核",
        })

    # R03 音乐版权：素材库状态可能滞后，deep_check 才会查版权库
    music = asset.get("music")
    if music:
        status, lic_id, track = music.get("license_status"), music.get("license_id"), music.get("track")
        lic = store.license(lic_id)
        lic_ok = bool(lic and lic["status"] == "active" and channel_code in lic["channels"])
        if status == "pending" and not deep:
            findings.append({
                "rule_id": "R03", "name": "音乐版权", "level": "verify",
                "message": f"背景音乐《{track}》在素材库中的授权状态为审批中（{lic_id}），需要补查版权库确认",
                "suggestion": "调用 check_rules 并设置 deep_check=true 查询版权库",
            })
        elif status in ("pending", "licensed") and deep:
            if lic_ok:
                resolved.append({
                    "rule_id": "R03", "result": "pass",
                    "evidence": f"版权库记录 {lic_id}：{lic['status']}，有效期至 {lic['valid_until']}，授权渠道含{channel_name}",
                })
            else:
                findings.append({
                    "rule_id": "R03", "name": "音乐版权", "level": "block",
                    "message": f"版权库中没有《{track}》在{channel_name}的有效授权（{lic_id or '无授权编号'}）",
                    "suggestion": "更换已授权音乐或补办授权后重新提交",
                })
        elif status != "licensed":
            findings.append({
                "rule_id": "R03", "name": "音乐版权", "level": "block",
                "message": f"背景音乐《{track}》没有有效授权（状态：{status}）",
                "suggestion": "更换已授权音乐或补办授权后重新提交",
            })

    # R04 渠道格式
    if asset.get("type") not in channel.get("types", []):
        findings.append({
            "rule_id": "R04", "name": "渠道格式", "level": "block",
            "message": f"{channel_name}不支持该素材类型（{asset.get('type')}）",
            "suggestion": "换成支持该类型的渠道，或改做成渠道支持的形式",
        })
    duration, limit = asset.get("duration_sec"), channel.get("max_duration_sec")
    if asset.get("type") == "video" and duration and limit and duration > limit:
        findings.append({
            "rule_id": "R04", "name": "渠道格式", "level": "block",
            "message": f"视频时长 {duration} 秒超过{channel_name}上限 {limit} 秒",
            "suggestion": "剪辑到上限以内后重新提交",
        })

    # R05 标题长度（只提示）
    max_len = rule["R05"]["max_title_len"]
    title = asset.get("title") or ""
    if len(title) > max_len:
        findings.append({
            "rule_id": "R05", "name": "标题长度", "level": "warn",
            "message": f"标题 {len(title)} 个字符，超过 {max_len} 个字符可能被截断",
            "suggestion": "可酌情精简标题",
        })

    levels = {f["level"] for f in findings}
    verdict = next((v for lvl, v in VERDICT_BY_LEVEL if lvl in levels), "pass")
    return {
        "asset_id": asset["asset_id"],
        "asset_version": asset.get("version"),
        "channel": channel_code,
        "deep_check": deep,
        "verdict": verdict,
        "findings": findings,
        "resolved": resolved,
        "checked_rules": [r["rule_id"] for r in rules_cfg["rules"]],
    }
