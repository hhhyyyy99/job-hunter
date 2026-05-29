import json
import sqlite3
import time
from pathlib import Path
from types import TracebackType
from typing import Any


class StateDB:
    """job-hunter 本地状态数据库（SQLite）。"""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS candidate_pool (
                security_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                preset TEXT NOT NULL,
                title TEXT DEFAULT '',
                company TEXT DEFAULT '',
                salary TEXT DEFAULT '',
                city TEXT DEFAULT '',
                match_score REAL DEFAULT 0,
                status TEXT DEFAULT 'pending',
                jd_text TEXT DEFAULT '',
                scored_at REAL,
                applied_at REAL,
                skipped_at REAL,
                reason TEXT DEFAULT '',
                PRIMARY KEY (security_id, job_id)
            );

            CREATE TABLE IF NOT EXISTS apply_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                security_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                company TEXT DEFAULT '',
                title TEXT DEFAULT '',
                match_score REAL DEFAULT 0,
                result TEXT DEFAULT 'success',
                applied_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_state (
                security_id TEXT PRIMARY KEY,
                company TEXT DEFAULT '',
                title TEXT DEFAULT '',
                gid TEXT DEFAULT '',
                depth INTEGER DEFAULT 0,
                stage TEXT DEFAULT 'chatting',
                auto_reply_count INTEGER DEFAULT 0,
                last_activity REAL DEFAULT 0,
                summary TEXT DEFAULT '',
                interview_time TEXT DEFAULT '',
                interview_location TEXT DEFAULT '',
                interview_interviewer TEXT DEFAULT '',
                interview_round TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_type TEXT NOT NULL,
                target TEXT NOT NULL,
                action TEXT NOT NULL,
                context TEXT DEFAULT '',
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_log (
                date TEXT PRIMARY KEY,
                applied_count INTEGER DEFAULT 0,
                replied_count INTEGER DEFAULT 0,
                new_jobs_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'completed',
                error TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
        """)

    # ── Candidate Pool ──────────────────────────────────────────────

    def add_candidate(self, item: dict[str, Any]) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO candidate_pool
               (security_id, job_id, preset, title, company, salary, city,
                match_score, status, jd_text, scored_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.get("security_id", ""),
                item.get("job_id", ""),
                item.get("preset", ""),
                item.get("title", ""),
                item.get("company", ""),
                item.get("salary", ""),
                item.get("city", ""),
                item.get("match_score", 0),
                item.get("status", "pending"),
                item.get("jd_text", ""),
                time.time(),
            ),
        )
        self._conn.commit()

    def get_pending_candidates(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_pool WHERE status IN ('pending', 'scored') ORDER BY match_score DESC"
        ).fetchall()
        return [_row_to_dict(row, self._conn.execute("PRAGMA table_info(candidate_pool)").fetchall())
                for row in rows]

    def mark_applied(self, security_id: str, job_id: str) -> None:
        self._conn.execute(
            "UPDATE candidate_pool SET status='applied', applied_at=? WHERE security_id=? AND job_id=?",
            (time.time(), security_id, job_id),
        )
        self._conn.commit()

    def mark_skipped(self, security_id: str, job_id: str, reason: str = "") -> None:
        self._conn.execute(
            "UPDATE candidate_pool SET status='skipped', reason=?, skipped_at=? WHERE security_id=? AND job_id=?",
            (reason, time.time(), security_id, job_id),
        )
        self._conn.commit()

    def expire_old_candidates(self, days: int = 7) -> int:
        cutoff = time.time() - days * 86400
        cursor = self._conn.execute(
            "UPDATE candidate_pool SET status='expired' WHERE status='pending' AND scored_at < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    # ── Apply Records ────────────────────────────────────────────────

    def record_apply(self, security_id: str, job_id: str, company: str, title: str, match_score: float, result: str = "success") -> None:
        self._conn.execute(
            "INSERT INTO apply_records (security_id, job_id, company, title, match_score, result, applied_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (security_id, job_id, company, title, match_score, result, time.time()),
        )
        self._conn.commit()

    def count_applies_today(self) -> int:
        today_start = time.time() - time.time() % 86400
        row = self._conn.execute(
            "SELECT COUNT(*) FROM apply_records WHERE applied_at >= ?",
            (today_start,),
        ).fetchone()
        return row[0] if row else 0

    def count_company_applies_since(self, company: str, days: int = 7) -> int:
        cutoff = time.time() - days * 86400
        row = self._conn.execute(
            "SELECT COUNT(*) FROM apply_records WHERE company=? AND applied_at >= ?",
            (company, cutoff),
        ).fetchone()
        return row[0] if row else 0

    def is_applied(self, security_id: str, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM apply_records WHERE security_id=? AND job_id=?",
            (security_id, job_id),
        ).fetchone()
        return row is not None

    # ── Conversation State ───────────────────────────────────────────

    def get_conversation(self, security_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM conversation_state WHERE security_id=?",
            (security_id,),
        ).fetchone()
        if row is None:
            return None
        cols = self._conn.execute("PRAGMA table_info(conversation_state)").fetchall()
        return _row_to_dict(row, cols)

    def upsert_conversation(self, data: dict[str, Any]) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO conversation_state
               (security_id, company, title, gid, depth, stage, auto_reply_count,
                last_activity, summary, interview_time, interview_location,
                interview_interviewer, interview_round, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("security_id", ""),
                data.get("company", ""),
                data.get("title", ""),
                data.get("gid", ""),
                data.get("depth", 0),
                data.get("stage", "chatting"),
                data.get("auto_reply_count", 0),
                data.get("last_activity", time.time()),
                data.get("summary", ""),
                data.get("interview_time", ""),
                data.get("interview_location", ""),
                data.get("interview_interviewer", ""),
                data.get("interview_round", ""),
                json.dumps(data.get("metadata", {}), ensure_ascii=False),
            ),
        )
        self._conn.commit()

    def get_conversations_needing_polling(self) -> list[dict[str, Any]]:
        cutoff = time.time() - 7 * 86400
        rows = self._conn.execute(
            "SELECT * FROM conversation_state WHERE stage NOT IN ('dead', 'rejected') AND last_activity >= ?",
            (cutoff,),
        ).fetchall()
        cols = self._conn.execute("PRAGMA table_info(conversation_state)").fetchall()
        return [_row_to_dict(r, cols) for r in rows]

    # ── Feedback ─────────────────────────────────────────────────────

    def add_feedback(self, feedback_type: str, target: str, action: str, context: str = "") -> None:
        self._conn.execute(
            "INSERT INTO feedback (feedback_type, target, action, context, created_at) VALUES (?, ?, ?, ?, ?)",
            (feedback_type, target, action, context, time.time()),
        )
        self._conn.commit()

    def get_feedback(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        cols = self._conn.execute("PRAGMA table_info(feedback)").fetchall()
        return [_row_to_dict(r, cols) for r in rows]

    # ── Daily Log ────────────────────────────────────────────────────

    def mark_daily_done(self, date: str, applied: int = 0, replied: int = 0, new_jobs: int = 0, status: str = "completed", error: str = "") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO daily_log (date, applied_count, replied_count, new_jobs_count, status, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (date, applied, replied, new_jobs, status, error, time.time()),
        )
        self._conn.commit()

    def is_today_done(self, date: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM daily_log WHERE date=? AND status='completed'",
            (date,),
        ).fetchone()
        return row is not None

    # ── Lifecycle ────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateDB":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


def _row_to_dict(row: tuple, cols: list[tuple]) -> dict[str, Any]:
    return {cols[i][1]: row[i] for i in range(len(cols))}
