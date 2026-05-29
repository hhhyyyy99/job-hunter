import json
import os
import random
import time
from pathlib import Path
from typing import Any

from job_hunter.config import JobHunterConfig, run_boss
from job_hunter.db import StateDB

CONV_DIR = Path.home() / ".boss-agent" / "job-hunter" / "conversations"
PENDING_DIR = Path.home() / ".boss-agent" / "job-hunter" / "pending_replies"


def poll_conversations(config: JobHunterConfig, db: StateDB) -> list[dict[str, Any]]:
    result = run_boss("chat")
    if not result.get("ok"):
        return []

    chat_items = result.get("data", [])
    triggered = []

    for item in chat_items:
        unread = item.get("unread", 0) or item.get("unreadMsgCount", 0)
        if unread <= 0:
            continue

        sid = item.get("security_id", "")
        if not sid:
            continue

        triggered.append({
            "security_id": sid,
            "company": item.get("brand_name", "") or item.get("company", ""),
            "title": item.get("title", ""),
            "unread": unread,
            "last_msg": item.get("last_msg", "") or item.get("lastMsg", ""),
            "last_time": item.get("last_time", "") or item.get("lastTS", ""),
        })

    return triggered


def analyze_and_respond(
    conversations: list[dict[str, Any]],
    config: JobHunterConfig,
    db: StateDB,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    results = []
    # 6.8: Retry any pending replies from when Bridge was offline
    _retry_pending_replies(config, db, dry_run)

    for i, conv in enumerate(conversations):
        if i > 0 and not dry_run:
            time.sleep(random.uniform(120, 300))

        sid = conv["security_id"]
        last_msg = conv["last_msg"]

        chat_text = _fetch_chat_history(sid)

        state = db.get_conversation(sid)
        if state is None:
            state = {
                "security_id": sid,
                "company": conv.get("company", ""),
                "title": conv.get("title", ""),
                "depth": 0,
                "stage": "chatting",
                "auto_reply_count": 0,
                "summary": "",
            }

        depth = state.get("depth", 0) + 1
        auto_reply_count = state.get("auto_reply_count", 0)
        stage = state.get("stage", "chatting")
        existing_summary = state.get("summary", "")

        # 6.10: Context compression for deep conversations
        if depth > config.summary_after_rounds and chat_text:
            compact = _compress_context(chat_text, existing_summary, config)
            if compact:
                existing_summary = compact
                chat_text = _build_compact_prompt(chat_text, compact)

        if stage == "interview_scheduled" or stage == "interview":
            # 7.4: Generate interview prep materials if interview stage
            prep_material = _generate_interview_prep(sid, config, db) if config.interview_auto_prep_material else None
            entry = {**conv, "action": "notify_user", "reason": "interview_stage"}
            if prep_material:
                entry["prep_material"] = prep_material
            results.append(entry)
            _update_state(db, sid, conv, depth, auto_reply_count, stage, existing_summary)
            continue

        analysis = _analyze_intent(last_msg, chat_text, config, db)
        action = _classify_action(analysis, depth, config)

        if action == "auto_reply" and config.auto_reply and not dry_run:
            reply_draft = _generate_reply(last_msg, chat_text, config)
            if reply_draft:
                send_result = _send_reply(sid, reply_draft)
                if send_result.get("ok"):
                    auto_reply_count += 1
                    results.append({**conv, "action": "auto_reply", "draft": reply_draft, "sent": True})
                else:
                    # 6.8: Queue pending reply for Bridge reconnection retry
                    _enqueue_pending_reply(sid, reply_draft, conv)
                    results.append({**conv, "action": "auto_reply", "draft": reply_draft, "sent": False, "queued": True, "error": send_result.get("error")})
            else:
                results.append({**conv, "action": "notify_user", "reason": "reply_generation_failed"})
        elif action == "urgent_notify":
            results.append({**conv, "action": "urgent_notify", "analysis": analysis})
            if config.interview_auto_detect and _is_interview_intent(analysis, config):
                stage = "interview_scheduled"
                _extract_interview_info(analysis, db, sid, conv)
        else:
            results.append({**conv, "action": "notify_user", "analysis": analysis})

        _update_state(db, sid, conv, depth, auto_reply_count, stage, existing_summary)

    return results


def _classify_action(analysis: dict[str, Any], depth: int, config: JobHunterConfig) -> str:
    intent = analysis.get("intent", "").lower()
    if depth >= config.max_auto_reply_depth:
        return "notify_user"
    if any(kw in intent for kw in ["面试", "offer", "录用", "入职"]):
        return "urgent_notify"
    if any(topic in intent for topic in config.sensitive_topics):
        return "notify_user"
    confidence = analysis.get("confidence", 0)
    if depth <= 3 and confidence > 0.7:
        return "auto_reply"
    if 4 <= depth <= 5 and confidence > 0.85:
        return "auto_reply"
    return "notify_user"


def _is_interview_intent(analysis: dict[str, Any], config: JobHunterConfig) -> bool:
    intent = analysis.get("intent", "").lower()
    match_points = analysis.get("match_points", [])
    all_text = intent + " " + " ".join(match_points)
    return any(kw in all_text for kw in config.interview_keywords)


def _extract_interview_info(analysis: dict[str, Any], db: StateDB, sid: str, conv: dict[str, Any]) -> None:
    state = db.get_conversation(sid) or {}
    raw = analysis.get("raw", {}) if isinstance(analysis.get("raw"), dict) else analysis
    state["stage"] = "interview_scheduled"
    state["interview_time"] = raw.get("interview_time", "") or raw.get("time", "")
    state["interview_location"] = raw.get("interview_location", "") or raw.get("location", "")
    state["interview_interviewer"] = raw.get("interview_interviewer", "") or raw.get("interviewer", "")
    state["interview_round"] = raw.get("interview_round", "") or raw.get("round", "")
    db.upsert_conversation(state)


def _update_state(db: StateDB, sid: str, conv: dict[str, Any], depth: int, auto_reply_count: int, stage: str, summary: str = "") -> None:
    db.upsert_conversation({
        "security_id": sid,
        "company": conv.get("company", ""),
        "title": conv.get("title", ""),
        "depth": depth,
        "stage": stage,
        "auto_reply_count": auto_reply_count,
        "last_activity": time.time(),
        "summary": summary,
    })


def _fetch_chat_history(sid: str) -> str:
    result = run_boss("chatmsg", sid, count="20")
    if not result.get("ok"):
        return ""
    messages = result.get("data", [])
    lines = []
    for msg in messages:
        from_who = msg.get("from", "")
        text = msg.get("text", "")
        if text:
            lines.append(f"{from_who}: {text}")
    return "\n".join(lines)


def _analyze_intent(last_msg: str, chat_text: str, config: JobHunterConfig, db: StateDB) -> dict[str, Any]:
    result = run_boss("ai", "reply", last_msg, tone=config.reply_tone)
    if result.get("ok"):
        data = result.get("data", {})
        return {
            "intent": data.get("intent_analysis", ""),
            "confidence": 0.8,
            "drafts": data.get("reply_drafts", []),
        }
    return {"intent": "unknown", "confidence": 0.5, "drafts": []}


def _generate_reply(last_msg: str, chat_text: str, config: JobHunterConfig) -> str | None:
    result = run_boss("ai", "reply", last_msg, tone=config.reply_tone)
    if result.get("ok"):
        drafts = result.get("data", {}).get("reply_drafts", [])
        if drafts:
            return drafts[0].get("text", "")
    return None


def _send_reply(sid: str, message: str) -> dict[str, Any]:
    return run_boss("reply", sid, message=message)


# ── 6.8: Bridge 离线 pending 队列 ──────────────────────────────────

def _enqueue_pending_reply(sid: str, message: str, conv: dict[str, Any]) -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "security_id": sid,
        "message": message,
        "company": conv.get("company", ""),
        "title": conv.get("title", ""),
        "queued_at": time.time(),
        "retry_count": 0,
    }
    path = PENDING_DIR / f"{sid}.json"
    path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")


