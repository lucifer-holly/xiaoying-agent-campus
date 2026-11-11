"""运行配置：环境变量优先，其次读取项目根目录的 .env（不依赖 python-dotenv）。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.8-max"


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """把 .env 里的 KEY=VALUE 写进 os.environ；已经存在的环境变量不会被覆盖。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return default if value == "" else value in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    api_key: str
    model: str
    timeout_s: float
    temperature: float
    enable_thinking: bool


def llm_settings() -> LLMSettings:
    load_dotenv()
    return LLMSettings(
        base_url=(os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        # 空字符串按“未配置”处理：.env 里 `LLM_API_KEY=` 是常见的占位写法
        api_key=os.environ.get("LLM_API_KEY", "").strip(),
        model=os.environ.get("LLM_MODEL") or DEFAULT_MODEL,
        timeout_s=float(os.environ.get("LLM_TIMEOUT_S") or 60),
        temperature=float(os.environ.get("LLM_TEMPERATURE") or 0.2),
        enable_thinking=_flag("LLM_ENABLE_THINKING", False),
    )
