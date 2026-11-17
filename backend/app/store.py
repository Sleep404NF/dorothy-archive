"""생성 기록 저장소 (SQLite 또는 PostgreSQL, app/db.py 참고).

작업 한 건을 한 행으로 저장한다. 목록 조회에 쓰는 값만 컬럼으로 두고
나머지(태그, 프롬프트, 파라미터)는 Job 을 통째로 data(JSON/JSONB) 에 넣는다.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from .db import jobs, make_engine, upsert

if TYPE_CHECKING:
    from .pipeline import Job

UNFINISHED = ("queued", "tagging", "generating")


class JobStore:
    def __init__(self, target: pathlib.Path | str):
        """target: SQLite 파일 경로 또는 DB URL (postgresql+psycopg://...)."""
        self._engine = make_engine(target)

    @property
    def dialect(self) -> str:
        return self._engine.dialect.name

    def save(self, job: "Job") -> None:
        values = {"id": job.id, "created_at": job.created_at, "status": job.status, "data": job.model_dump(mode="json")}
        with self._engine.begin() as conn:
            conn.execute(upsert(self._engine, jobs, values, conflict=["id"], update=["status", "data"]))

    def get(self, job_id: str) -> "Job | None":
        with self._engine.connect() as conn:
            data = conn.execute(select(jobs.c.data).where(jobs.c.id == job_id)).scalar()
        return self._load(data) if data else None

    def list(self, limit: int = 50, offset: int = 0, status: str | None = None) -> "list[Job]":
        query = select(jobs.c.data).order_by(jobs.c.created_at.desc(), jobs.c.id.desc()).limit(limit).offset(offset)
        if status:
            query = query.where(jobs.c.status == status)
        with self._engine.connect() as conn:
            return [self._load(d) for d in conn.execute(query).scalars()]

    def count(self, status: str | None = None) -> int:
        query = select(func.count()).select_from(jobs)
        if status:
            query = query.where(jobs.c.status == status)
        with self._engine.connect() as conn:
            return conn.execute(query).scalar_one()

    def fail_unfinished(self, reason: str, statuses: tuple[str, ...] = UNFINISHED) -> int:
        """서버가 꺼지며 끝나지 못한 작업을 실패로 정리한다. 정리한 건수를 돌려준다."""
        with self._engine.connect() as conn:
            rows = conn.execute(select(jobs.c.data).where(jobs.c.status.in_(statuses))).scalars().all()
        for data in rows:
            job = self._load(data)
            job.status, job.error = "failed", reason
            self.save(job)
        return len(rows)

    def close(self) -> None:
        self._engine.dispose()

    @staticmethod
    def _load(data) -> "Job":
        from .pipeline import Job

        return Job.model_validate(data)
