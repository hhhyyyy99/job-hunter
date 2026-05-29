import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from job_hunter.config import JobHunterConfig, run_boss
from job_hunter.db import StateDB

JD_CACHE_DIR = Path.home() / ".boss-agent" / "job-hunter" / "jd_cache"


def collect_watch_results(config: JobHunterConfig) -> list[dict[str, Any]]:
    all_jobs = []
    for preset in config.presets:
        result = run_boss("watch", "run", preset, timeout=120)
        if result.get("ok"):
            data = result.get("data", {})
            new_items = data.get("new_items", []) if isinstance(data, dict) else []
            for item in new_items:
                item["_preset"] = preset
                all_jobs.append(item)
    return all_jobs


def deduplicate_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {}
    for job in jobs:
        key = f"{job.get('security_id', '')}:{job.get('job_id', '')}"
        if key and key not in seen:
            seen[key] = job
        elif key and key in seen:
            # Keep the one with the more recent or richer data
            existing = seen[key]
            if len(json.dumps(job, ensure_ascii=False)) > len(json.dumps(existing, ensure_ascii=False)):
                seen[key] = job
    return list(seen.values())


def l1_filter(jobs: list[dict[str, Any]], config: JobHunterConfig) -> list[dict[str, Any]]:
    result = []
    for job in jobs:
        company = job.get("company", "")

        if company in config.company_blacklist:
            continue

        city = job.get("city", "")
        if config.target_cities and city not in config.target_cities:
            continue

        salary_str = job.get("salary", "")
        if config.min_salary and salary_str:
            salary_max = _parse_salary_max(salary_str)
            min_expected = _parse_salary_min(config.min_salary)
            if min_expected > 0 and salary_max > 0 and salary_max < min_expected:
                continue

        result.append(job)
    return result


def fetch_jd_details(jobs: list[dict[str, Any]], db: StateDB) -> list[dict[str, Any]]:
    JD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for job in jobs:
        sid = job.get("security_id", "")
        cache_path = JD_CACHE_DIR / f"{sid}.json"

        jd_text = ""
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                jd_text = cached.get("jd_text", "")
            except Exception:
                pass

        if not jd_text:
            detail = run_boss("detail", sid, timeout=120)
            if detail.get("ok"):
                jd_data = detail.get("data", {})
                jd_text = jd_data.get("description", "") or jd_data.get("jobDescription", "") or json.dumps(jd_data, ensure_ascii=False)
                cache_path.write_text(json.dumps({"jd_text": jd_text, "cached_at": time.time()}, ensure_ascii=False), encoding="utf-8")

        job["jd_text"] = jd_text
        result.append(job)
    return result


from job_hunter.feedback import build_feedback_context


def ai_score_jobs(jobs: list[dict[str, Any]], config: JobHunterConfig, db: StateDB) -> list[dict[str, Any]]:
    # 10.4: Build feedback context for AI scoring
    feedback_ctx = build_feedback_context(db)
    for job in jobs:
        jd_text = job.get("jd_text", "")
        if not jd_text:
            job["match_score"] = _fallback_score(job)
            job["_score_source"] = "fallback"
            continue

        sid = job.get("security_id", "")
        result = run_boss("ai", "analyze-jd", jd_text, resume=config.resume, timeout=120)
        if result.get("ok"):
            score_data = result.get("data", {})
            job["match_score"] = score_data.get("match_score", _fallback_score(job))
            job["match_analysis"] = score_data.get("match_analysis", "")
            job["_score_source"] = "ai"
        else:
            job["match_score"] = _fallback_score(job)
            job["_score_source"] = "fallback"

    return jobs


def rank_jobs(jobs: list[dict[str, Any]], config: JobHunterConfig, db: StateDB) -> list[dict[str, Any]]:
    for job in jobs:
        score = job.get("match_score", 0)

        # Freshness bonus
        posted_time = job.get("posted_time", "") or job.get("publishTime", "")
        if posted_time:
            try:
                posted_ts = float(posted_time) / 1000 if len(str(posted_time)) > 10 else float(posted_time)
                age_days = (time.time() - posted_ts) / 86400
                if age_days < 1:
                    score += 5
                elif age_days < 3:
                    score += 3
                elif age_days > 7:
                    score -= 10
            except (ValueError, TypeError):
                pass

        # Boss activity
        boss_active = job.get("boss_active", "") or job.get("bossActiveTime", "")
        if boss_active == "今日活跃" or boss_active == "刚刚活跃":
            score += 3
        elif boss_active == "一个月内未活跃":
            score -= 15

        # Company preference
        company = job.get("company", "")
        if company in config.company_whitelist:
            score += 10

        job["match_score"] = min(max(score, 0), 100)

    jobs.sort(key=lambda j: j.get("match_score", 0), reverse=True)
    return jobs


def add_to_candidate_pool(jobs: list[dict[str, Any]], db: StateDB) -> None:
    for job in jobs:
        db.add_candidate({
            "security_id": job.get("security_id", ""),
            "job_id": job.get("job_id", ""),
            "preset": job.get("_preset", ""),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "salary": job.get("salary", ""),
            "city": job.get("city", ""),
            "match_score": job.get("match_score", 0),
            "status": "scored",
            "jd_text": job.get("jd_text", ""),
        })
    db.expire_old_candidates()


def _fallback_score(job: dict[str, Any]) -> float:
    score = 50.0
    if job.get("title", ""):
        score += 5
    if job.get("salary", ""):
        score += 5
    if job.get("welfare"):
        score += 5
    return score


def _parse_salary_max(salary_str: str) -> int:
    try:
        parts = salary_str.lower().replace("k", "").split("-")
        if len(parts) == 2:
            return int(parts[1].strip()) * 1000
        return int(parts[0].strip()) * 1000
    except (ValueError, IndexError):
        return 0


def _parse_salary_min(salary_str: str) -> int:
    try:
        parts = salary_str.lower().replace("k", "").split("-")
        return int(parts[0].strip()) * 1000
    except (ValueError, IndexError):
        return 0
