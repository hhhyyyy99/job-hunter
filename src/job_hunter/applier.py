import random
import time
from typing import Any

from job_hunter.config import JobHunterConfig, run_boss
from job_hunter.db import StateDB


def apply_pipeline(config: JobHunterConfig, db: StateDB) -> dict[str, Any]:
    candidates = db.get_pending_candidates()
    applied = []
    skipped = []
    today_count = db.count_applies_today()

    for job in candidates:
        if today_count >= config.max_per_day:
            skipped.append({**job, "reason": "daily_quota_exhausted"})
            continue

        company = job.get("company", "")
        if db.count_company_applies_since(company, days=7) >= config.max_per_company_per_week:
            skipped.append({**job, "reason": "company_limit_reached"})
            continue

        sid = job.get("security_id", "")
        jid = job.get("job_id", "")
        if db.is_applied(sid, jid):
            skipped.append({**job, "reason": "already_applied"})
            continue

        result = run_boss("apply", sid, jid, timeout=30)
        if result.get("ok"):
            db.mark_applied(sid, jid)
            db.record_apply(sid, jid, company, job.get("title", ""), job.get("match_score", 0), "success")
            applied.append(job)
            today_count += 1

            delay = random.uniform(config.min_interval_sec, config.min_interval_sec * 2)
            time.sleep(delay)
        else:
            error = result.get("error", {})
            code = error.get("code", "UNKNOWN")
            if code == "RATE_LIMITED":
                skipped.append({**job, "reason": "platform_rate_limited"})
                break
            elif code == "ALREADY_APPLIED":
                db.mark_applied(sid, jid)
                db.record_apply(sid, jid, company, job.get("title", ""), job.get("match_score", 0), "duplicate")
                skipped.append({**job, "reason": "already_applied"})
            else:
                db.record_apply(sid, jid, company, job.get("title", ""), job.get("match_score", 0), "failed")
                skipped.append({**job, "reason": f"apply_failed: {code}"})

    return {"applied": applied, "skipped": skipped, "total": len(candidates)}
