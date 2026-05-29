"""Tests for the conversation tracker module."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from job_hunter.config import JobHunterConfig
from job_hunter.db import StateDB


class TestClassifyAction:
    def test_deep_conversation_notify(self):
        from job_hunter.tracker import _classify_action
        config = JobHunterConfig()
        config.max_auto_reply_depth = 5
        analysis = {"intent": "greeting", "confidence": 0.9}
        result = _classify_action(analysis, 6, config)
        assert result == "notify_user"

    def test_interview_urgent(self):
        from job_hunter.tracker import _classify_action
        config = JobHunterConfig()
        analysis = {"intent": "面试邀请", "confidence": 0.9}
        result = _classify_action(analysis, 2, config)
        assert result == "urgent_notify"

    def test_sensitive_notify(self):
        from job_hunter.tracker import _classify_action
        config = JobHunterConfig()
        analysis = {"intent": "薪资讨论", "confidence": 0.9}
        result = _classify_action(analysis, 2, config)
        assert result == "notify_user"

    def test_normal_auto_reply(self):
        from job_hunter.tracker import _classify_action
        config = JobHunterConfig()
        analysis = {"intent": "greeting", "confidence": 0.8}
        result = _classify_action(analysis, 2, config)
        assert result == "auto_reply"


class TestInterviewIntent:
    def test_keyword_match(self):
        from job_hunter.tracker import _is_interview_intent
        config = JobHunterConfig()
        analysis = {"intent": "约个时间面试", "match_points": ["面试", "到岗时间"]}
        assert _is_interview_intent(analysis, config)

    def test_no_match(self):
        from job_hunter.tracker import _is_interview_intent
        config = JobHunterConfig()
        analysis = {"intent": "项目经验确认", "match_points": ["Golang", "Kubernetes"]}
        assert not _is_interview_intent(analysis, config)


class TestConversationState:
    def test_upsert_and_get(self, tmp_path):
        db = StateDB(tmp_path / "test.db")
        db.upsert_conversation({
            "security_id": "S1",
            "company": "TestCorp",
            "title": "Engineer",
            "depth": 3,
            "stage": "chatting",
            "auto_reply_count": 2,
        })
        state = db.get_conversation("S1")
        assert state is not None
        assert state["depth"] == 3
        assert state["stage"] == "chatting"

    def test_stage_transition(self, tmp_path):
        db = StateDB(tmp_path / "test.db")
        db.upsert_conversation({
            "security_id": "S1",
            "company": "TestCorp",
            "stage": "chatting",
        })
        db.upsert_conversation({
            "security_id": "S1",
            "company": "TestCorp",
            "stage": "interview_scheduled",
            "interview_time": "2025-02-01 14:00",
        })
        state = db.get_conversation("S1")
        assert state["stage"] == "interview_scheduled"
        assert state["interview_time"] == "2025-02-01 14:00"
