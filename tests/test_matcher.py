"""Tests for the job matcher module."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from job_hunter.config import JobHunterConfig
from job_hunter.db import StateDB
from job_hunter.matcher import deduplicate_jobs, l1_filter, rank_jobs


class TestDeduplicate:
    def test_no_duplicates(self):
        jobs = [
            {"security_id": "A", "job_id": "1", "title": "Job A"},
            {"security_id": "B", "job_id": "2", "title": "Job B"},
        ]
        result = deduplicate_jobs(jobs)
        assert len(result) == 2

    def test_duplicates_removed(self):
        jobs = [
            {"security_id": "A", "job_id": "1", "title": "Job A", "company": "X"},
            {"security_id": "A", "job_id": "1", "title": "Job A Duplicate", "company": "X Extra"},
        ]
        result = deduplicate_jobs(jobs)
        assert len(result) == 1
        # Should keep the richer entry
        assert result[0]["title"] == "Job A Duplicate"

    def test_different_jobs_same_company(self):
        jobs = [
            {"security_id": "A", "job_id": "1", "title": "Job A"},
            {"security_id": "A", "job_id": "2", "title": "Job B"},
        ]
        result = deduplicate_jobs(jobs)
        assert len(result) == 2


class TestL1Filter:
    def test_blacklist(self):
        config = JobHunterConfig()
        config.company_blacklist = ["BadCorp"]
        jobs = [
            {"company": "GoodCorp", "title": "Job 1"},
            {"company": "BadCorp", "title": "Job 2"},
        ]
        result = l1_filter(jobs, config)
        assert len(result) == 1
        assert result[0]["company"] == "GoodCorp"

    def test_city_filter(self):
        config = JobHunterConfig()
        config.target_cities = ["广州"]
        jobs = [
            {"company": "A", "city": "广州", "title": "Job 1"},
            {"company": "B", "city": "北京", "title": "Job 2"},
        ]
        result = l1_filter(jobs, config)
        assert len(result) == 1
        assert result[0]["city"] == "广州"

    def test_empty_filters_pass(self):
        config = JobHunterConfig()
        jobs = [{"company": "A", "title": "Job 1"}]
        result = l1_filter(jobs, config)
        assert len(result) == 1


class TestRank:
    def test_sort_by_score(self, tmp_path):
        db = StateDB(tmp_path / "test.db")
        config = JobHunterConfig()
        jobs = [
            {"match_score": 60, "company": "C"},
            {"match_score": 90, "company": "A"},
            {"match_score": 75, "company": "B"},
        ]
        result = rank_jobs(jobs, config, db)
        assert result[0]["company"] == "A"
        assert result[1]["company"] == "B"
        assert result[2]["company"] == "C"

    def test_whitelist_boost(self, tmp_path):
        db = StateDB(tmp_path / "test.db")
        config = JobHunterConfig()
        config.company_whitelist = ["StarCorp"]
        jobs = [
            {"match_score": 70, "company": "StarCorp"},
            {"match_score": 80, "company": "NormalCorp"},
        ]
        result = rank_jobs(jobs, config, db)
        # StarCorp gets +10 boost
        assert result[0]["company"] == "StarCorp"
