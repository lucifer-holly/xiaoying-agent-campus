from __future__ import annotations

import pytest

from domain.scheduling import SchedulingSession
from domain.store import DataStore

BASE_REQUEST = {
    "request_id": "REQ-TEST-001",
    "asset_id": "M01",
    "channel": "douyin",
    "publish_at": "2026-11-13 18:00",
    "constraints": {"date_fixed": True},
}


@pytest.fixture
def store() -> DataStore:
    return DataStore()


@pytest.fixture
def make_session(store):
    def _make(faults: dict | None = None, **overrides) -> SchedulingSession:
        return SchedulingSession(store, {**BASE_REQUEST, **overrides}, faults)

    return _make


def call(session: SchedulingSession, name: str, **args) -> dict:
    """像模型一样调用工具（带 decision_note），返回 {ok, data, error}。"""
    args.setdefault("decision_note", "测试调用")
    return session.registry.execute(name, args).result