def _retry_pending_replies(config: JobHunterConfig, db: StateDB, dry_run: bool) -> int:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    sent = 0
    for path in sorted(PENDING_DIR.glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)
            continue

        retry_count = entry.get("retry_count", 0)
        if retry_count >= 3:
            path.unlink(missing_ok=True)
            continue

        if dry_run:
            sent += 1
            path.unlink(missing_ok=True)
            continue

        result = _send_reply(entry["security_id"], entry["message"])
        if result.get("ok"):
            sent += 1
            path.unlink(missing_ok=True)
        else:
            entry["retry_count"] = retry_count + 1
            entry["last_error"] = str(result.get("error", {}))
            path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")

    return sent


# ── 6.10: 上下文摘要压缩 ──────────────────────────────────────────

def _compress_context(chat_text: str, existing_summary: str, config: JobHunterConfig) -> str | None:
    if not chat_text:
        return None
    prompt_lines = [
        "请用一段中文摘要以下求职对话的关键信息：",
        "- 已确认的事实（技术栈、经验、到岗时间等）",
        "- 未解决的问题或待确认事项",
        "- HR 的态度（积极/观望/冷淡）",
    ]
    if existing_summary:
        prompt_lines.insert(0, f"之前的摘要：{existing_summary}")
    prompt_lines.append(f"对话内容：\n{chat_text}")
    prompt = "\n\n".join(prompt_lines)

    try:
        from job_hunter.config import run_boss as rb
        result = rb("ai", "analyze-jd", prompt, resume="")
        if result.get("ok"):
            data = result.get("data", {})
            return data.get("match_analysis", "") or data.get("summary", "")
    except Exception:
        pass
    return existing_summary


def _build_compact_prompt(chat_text: str, summary: str) -> str:
    """只传最后 5 轮 + 摘要给 AI。"""
    lines = chat_text.strip().split("\n")
    recent = lines[-10:] if len(lines) > 10 else lines
    return f"对话摘要：{summary}\n\n最近消息：\n" + "\n".join(recent)


# ── 7.4: 面试准备材料生成 ─────────────────────────────────────────

def _generate_interview_prep(sid: str, config: JobHunterConfig, db: StateDB) -> dict[str, Any] | None:
    """Generate interview preparation materials using cached JD text."""
    # Try to get JD from candidate pool
    candidates = db.get_pending_candidates()
    jd_text = ""
    for c in candidates:
        if c.get("security_id") == sid:
            jd_text = c.get("jd_text", "")
            break

    # Also check applied records - they might have the JD
    if not jd_text:
        jd_text = _get_cached_jd(sid)

    if not jd_text:
        return None

    result = run_boss("ai", "interview-prep", jd_text, count=str(config.interview_prep_question_count))
    if result.get("ok"):
        return result.get("data", {})
    return None


def _get_cached_jd(sid: str) -> str:
    cache_path = Path.home() / ".boss-agent" / "job-hunter" / "jd_cache" / f"{sid}.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return data.get("jd_text", "")
        except Exception:
            pass
    return ""
