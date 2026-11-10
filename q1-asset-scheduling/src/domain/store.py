"""合成数据与草稿库。

素材、规则、版权库、发布日历都是只读的合成数据（data/*.json）。
草稿库是唯一可写的部分：默认只在内存里（每次运行互不影响），
传入 drafts_path 时落盘到 JSON 文件，用来演示跨进程的“重复提交”。
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


class DataStore:
    def __init__(self, data_dir: Path = DATA_DIR, drafts_path: Path | None = None):
        self.data_dir = Path(data_dir)
        self.assets: dict[str, dict] = {a["asset_id"]: a for a in _load(self.data_dir / "assets.json")["assets"]}
        self.rules: dict = _load(self.data_dir / "rules.json")
        self.licenses: dict[str, dict] = {
            lic["license_id"]: lic for lic in _load(self.data_dir / "license_registry.json")["licenses"]
        }
        schedule = _load(self.data_dir / "schedule.json")
        self.slot_times: list[str] = schedule["slot_times"]
        self.bookings: list[dict] = schedule["bookings"]
        self.drafts_path = Path(drafts_path) if drafts_path else None
        self._lock = threading.Lock()
        self._drafts: list[dict] = []
        if self.drafts_path and self.drafts_path.exists():
            self._drafts = _load(self.drafts_path).get("drafts", [])

    # ---- 只读数据 -------------------------------------------------------
    def get_asset(self, asset_id: str) -> dict | None:
        asset = self.assets.get(asset_id)
        return copy.deepcopy(asset) if asset else None

    def channel(self, code: str) -> dict | None:
        return self.rules["channels"].get(code)

    def license(self, license_id: str | None) -> dict | None:
        return self.licenses.get(license_id) if license_id else None

    def slot_occupant(self, channel: str, date: str, time: str) -> dict | None:
        """返回占用该时段的条目（已有排期或草稿），空闲时返回 None。"""
        for b in self.bookings:
            if (b["channel"], b["date"], b["time"]) == (channel, date, time):
                return {"type": "booking", "asset_id": b["asset_id"], "title": b["title"]}
        for d in self.drafts():
            if d["channel"] == channel and d["publish_at"] == f"{date} {time}":
                return {
                    "type": "draft",
                    "asset_id": d["asset_id"],
                    "draft_id": d["draft_id"],
                    "request_id": d["request_id"],
                    "draft_status": d["status"],
                }
        return None

    # ---- 草稿库 ---------------------------------------------------------
    def drafts(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._drafts)

    def find_draft(self, *, draft_id: str | None = None, idempotency_key: str | None = None) -> dict | None:
        for d in self.drafts():
            if draft_id and d["draft_id"] == draft_id:
                return d
            if idempotency_key and d["idempotency_key"] == idempotency_key:
                return d
        return None

    def drafts_for_request(self, request_id: str) -> list[dict]:
        return [d for d in self.drafts() if d["request_id"] == request_id]

    def insert_draft(self, draft: dict) -> tuple[dict, bool]:
        """按幂等键插入；同键已存在时返回已有草稿和 False。检查与写入在同一把锁里完成。"""
        with self._lock:
            for d in self._drafts:
                if d["idempotency_key"] == draft["idempotency_key"]:
                    return copy.deepcopy(d), False
            self._drafts.append(copy.deepcopy(draft))
            self._persist_locked()
            return copy.deepcopy(draft), True

    def _persist_locked(self) -> None:
        if not self.drafts_path:
            return
        self.drafts_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"drafts": self._drafts}, ensure_ascii=False, indent=2)
        # 先写临时文件再原子替换，避免进程中断留下半个 JSON
        fd, tmp = tempfile.mkstemp(dir=self.drafts_path.parent, prefix=".drafts-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, self.drafts_path)
