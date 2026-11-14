"""생성 기록 저장소 (SQLite).

작업 한 건을 한 행으로 저장한다. 목록 조회에 쓰는 값만 컬럼으로 두고
나머지(태그, 프롬프트, 파라미터)는 Job JSON 그대로 data 에 넣는다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pipeline import Job

UNFINISHED = ("queued", "tagging", "generating")


class JobStore:
    def __init__(self, path: pathlib.Path | str):
        if str(path) != ":memory:":
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        # 쓰기는 파이프라인 락 안에서, 읽기는 이벤트 루프에서만 하므로 한 연결을 공유한다.
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id         TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status     TEXT NOT NULL,
                data       TEXT NOT NULL
            )
            """
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs (created_at DESC)")

    def save(self, job: "Job") -> None:
        self._db.execute(
            "INSERT INTO jobs (id, created_at, status, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, data = excluded.data",
            (job.id, job.created_at, job.status, job.model_dump_json()),
        )

    def get(self, job_id: str) -> "Job | None":
        row = self._db.execute("SELECT data FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._load(row[0]) if row else None

    def list(self, limit: int = 50, offset: int = 0, status: str | None = None) -> "list[Job]":
        where, args = ("WHERE status = ?", [status]) if status else ("", [])
        rows = self._db.execute(
            f"SELECT data FROM jobs {where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        return [self._load(r[0]) for r in rows]

    def count(self, status: str | None = None) -> int:
        where, args = ("WHERE status = ?", [status]) if status else ("", [])
        return self._db.execute(f"SELECT COUNT(*) FROM jobs {where}", args).fetchone()[0]

    def fail_unfinished(self, reason: str) -> int:
        """서버가 꺼지며 끝나지 못한 작업을 실패로 정리한다. 정리한 건수를 돌려준다."""
        marks = ",".join("?" * len(UNFINISHED))
        rows = self._db.execute(f"SELECT data FROM jobs WHERE status IN ({marks})", UNFINISHED).fetchall()
        for (data,) in rows:
            job = self._load(data)
            job.status, job.error = "failed", reason
            self.save(job)
        return len(rows)

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _load(data: str) -> "Job":
        from .pipeline import Job

        return Job.model_validate_json(data)
