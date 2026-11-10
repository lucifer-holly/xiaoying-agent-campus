"""故障注入：写在输入文件的 fault_injection 里，保证“工具失败”场景稳定复现（真实模型下也一样）。

返回给模型的错误信息与真实故障一致，不提示“这是注入的”；注入配置记录在 Trace 头部。

模式：
- error                 每次调用都失败（标记为可重试，但重试也不会成功）
- error_once            第一次调用失败，之后恢复正常
- timeout               每次调用都超时
- timeout_after_commit  仅 save_draft：写入已经生效，但接口返回超时
"""
from __future__ import annotations

from collections import Counter

from agent.tools import ToolError

MODES = {"error", "error_once", "timeout", "timeout_after_commit"}
TOOLS = {"read_asset", "check_rules", "query_slots", "save_draft"}

_UNAVAILABLE = {
    "read_asset": ("ASSET_SERVICE_UNAVAILABLE", "素材库服务暂时不可用（503）"),
    "check_rules": ("RULE_SERVICE_UNAVAILABLE", "规则服务暂时不可用（503）"),
    "query_slots": ("CALENDAR_UNAVAILABLE", "发布日历服务暂时不可用（503）"),
    "save_draft": ("STORAGE_UNAVAILABLE", "草稿库写入失败：存储服务暂时不可用（503），本次没有写入"),
}


class FaultInjector:
    def __init__(self, config: dict | None = None):
        config = dict(config or {})
        for tool, mode in config.items():
            if tool not in TOOLS:
                raise ValueError(f"fault_injection 不支持的工具：{tool}（可选 {sorted(TOOLS)}）")
            if mode not in MODES:
                raise ValueError(f"fault_injection 不支持的模式：{mode}（可选 {sorted(MODES)}）")
            if mode == "timeout_after_commit" and tool != "save_draft":
                raise ValueError("timeout_after_commit 只适用于 save_draft")
        self.config = config
        self.calls: Counter = Counter()

    def before(self, tool: str) -> None:
        """工具逻辑执行前调用；命中时抛出 ToolError。"""
        self.calls[tool] += 1
        mode = self.config.get(tool)
        if mode == "error" or (mode == "error_once" and self.calls[tool] == 1):
            code, message = _UNAVAILABLE[tool]
            raise ToolError(code, message, retryable=True)
        if mode == "timeout":
            raise ToolError("TIMEOUT", f"{tool} 调用超时（10 秒无响应）", retryable=True)

    def after_commit(self, tool: str) -> None:
        """写入生效后调用；只有 timeout_after_commit 会在这里抛错（只影响第一次调用）。"""
        if self.config.get(tool) == "timeout_after_commit" and self.calls[tool] == 1:
            raise ToolError("TIMEOUT", "保存接口响应超时（10 秒），无法确认是否已写入", retryable=True)
