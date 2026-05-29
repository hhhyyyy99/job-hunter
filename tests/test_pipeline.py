"""End-to-end integration tests with mocked boss CLI."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from job_hunter.config import JobHunterConfig
from job_hunter.db import StateDB
from job_hunter.feedback import parse_report_feedback, merge_feedback


_MOCK_WATCH_RESULT = {
    "ok": True,
    "data": {
        "new_items": [
            {
                "security_id": "S1",
                "job_id": "J1",
                "title": "Golang Engineer",
                "company": "TechCorp",
                "salary": "25-35K",
                "city": "广州",
                "skills": ["Go", "K8s"],
            },
            {
                "security_id": "S2",
                "job_id": "J2",
                "title": "Backend Dev",
                "company": "DataCorp",
                "salary": "20-30K",
                "city": "广州",
                "skills": ["Python", "Go"],
            },
        ]
    },
}

_MOCK_DETAIL_RESULT = {
    "ok": True,
    "data": {
        "description": "岗位职责：负责后端服务开发与维护",
        "jobDescription": "维护微服务系统",
    },
}

_MOCK_AI_RESULT = {
    "ok": True,
    "data": {
        "match_score": 85,
        "match_analysis": "技能栈高度匹配",
    },
}

_MOCK_APPLY_RESULT = {
    "ok": True,
    "data": {"message": "投递成功"},
}

_MOCK_CHAT_RESULT = {
    "ok": True,
    "data": [
        {
            "security_id": "S1",
            "brand_name": "TechCorp",
            "title": "Golang Engineer",
            "unread": 1,
            "lastMsg": "你好，简历收到了",
        },
    ],
}

_MOCK_AI_REPLY_RESULT = {
    "ok": True,
    "data": {
        "intent_analysis": "HR确认收到简历",
        "reply_drafts": [{"text": "您好，感谢查看，期待进一步交流"}],
    },
}


class TestPipelineIntegration:
    def test_full_pipeline_with_mocks(self, tmp_path, monkeypatch):
        """Test the complete pipeline flow with all boss CLI calls mocked."""
        config = JobHunterConfig()
        config.presets = ["test-preset"]
        config.auto_apply_threshold = 75
        config.max_per_day = 5
        config.auto_reply = False  # Disable auto-reply for test
        config.report_output_dir = str(tmp_path / "reports")

        # Prepare DB
        db = StateDB(tmp_path / "state.db")

        # Mock all subprocess calls
        call_count = {"watch": 0, "detail": 0, "ai": 0, "apply": 0, "chat": 0}

        def mock_subprocess(args, **kwargs):
            import subprocess as sp
            cmd_args = args[0] if isinstance(args, tuple) else args
            if isinstance(cmd_args, list):
                cmd_str = " ".join(str(a) for a in cmd_args)
            else:
                cmd_str = str(cmd_args)

            if "watch run" in cmd_str:
                call_count["watch"] += 1
                return _make_mock_result(_MOCK_WATCH_RESULT)
            elif "detail" in cmd_str:
                call_count["detail"] += 1
                return _make_mock_result(_MOCK_DETAIL_RESULT)
            elif "ai analyze-jd" in cmd_str:
                call_count["ai"] += 1
                return _make_mock_result(_MOCK_AI_RESULT)
            elif "apply" in cmd_str:
                call_count["apply"] += 1
                return _make_mock_result(_MOCK_APPLY_RESULT)
            elif "chat" in cmd_str:
                call_count["chat"] += 1
                return _make_mock_result(_MOCK_CHAT_RESULT)
            elif "ai reply" in cmd_str:
                return _make_mock_result(_MOCK_AI_REPLY_RESULT)
            return _make_mock_result({"ok": False, "error": {"code": "UNKNOWN"}})

        # Test matcher pipeline
        from job_hunter.matcher import collect_watch_results, deduplicate_jobs, l1_filter, rank_jobs

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mock_subprocess

            # Collect
            jobs = collect_watch_results(config)
            assert len(jobs) == 2
            assert call_count["watch"] > 0

            # Deduplicate
            unique = deduplicate_jobs(jobs)
            assert len(unique) == 2

            # L1 filter
            filtered = l1_filter(unique, config)
            assert len(filtered) == 2

            # Rank
            for j in filtered:
                j["match_score"] = 85 if j["company"] == "TechCorp" else 75
            ranked = rank_jobs(filtered, config, db)
            assert ranked[0]["company"] == "TechCorp"

        db.close()

    def test_feedback_loop(self, tmp_path):
        """Test feedback parsing from report to action."""
        report_md = """## 今日自动投递

- **BadCorp** · Engineer · 25-35K · 匹配分 88 [x]
- **GoodCorp** · Dev · 20-30K · 匹配分 85 [ ]

## 待跟进

### 🟡 TestCorp · Developer
  意图: 确认项目经验
  → 建议回复: 您好在吗 [x]
"""
        report_path = tmp_path / "report.md"
        report_path.write_text(report_md, encoding="utf-8")

        feedback = parse_report_feedback(str(report_path))
        assert len(feedback) == 2

        skip_fb = [f for f in feedback if f["type"] == "apply_skip"]
        assert len(skip_fb) == 1
        assert skip_fb[0]["target"] == "BadCorp"

        reply_fb = [f for f in feedback if f["type"] == "reply_issue"]
        assert len(reply_fb) == 1

    def test_report_generation(self, tmp_path):
        """Test report content structure."""
        from job_hunter.reporter import build_report, write_report
        config = JobHunterConfig()
        config.report_output_dir = str(tmp_path / "reports")

        health = {
            "bridge_running": True,
            "extension_connected": True,
            "login_valid": True,
            "ai_available": True,
            "disk_ok": True,
            "write_ops_enabled": True,
        }

        today_data = {
            "new_jobs_total": 10,
            "l1_passed": 7,
            "l2_passed": 4,
            "applied": [
                {"company": "TechCorp", "title": "Engineer", "match_score": 88, "salary": "25-35K"},
                {"company": "DataCorp", "title": "Dev", "match_score": 82, "salary": "20-30K"},
            ],
            "suggested": [
                {"company": "OtherCorp", "title": "JR Dev", "match_score": 65},
            ],
            "follow_ups": [],
            "interviews": [],
            "follow_up_count": 0,
            "interview_count": 0,
            "replied_count": 0,
        }

        md = build_report(today_data, health, config)
        assert "TechCorp" in md
        assert "匹配分 88" in md
        assert "[ ]" in md  # Feedback checkbox
        assert "系统状态" in md or "## " in md

        path = write_report(md, config)
        assert Path(path).exists()


def _make_mock_result(data):
    mock = MagicMock()
    mock.stdout = json.dumps(data, ensure_ascii=False)
    mock.stderr = ""
    mock.returncode = 0
    return mock
