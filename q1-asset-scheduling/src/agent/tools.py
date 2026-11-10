"""工具注册：JSON Schema、参数校验、结果统一封装为 {ok, data, error}。

模型给出的参数不可信：先解析、再按 Schema 校验，最后才交给业务函数。
业务函数抛出的 ToolError 和意外异常都会被封装成 ok=false 的观察结果交还给模型，
不会让 Agent 循环崩掉。每个工具都要求 decision_note（一句话决策依据），
注册表把它从参数里取出来单独记进 Trace，不传给业务函数。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

DECISION_NOTE = {"type": "string", "description": "一句话说明为什么现在调用这个工具（写进运行记录）"}


class ToolError(Exception):
    """业务工具主动返回的错误：原样交给模型，由模型决定重试、换方案还是结束。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict:
        err = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.details:
            err["details"] = self.details
        return err


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class ToolExecution:
    name: str
    args: dict            # 去掉 decision_note 之后的参数（解析失败时为 {}）
    decision_note: str | None
    result: dict          # {ok: true, data} 或 {ok: false, error}

    @property
    def ok(self) -> bool:
        return bool(self.result.get("ok"))


_PY_TYPES = {"string": str, "boolean": bool, "integer": int, "number": (int, float), "array": list, "object": dict}


def _check_value(key: str, spec: dict, value: Any) -> list[str]:
    expected = spec.get("type")
    if expected:
        bad_type = not isinstance(value, _PY_TYPES[expected])
        if expected in ("integer", "number") and isinstance(value, bool):
            bad_type = True
        if bad_type:
            return [f"参数 {key} 应为 {expected}"]
    errors = []
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"参数 {key} 只能取 {spec['enum']} 之一，收到 {value!r}")
    if expected == "string" and "pattern" in spec and not re.fullmatch(spec["pattern"], value):
        errors.append(f"参数 {key} 格式不对（应匹配 {spec['pattern']}），收到 {value!r}")
    if expected == "array" and "items" in spec:
        for i, item in enumerate(value):
            errors.extend(_check_value(f"{key}[{i}]", spec["items"], item))
    return errors


def validate_args(schema: dict, args: Any) -> list[str]:
    """一个够用的 JSON Schema 子集校验：type / required / enum / pattern / items / additionalProperties。"""
    if not isinstance(args, dict):
        return ["参数必须是 JSON 对象"]
    props = schema.get("properties", {})
    errors = [f"缺少必填参数 {k}" for k in schema.get("required", []) if args.get(k) in (None, "")]
    if schema.get("additionalProperties") is False:
        errors += [f"未知参数 {k}" for k in args if k not in props]
    for key, value in args.items():
        if key in props and value is not None:
            errors += _check_value(key, props[key], value)
    return errors


def _coerce(schema: dict, args: dict) -> dict:
    """容忍模型常见的小偏差：布尔值写成字符串、可选参数传 null。"""
    props = schema.get("properties", {})
    out = {}
    for key, value in args.items():
        spec = props.get(key, {})
        if spec.get("type") == "boolean" and isinstance(value, str) and value.lower() in ("true", "false"):
            value = value.lower() == "true"
        if value is None and key not in schema.get("required", []):
            continue
        out[key] = value
    return out


class ToolRegistry:
    def __init__(self, tools: list[Tool], observer: Callable[[ToolExecution], None] | None = None):
        self._tools = {t.name: t for t in tools}
        self._observer = observer

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def parse(self, name: str, raw_args: str | dict) -> tuple[dict, str | None, list[str]]:
        """解析并校验参数，返回 (参数, decision_note, 错误列表)。"""
        tool = self._tools.get(name)
        if tool is None:
            return {}, None, [f"不存在工具 {name}（可用：{', '.join(self._tools)}）"]
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args or "{}")
            except json.JSONDecodeError as exc:
                return {}, None, [f"参数不是合法 JSON：{exc.msg}"]
        else:
            args = dict(raw_args)
        if not isinstance(args, dict):
            return {}, None, ["参数必须是 JSON 对象"]
        args = _coerce(tool.parameters, args)
        errors = validate_args(tool.parameters, args)
        note = args.pop("decision_note", None)
        return args, note, errors

    def execute(self, name: str, raw_args: str | dict) -> ToolExecution:
        args, note, errors = self.parse(name, raw_args)
        if name not in self._tools:
            result = {"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": errors[0], "retryable": False}}
        elif errors:
            result = {"ok": False, "error": {"code": "INVALID_ARGUMENTS", "message": "；".join(errors), "retryable": True}}
        else:
            try:
                result = {"ok": True, "data": self._tools[name].handler(**args)}
            except ToolError as exc:
                result = {"ok": False, "error": exc.to_dict()}
            except Exception as exc:  # 业务代码的意外异常也只作为观察结果返回
                result = {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}", "retryable": False}}
        execution = ToolExecution(name=name, args=args, decision_note=note, result=result)
        if self._observer:
            self._observer(execution)
        return execution
