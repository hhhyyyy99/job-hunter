import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path.home() / ".boss-agent" / "job-hunter"

# Try "boss" first, fall back to "uv run boss" if not on PATH
_BOSS_CMD: list[str] | None = None


def _resolve_boss_cmd() -> list[str]:
    global _BOSS_CMD
    if _BOSS_CMD is not None:
        return _BOSS_CMD
    try:
        subprocess.run(["boss", "--help"], capture_output=True, timeout=5)
        _BOSS_CMD = ["boss"]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _BOSS_CMD = ["uv", "run", "boss"]
    return _BOSS_CMD


def run_boss(*args: str, timeout: int = 60, **kwargs: str) -> dict[str, Any]:
    """Execute a boss-agent-cli command. Falls back to `uv run boss` if `boss` is not on PATH."""
    cmd = _resolve_boss_cmd()
    cli_args = [*cmd, *args]
    for key, value in kwargs.items():
        cli_args.append(f"--{key.replace('_', '-')}")
        cli_args.append(str(value))
    try:
        result = subprocess.run(
            cli_args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return json.loads(result.stdout) if result.stdout.strip() else {"ok": False}
    except FileNotFoundError:
        return {"ok": False}
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return {"ok": False}


@dataclass
class JobHunterConfig:
    resume: str = "默认简历"
    presets: list[str] = field(default_factory=lambda: ["默认搜索"])

    # AI
    ai_matching_provider: str = ""
    ai_matching_model: str = ""
    ai_reply_provider: str = ""
    ai_reply_model: str = ""

    # Match thresholds
    auto_apply_threshold: int = 75
    suggest_threshold: int = 50

    # Apply limits
    max_per_day: int = 10
    min_interval_sec: int = 90
    max_per_company_per_week: int = 2

    # Follow-up
    follow_up_enabled: bool = True
    auto_reply: bool = True
    reply_tone: str = "简洁专业"
    deep_analysis_threshold: int = 5
    chase_after_days: int = 2
    max_chases: int = 2
    dead_after_days: int = 7
    re_engage_days: int = 4
    interview_intent_notify: bool = True
    interview_keywords: list[str] = field(default_factory=lambda: [
        "面试", "面谈", "约个时间", "到岗", "入职", "方便聊",
    ])
    sensitive_topics: list[str] = field(default_factory=lambda: [
        "薪资", "期望薪资", "目前薪资", "工资",
    ])

    # Conversation
    max_auto_reply_depth: int = 5
    max_auto_reply_count: int = 8
    notify_on_deep: bool = True
    summary_after_rounds: int = 8

    # Schedule
    daily_time: str = "08:00"
    active_hours_start: str = "09:00"
    active_hours_end: str = "21:00"
    poll_interval_minutes: int = 15
    run_on_weekdays_only: bool = True

    # Interview
    interview_auto_detect: bool = True
    interview_auto_prep_material: bool = True
    interview_prep_question_count: int = 10
    interview_remind_before_days: int = 1
    interview_remind_on_day: bool = True
    interview_suggest_thank_you: bool = True
    interview_thank_you_after_hours: int = 24
    interview_follow_up_after_days: int = 3
    interview_mark_dead_after_days: int = 7
    interview_urgent_notify: bool = True

    # Report
    report_output_dir: str = str(DEFAULT_CONFIG_DIR / "reports")

    # Privacy
    privacy_mask_pii: bool = True
    privacy_mask_fields: list[str] = field(default_factory=lambda: ["name", "phone", "email", "wechat"])
    privacy_local_model_endpoint: str = ""

    # Preferences
    company_blacklist: list[str] = field(default_factory=list)
    company_whitelist: list[str] = field(default_factory=list)
    industry_exclude: list[str] = field(default_factory=list)
    min_salary: str = ""
    target_cities: list[str] = field(default_factory=list)


def load_config(config_path: Path | None = None) -> JobHunterConfig:
    config_dir = DEFAULT_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)

    if config_path is None:
        config_path = config_dir / "config.yaml"

    if not config_path.exists():
        return JobHunterConfig()

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return _parse_config(raw)


