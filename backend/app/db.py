"""DB 연결과 테이블 정의. SQLite(기본)와 PostgreSQL 에서 같은 코드가 돈다 (SQLAlchemy Core).

- 기본값: data/dorothy.db (SQLite). Docker 없이 바로 쓸 수 있다.
- DOROTHY_DATABASE_URL=postgresql+psycopg://... 를 주면 PostgreSQL 을 쓴다.

작업과 프리셋은 목록 조회에 쓰는 값만 컬럼으로 두고, 나머지는 data 한 칸에 통째로 넣는다.
PostgreSQL 에서는 data 가 JSONB 라서 나중에 태그나 파라미터로 검색할 때 그대로 쓸 수 있다.
"""

from __future__ import annotations

import pathlib

from sqlalchemy import JSON, Column, Engine, Index, MetaData, String, Table, UniqueConstraint, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

metadata = MetaData()
JsonData = JSON().with_variant(JSONB(), "postgresql")

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("created_at", String(40), nullable=False),
    Column("status", String(16), nullable=False),
    Column("data", JsonData, nullable=False),
    Index("jobs_created_at", "created_at"),
    Index("jobs_status", "status"),
)

presets = Table(
    "presets",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("type", String(16), nullable=False),
    Column("name", String(50), nullable=False),
    Column("data", JsonData, nullable=False),
    UniqueConstraint("type", "name", name="presets_type_name"),
)


def database_url(target: str | pathlib.Path) -> str:
    """경로면 SQLite URL 로, URL 이면 그대로 쓴다."""
    text = str(target)
    if "://" in text:
        return text
    if text == ":memory:":
        return "sqlite://"
    path = pathlib.Path(text).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def make_engine(target: str | pathlib.Path) -> Engine:
    url = database_url(target)
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url == "sqlite://":
            kwargs["poolclass"] = StaticPool  # 메모리 DB 는 연결 하나를 같이 써야 한다.
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _record):
            # API 와 Celery 워커가 같은 파일을 쓸 때 잠깐 잠겨 있어도 기다리게 한다.
            conn.execute("PRAGMA busy_timeout = 5000")

    else:
        engine = create_engine(url, pool_pre_ping=True)
    metadata.create_all(engine)
    return engine


def upsert(engine: Engine, table: Table, values: dict, conflict: list[str], update: list[str]):
    """INSERT ... ON CONFLICT DO UPDATE. SQLite 와 PostgreSQL 이 같은 문법을 쓰지만 생성 함수가 다르다."""
    insert = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    stmt = insert(table).values(**values)
    return stmt.on_conflict_do_update(index_elements=conflict, set_={c: stmt.excluded[c] for c in update})
