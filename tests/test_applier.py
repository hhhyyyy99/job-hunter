"""Tests for the auto applier module."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from job_hunter.config import JobHunterConfig
from job_hunter.db import StateDB


class TestApplyLimits:
    def test_company_limit(self, tmp_path):
        db = StateDB(tmp_path / "test.db")
        # Add 2 applies for same company this week
        db.record_apply("S1", "J1", "TestCorp", "Job 1", 85)
        db.record_apply("S2", "J2", "TestCorp", "Job 2", 80)

        count = db.count_company_applies_since("TestCorp", days=7)
        assert count == 2

    def test_daily_limit(self, tmp_path):
        db = StateDB(tmp_path / "test.db")
        for i in range(5):
            db.record_apply(f"S{i}", f"J{i}", "Corp", f"Job {i}", 70 + i)

        count = db.count_applies_today()
        assert count == 5

    def test_deduplication(self, tmp_path):
        db = StateDB(tmp_path / "test.db")
        db.record_apply("S1", "J1", "TestCorp", "Job 1", 85)
        assert db.is_applied("S1", "J1")
        assert not db.is_applied("S2", "J2")
