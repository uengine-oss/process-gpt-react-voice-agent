"""
대화방 음성 모드의 할 일 조회 — 도구는 이메일을 받는데 todolist.user_id 에는 uid 가 들어 있다.

예전에는 `user_id like '%이메일%'` 로 찾아 하나도 나오지 않았고, 에이전트는 할 일이 있는데도
늘 「지금 확인된 사용자의 할일 목록이 없습니다」 라고 대답했다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import database as db  # noqa: E402

UID = "63826321-6b8b-48ac-93c4-26822f3a8265"
EMAIL = "jinyoung@hanbit.example"
USERS = [{"id": UID, "email": EMAIL}]
TODOS = [
    {"id": "t1", "user_id": UID, "tenant_id": "localhost", "status": "TODO", "activity_id": "a", "activity_name": "A"},
    {"id": "t2", "user_id": f"{UID},daa2c3e3", "tenant_id": "localhost", "status": "DONE", "activity_id": "b", "activity_name": "B"},
    {"id": "t3", "user_id": "someone-else", "tenant_id": "localhost", "status": "TODO", "activity_id": "c", "activity_name": "C"},
]


class _Q:
    """supabase-py 의 select 사슬을 흉내 낸다 — eq · like · filter(cs) · execute."""

    def __init__(self, rows):
        self.rows = list(rows)

    def select(self, *_):
        return self

    def eq(self, col, val):
        return _Q(r for r in self.rows if r.get(col) == val)

    def like(self, col, pattern):
        needle = pattern.strip("%")
        return _Q(r for r in self.rows if needle in (r.get(col) or ""))

    def filter(self, col, op, val):
        assert op == "cs"
        want = val.strip("{}")
        return _Q(r for r in self.rows if want in (r.get(col) or []))

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _DB:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Q(self.tables.get(name, []))


def _with(tables):
    return db.supabase_client_var.set(_DB(tables))


def test_이메일로_uid_를_찾아_할_일을_조회한다():
    token = _with({"users": USERS, "todolist": TODOS})
    try:
        items = db.fetch_todolist_by_user_id(EMAIL, "localhost")
    finally:
        db.supabase_client_var.reset(token)

    assert sorted(i.id for i in items) == ["t1", "t2"]


def test_상태로_거를_때도_uid_로_찾는다():
    token = _with({"users": USERS, "todolist": TODOS})
    try:
        items = db.fetch_todolist_by_user_id_and_status(EMAIL, "TODO", "localhost")
    finally:
        db.supabase_client_var.reset(token)

    assert [i.id for i in items] == ["t1"]


def test_uid_를_그대로_줘도_찾는다():
    token = _with({"users": USERS, "todolist": TODOS})
    try:
        items = db.fetch_todolist_by_user_id(UID, "localhost")
    finally:
        db.supabase_client_var.reset(token)

    assert sorted(i.id for i in items) == ["t1", "t2"]


def test_참여한_인스턴스도_uid_로_찾는다(monkeypatch):
    """bpm_proc_inst.participants 에도 uid 가 들어 있다."""
    # ProcessInstance 는 만들 때 프로세스 정의를 읽는다 — 여기서는 찾은 행만 본다
    monkeypatch.setattr(db, "ProcessInstance", lambda **kw: SimpleNamespace(**kw))
    inst = [
        {"proc_inst_id": "p1", "tenant_id": "localhost", "participants": [UID], "proc_inst_name": "견적", "status": "RUNNING"},
        {"proc_inst_id": "p2", "tenant_id": "localhost", "participants": ["someone-else"], "status": "RUNNING"},
    ]
    token = _with({"users": USERS, "bpm_proc_inst": inst})
    try:
        items = db.fetch_process_instance_list(EMAIL, None, "localhost")
    finally:
        db.supabase_client_var.reset(token)

    assert [i.proc_inst_id for i in items] == ["p1"]
