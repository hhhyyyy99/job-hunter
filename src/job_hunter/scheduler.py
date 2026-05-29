import datetime
import time
from pathlib import Path
from typing import Any

import httpx

from job_hunter.config import JobHunterConfig, run_boss
from job_hunter.db import StateDB

BRIDGE_URL = "http://127.0.0.1:19826"


def is_bridge_running() -> bool:
    try:
        resp = httpx.get(f"{BRIDGE_URL}/ping", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


def is_extension_connected() -> bool:
    try:
        resp = httpx.get(f"{BRIDGE_URL}/status", timeout=2.0)
        data = resp.json()
        return bool(data.get("extensionConnected", False))
    except Exception:
        return False


def is_active_hours(config: JobHunterConfig) -> bool:
    now = datetime.datetime.now()
    start_h, start_m = map(int, config.active_hours_start.split(":"))
    end_h, end_m = map(int, config.active_hours_end.split(":"))
    start = now.replace(hour=start_h, minute=start_m, second=0)
    end = now.replace(hour=end_h, minute=end_m, second=0)
    return start <= now <= end


def is_weekday() -> bool:
    return datetime.date.today().weekday() < 5


def is_daily_time_reached(config: JobHunterConfig) -> bool:
    now = datetime.datetime.now()
    target_h, target_m = map(int, config.daily_time.split(":"))
    target = now.replace(hour=target_h, minute=target_m, second=0)
    return now >= target


def check_login_state() -> dict[str, Any]:
    result = run_boss("status")
    return result


def check_ai_service() -> bool:
    result = run_boss("ai", "config")
    return result.get("ok", False) and result.get("data", {}).get("api_key_set", False)


def try_renew_token_via_bridge() -> bool:
    result = run_boss("login", "--bridge")
    return result.get("ok", False)


def check_disk_space(data_dir: Path, min_mb: int = 500) -> bool:
    try:
        stat = __import__("shutil").disk_usage(data_dir)
        return stat.free > min_mb * 1024 * 1024
    except Exception:
        return True


def health_check(config: JobHunterConfig, data_dir: Path) -> dict[str, Any]:
    results = {
        "bridge_running": False,
        "extension_connected": False,
        "login_valid": False,
        "ai_available": False,
        "disk_ok": True,
        "write_ops_enabled": False,
    }

    results["bridge_running"] = is_bridge_running()
    results["extension_connected"] = is_extension_connected() if results["bridge_running"] else False

    login = check_login_state()
    results["login_valid"] = login.get("data", {}).get("authenticated", False) if login.get("ok") else False

    if not results["login_valid"] and results["extension_connected"]:
        if try_renew_token_via_bridge():
            results["login_valid"] = True

    results["ai_available"] = check_ai_service()
    results["disk_ok"] = check_disk_space(data_dir)
    results["write_ops_enabled"] = results["extension_connected"] and results["login_valid"]

    return results


def should_run_daily_pipeline(config: JobHunterConfig, db: StateDB, health: dict[str, Any]) -> bool:
    today = datetime.date.today().isoformat()

    if db.is_today_done(today):
        return False

    if not health["bridge_running"] or not health["extension_connected"]:
        return False

    if config.run_on_weekdays_only and not is_weekday():
        return False

    if not is_daily_time_reached(config):
        return False

    return True
