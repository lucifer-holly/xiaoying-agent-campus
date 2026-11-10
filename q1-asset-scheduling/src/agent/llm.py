"""模型接入的薄封装：真实模型（百炼 OpenAI 兼容接口）与离线 Mock 共用同一个 chat() 接口。

这一层只负责“把消息和工具发出去、把回复取回来、失败时如实抛错”，
不认识任何业务；该调哪个工具、调完怎么办，全部由 Agent 循环把结果交还给模型决定。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from config import LLMSettings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # 模型给出的原始 JSON 字符串，由工具注册表解析和校验


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0
    usage: dict | None = None
    finish_reason: str | None = None

    def to_message(self) -> dict:
        message: dict = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return message


class LLMError(RuntimeError):
    """模型调用失败（网络、认证、服务端错误）。"""


class LLMUnavailable(LLMError):
    """根本没有配置密钥：不发请求，直接提示改用 Mock。"""


class QwenLLM:
    """阿里云百炼 Qwen（OpenAI 兼容 Chat Completions + function calling）。"""

    mode = "real"

    def __init__(self, settings: LLMSettings):
        if not settings.api_key:
            raise LLMUnavailable(
                "LLM_API_KEY 未配置（或为空字符串），无法调用真实模型。"
                "请复制 .env.example 为 .env 并填写 LLM_API_KEY，或改用 --llm mock 离线跑通流程。"
            )
        from openai import OpenAI  # 延迟导入：只跑 Mock 时不需要安装 openai

        self.model = settings.model
        self.settings = settings
        self._client = OpenAI(base_url=settings.base_url, api_key=settings.api_key, timeout=settings.timeout_s, max_retries=2)

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                temperature=self.settings.temperature,
                # Qwen3.5 及以后默认开启思考模式，显式关闭：决策依据由工具参数 decision_note 提供
                extra_body={"enable_thinking": self.settings.enable_thinking},
            )
        except Exception as exc:  # openai 的认证、限流、网络、5xx 错误统一转成 LLMError
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        choice = response.choices[0]
        message = choice.message
        calls = [
            ToolCall(id=c.id or f"call_{i}", name=c.function.name, arguments=c.function.arguments or "{}")
            for i, c in enumerate(message.tool_calls or [])
        ]
        usage = None
        if response.usage:
            usage = {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens}
        return LLMReply(
            content=message.content or "",
            tool_calls=calls,
            model=response.model or self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            usage=usage,
            finish_reason=choice.finish_reason,
        )