def _parse_config(raw: dict[str, Any]) -> JobHunterConfig:
    cfg = JobHunterConfig()

    # Top-level
    if "resume" in raw:
        cfg.resume = raw["resume"]
    if "presets" in raw:
        cfg.presets = raw["presets"]

    # AI
    ai = raw.get("ai", {})
    if matching := ai.get("matching", {}):
        cfg.ai_matching_provider = matching.get("provider", "")
        cfg.ai_matching_model = matching.get("model", "")
    if reply := ai.get("reply", {}):
        cfg.ai_reply_provider = reply.get("provider", "")
        cfg.ai_reply_model = reply.get("model", "")

    # Match
    match = raw.get("match", {})
    if "auto_apply_threshold" in match:
        cfg.auto_apply_threshold = match["auto_apply_threshold"]
    if "suggest_threshold" in match:
        cfg.suggest_threshold = match["suggest_threshold"]

    # Apply
    apply = raw.get("apply", {})
    if "max_per_day" in apply:
        cfg.max_per_day = apply["max_per_day"]
    if "min_interval_sec" in apply:
        cfg.min_interval_sec = apply["min_interval_sec"]
    if "max_per_company_per_week" in apply:
        cfg.max_per_company_per_week = apply["max_per_company_per_week"]

    # Follow-up
    fu = raw.get("follow_up", {})
    if "enabled" in fu:
        cfg.follow_up_enabled = fu["enabled"]
    if "auto_reply" in fu:
        cfg.auto_reply = fu["auto_reply"]
    if "reply_tone" in fu:
        cfg.reply_tone = fu["reply_tone"]
    if "deep_analysis_threshold" in fu:
        cfg.deep_analysis_threshold = fu["deep_analysis_threshold"]
    if "chase_after_days" in fu:
        cfg.chase_after_days = fu["chase_after_days"]
    if "max_chases" in fu:
        cfg.max_chases = fu["max_chases"]
    if "dead_after_days" in fu:
        cfg.dead_after_days = fu["dead_after_days"]
    if "re_engage_days" in fu:
        cfg.re_engage_days = fu["re_engage_days"]
    if "interview_intent_notify" in fu:
        cfg.interview_intent_notify = fu["interview_intent_notify"]
    if "interview_keywords" in fu:
        cfg.interview_keywords = fu["interview_keywords"]
    if "sensitive_topics" in fu:
        cfg.sensitive_topics = fu["sensitive_topics"]

    # Conversation
    conv = raw.get("conversation", {})
    if "max_auto_reply_depth" in conv:
        cfg.max_auto_reply_depth = conv["max_auto_reply_depth"]
    if "max_auto_reply_count" in conv:
        cfg.max_auto_reply_count = conv["max_auto_reply_count"]
    if "notify_on_deep" in conv:
        cfg.notify_on_deep = conv["notify_on_deep"]
    if "summary_after_rounds" in conv:
        cfg.summary_after_rounds = conv["summary_after_rounds"]

    # Schedule
    sched = raw.get("schedule", {})
    if "daily_time" in sched:
        cfg.daily_time = sched["daily_time"]
    if "active_hours_start" in sched:
        cfg.active_hours_start = sched["active_hours_start"]
    if "active_hours_end" in sched:
        cfg.active_hours_end = sched["active_hours_end"]
    if "poll_interval_minutes" in sched:
        cfg.poll_interval_minutes = sched["poll_interval_minutes"]
    if "run_on_weekdays_only" in sched:
        cfg.run_on_weekdays_only = sched["run_on_weekdays_only"]

    # Interview
    iv = raw.get("interview", {})
    if "auto_detect" in iv:
        cfg.interview_auto_detect = iv["auto_detect"]
    if "auto_prep_material" in iv:
        cfg.interview_auto_prep_material = iv["auto_prep_material"]
    if "prep_question_count" in iv:
        cfg.interview_prep_question_count = iv["prep_question_count"]
    if "remind_before_days" in iv:
        cfg.interview_remind_before_days = iv["remind_before_days"]
    if "remind_on_day" in iv:
        cfg.interview_remind_on_day = iv["remind_on_day"]
    if "suggest_thank_you" in iv:
        cfg.interview_suggest_thank_you = iv["suggest_thank_you"]
    if "thank_you_after_hours" in iv:
        cfg.interview_thank_you_after_hours = iv["thank_you_after_hours"]
    if "follow_up_after_days" in iv:
        cfg.interview_follow_up_after_days = iv["follow_up_after_days"]
    if "mark_dead_after_days" in iv:
        cfg.interview_mark_dead_after_days = iv["mark_dead_after_days"]
    if "urgent_notify" in iv:
        cfg.interview_urgent_notify = iv["urgent_notify"]

    # Report
    rep = raw.get("report", {})
    if "output_dir" in rep:
        cfg.report_output_dir = os.path.expanduser(rep["output_dir"])

    # Privacy
    priv = raw.get("privacy", {})
    if "mask_pii" in priv:
        cfg.privacy_mask_pii = priv["mask_pii"]
    if "mask_fields" in priv:
        cfg.privacy_mask_fields = priv["mask_fields"]
    if "local_model_endpoint" in priv:
        cfg.privacy_local_model_endpoint = priv.get("local_model_endpoint") or ""

    # Preferences
    pref = raw.get("preferences", {})
    if "company_blacklist" in pref:
        cfg.company_blacklist = pref["company_blacklist"]
    if "company_whitelist" in pref:
        cfg.company_whitelist = pref["company_whitelist"]
    if "industry_exclude" in pref:
        cfg.industry_exclude = pref["industry_exclude"]
    if "min_salary" in pref:
        cfg.min_salary = pref["min_salary"] or ""
    if "target_cities" in pref:
        cfg.target_cities = pref["target_cities"]

    return cfg
