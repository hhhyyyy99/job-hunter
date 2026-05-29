import datetime
import logging
import time
from pathlib import Path
from typing import Any

from job_hunter.config import JobHunterConfig, load_config
from job_hunter.db import StateDB
from job_hunter.scheduler import health_check, should_run_daily_pipeline, is_active_hours, is_bridge_running
from job_hunter.matcher import collect_watch_results, deduplicate_jobs, l1_filter, fetch_jd_details, ai_score_jobs, rank_jobs, add_to_candidate_pool
from job_hunter.applier import apply_pipeline
from job_hunter.tracker import poll_conversations, analyze_and_respond
from job_hunter.reporter import build_report, write_report
from job_hunter.feedback import parse_report_feedback, merge_feedback, apply_feedback_rules, build_feedback_context

logger = logging.getLogger("job-hunter")


def daily_pipeline(config: JobHunterConfig, data_dir: Path, dry_run: bool = False) -> str:
    today = datetime.date.today().isoformat()
    report_path = ""
    applied = []
    replied_results = []

    with StateDB(data_dir / "state.db") as db:
        health = health_check(config, data_dir)

        if not should_run_daily_pipeline(config, db, health):
            # Even if not running full pipeline, still check conversations
            if health.get("bridge_running") and is_active_hours(config):
                convos = poll_conversations(config, db)
                if convos:
                    replied_results = analyze_and_respond(convos, config, db, dry_run=dry_run)
            # Generate minimal report
            today_data = _build_today_data([], [], replied_results, [], [])
            md = build_report(today_data, health, config)
            report_path = write_report(md, config)
            return report_path

        # Step 1: Collect and match jobs
        logger.info("Step 1: 收集新岗位...")
        raw_jobs = collect_watch_results(config)
        unique_jobs = deduplicate_jobs(raw_jobs)

        # Step 2: L1 filter
        logger.info("Step 2: L1 粗筛...")
        l1_jobs = l1_filter(unique_jobs, config)

        # Step 3: Fetch JD details
        logger.info("Step 3: 获取 JD 详情...")
        detailed_jobs = fetch_jd_details(l1_jobs, db)

        # Step 4: AI scoring
        logger.info("Step 4: AI 评分...")
        scored_jobs = ai_score_jobs(detailed_jobs, config, db)

        # Step 5: Rank globally
        logger.info("Step 5: 全局排序...")
        ranked_jobs = rank_jobs(scored_jobs, config, db)

        # Add to candidate pool
        add_to_candidate_pool(ranked_jobs, db)

        # Step 6: Apply (top N)
        logger.info("Step 6: 自动投递...")
        if health.get("write_ops_enabled") and not dry_run:
            apply_result = apply_pipeline(config, db)
            applied = apply_result.get("applied", [])
        else:
            if dry_run:
                logger.info("dry-run 模式，跳过投递")
            else:
                logger.warning("写操作未启用，跳过投递")

        # Step 7: Check conversations
        logger.info("Step 7: 对话跟进...")
        replied_results = []
        if health.get("bridge_running"):
            convos = poll_conversations(config, db)
            if convos:
                replied_results = analyze_and_respond(convos, config, db, dry_run=dry_run)

        # Step 8: Generate report
        logger.info("Step 8: 生成日报...")
        interviews = _collect_interviews(db)
        suggested = [j for j in ranked_jobs if config.suggest_threshold <= j.get("match_score", 0) < config.auto_apply_threshold]
        l2_passed = len([j for j in ranked_jobs if j.get("match_score", 0) >= config.auto_apply_threshold])

        today_data = _build_today_data(
            applied=applied,
            suggested=suggested,
            replied=replied_results,
            interviews=interviews,
            extra={
                "new_jobs_total": len(raw_jobs),
                "l1_passed": len(l1_jobs),
                "l2_passed": l2_passed,
                "follow_up_count": len(replied_results),
                "interview_count": len(interviews),
                "replied_count": sum(1 for r in replied_results if r.get("action") == "auto_reply" and r.get("sent")),
            },
        )
        md = build_report(today_data, health, config)
        report_path = write_report(md, config)

        # Parse previous report feedback
        prev_report = Path(config.report_output_dir).expanduser() / f"求职日报-{_yesterday()}.md"
        if prev_report.exists():
            fb = parse_report_feedback(str(prev_report))
            if fb:
                json_fb = {}
                merge_feedback(fb, json_fb)
                apply_feedback_rules(config, db)

        # Mark daily done
        db.mark_daily_done(
            today,
            applied=len(applied),
            replied=sum(1 for r in replied_results if r.get("action") == "auto_reply" and r.get("sent")),
            new_jobs=len(raw_jobs),
            status="completed",
        )

    return report_path


def conversation_loop(config: JobHunterConfig, data_dir: Path, dry_run: bool = False) -> None:
    """持续轮询对话状态，检测到新消息时触发分析+回复。"""
    logger.info("对话轮询启动")
    with StateDB(data_dir / "state.db") as db:
        while True:
            if not is_active_hours(config):
                time.sleep(60)
                continue

            if not is_bridge_running():
                time.sleep(30)
                continue

            convos = poll_conversations(config, db)
            if convos:
                logger.info(f"检测到 {len(convos)} 个会话有新消息")
                analyze_and_respond(convos, config, db, dry_run=dry_run)

            time.sleep(config.poll_interval_minutes * 60)


def _build_today_data(applied, suggested, replied, interviews, extra):
    return {
        "applied": applied,
        "suggested": suggested,
        "follow_ups": replied,
        "interviews": interviews,
        **extra,
    }


def _collect_interviews(db):
    rows = db.get_conversations_needing_polling()
    return [r for r in rows if r.get("stage") in ("interview_scheduled", "interview")]


def _yesterday():
    return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
