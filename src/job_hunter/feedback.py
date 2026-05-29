import json
import re
from pathlib import Path
from typing import Any

from job_hunter.config import JobHunterConfig
from job_hunter.db import StateDB

FEEDBACK_PATH = Path.home() / ".boss-agent" / "job-hunter" / "feedback.json"


def parse_report_feedback(report_path: str) -> list[dict[str, Any]]:
    feedback = []
    try:
        content = Path(report_path).read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return feedback

    # Parse [x] marked apply lines
    apply_pattern = re.compile(r'- \*\*(.+?)\*\* · (.+?) · .+? 匹配分 (\d+) \[x\]')
    for match in apply_pattern.finditer(content):
        company = match.group(1).strip()
        title = match.group(2).strip()
        score = int(match.group(3))
        feedback.append({
            "type": "apply_skip",
            "target": company,
            "action": "skip",
            "context": json.dumps({"title": title, "score": score}, ensure_ascii=False),
        })

    # Parse [x] marked reply lines
    reply_pattern = re.compile(r'→ 建议回复: (.+?) \[x\]')
    for match in reply_pattern.finditer(content):
        draft = match.group(1).strip()
        feedback.append({
            "type": "reply_issue",
            "target": draft[:50],
            "action": "inappropriate",
            "context": json.dumps({"full_draft": draft}, ensure_ascii=False),
        })

    return feedback


def load_json_feedback() -> dict[str, Any]:
    if not FEEDBACK_PATH.exists():
        return {}
    try:
        return json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json_feedback(data: dict[str, Any]) -> None:
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_feedback(report_feedback: list[dict[str, Any]], json_feedback: dict[str, Any]) -> None:
    # Merge report-parsed feedback into JSON store
    for item in report_feedback:
        key = f"{item['target']}:{item['action']}"
        if key not in json_feedback:
            json_feedback[key] = item
    save_json_feedback(json_feedback)


def apply_feedback_rules(config: JobHunterConfig, db: StateDB) -> list[str]:
    # Apply blacklist rules from config
    blacklist = config.company_blacklist

    # Also load from feedback JSON
    fb = load_json_feedback()
    for key, item in fb.items():
        if item.get("action") == "skip" and item.get("type") == "apply_skip":
            target = item.get("target", "")
            if target and target not in blacklist:
                blacklist.append(target)

    # Update config
    config.company_blacklist = blacklist
    return blacklist


def build_feedback_context(db: StateDB) -> str:
    feedback_items = db.get_feedback()
    if not feedback_items:
        return ""

    lines = ["用户历史反馈："]
    for item in feedback_items[:10]:
        lines.append(f"- {item.get('feedback_type', '')}: {item.get('target', '')} → {item.get('action', '')}")
    return "\n".join(lines)
