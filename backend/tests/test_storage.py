"""저장소 전환: DB(SQLite / PostgreSQL)와 이미지 저장소(로컬 / S3 호환), 그리고 옮기기 스크립트.

PostgreSQL 테스트는 DOROTHY_TEST_DATABASE_URL 이 있을 때만 돈다. 예:
    DOROTHY_TEST_DATABASE_URL=postgresql+psycopg://dorothy:dorothy@127.0.0.1:5432/dorothy_test pytest
S3 는 moto 로 흉내 내므로 RustFS 없이 돈다.
"""

import os
import pathlib
import sys

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy import create_engine

from app.config import Settings
from app.db import metadata
from app.main import create_app
from app.pipeline import Job, Pipeline
from app.presets import PresetConflict, PresetIn, PresetStore
from app.storage import LocalStorage, S3Storage
from app.store import JobStore
from test_image_format import PngBackend
from test_pipeline import wait_done

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from migrate_storage import migrate  # noqa: E402

PG_URL = os.getenv("DOROTHY_TEST_DATABASE_URL")


@pytest.fixture(params=["sqlite", "postgresql"])
def db_target(request, tmp_path):
    if request.param == "sqlite":
        return tmp_path / "t.db"
    if not PG_URL:
        pytest.skip("DOROTHY_TEST_DATABASE_URL not set")
    engine = create_engine(PG_URL)
    metadata.drop_all(engine)
    engine.dispose()
    return PG_URL


def job(job_id, status="done", created="2026-01-01T00:00:00.000+00:00", **extra):
    return Job(id=job_id, status=status, created_at=created, negative="n", seed=1, width=8, height=8,
               steps=1, cfg=1.0, backend="x", positive="1girl", **extra)


# --- DB --------------------------------------------------------------------

def test_job_store_round_trip(db_target):
    store = JobStore(db_target)
    store.save(job("a", created="2026-01-01T00:00:01.000+00:00", tags={"subject": ["1girl", "solo"]}))
    store.save(job("b", status="generating", created="2026-01-01T00:00:02.000+00:00"))
    store.save(job("a", created="2026-01-01T00:00:01.000+00:00", error="again"))  # upsert

    assert store.get("a").error == "again"
    assert store.get("missing") is None
    assert [j.id for j in store.list()] == ["b", "a"]
    assert store.count() == 2 and store.count("generating") == 1
    assert store.fail_unfinished("stop") == 1
    assert store.get("b").status == "failed"
    store.close()


def test_preset_store_round_trip(db_target):
    store = PresetStore(db_target)
    body = dict(type="character", name="케이", positive=["1girl", "white hair"])
    created = store.create(PresetIn(**body))
    with pytest.raises(PresetConflict):
        store.create(PresetIn(**body))
    updated = store.update(created.id, PresetIn(**{**body, "positive": ["1girl", "pink eyes"]}))
    assert updated.created_at == created.created_at and store.get(created.id).positive == ["1girl", "pink eyes"]

    store.put(created)  # 옮기기용: id 와 시각까지 그대로 덮어쓴다.
    assert store.get(created.id).positive == ["1girl", "white hair"]
    assert [p.name for p in store.list("character")] == ["케이"]
    assert store.delete(created.id) and not store.delete(created.id)
    store.close()


# --- 이미지 저장소 ----------------------------------------------------------

@pytest.fixture
def s3():
    with mock_aws():
        yield S3Storage(bucket="dorothy-test", region="us-east-1")


def test_local_storage(tmp_path):
    storage = LocalStorage(tmp_path / "out")
    assert storage.get("x.webp") is None and not storage.exists("x.webp")
    storage.put("x.webp", b"data", "image/webp")
    assert storage.get("x.webp") == b"data" and storage.exists("x.webp")


def test_s3_storage_creates_bucket_and_round_trips(s3):
    assert s3.get("x.webp") is None and not s3.exists("x.webp")
    s3.put("x.webp", b"data", "image/webp")
    assert s3.get("x.webp") == b"data" and s3.exists("x.webp")
    obj = boto3.client("s3", region_name="us-east-1").head_object(Bucket="dorothy-test", Key="images/x.webp")
    assert obj["ContentType"] == "image/webp"
    S3Storage(bucket="dorothy-test", region="us-east-1")  # 이미 있는 버킷이어도 괜찮다.


def test_api_serves_images_from_s3(tmp_path, s3):
    settings = Settings(output_dir=tmp_path, db_path=tmp_path / "t.db", preset_seed_dir=None)
    tagger = lambda text, keep_alive: None  # noqa: E731
    pipeline = Pipeline(PngBackend(), tagger, s3, JobStore(settings.db_path), image_format="webp")
    with TestClient(create_app(settings, pipeline)) as client:
        done = wait_done(client, client.post("/jobs", json={"prompt": "1girl"}).json()["id"])
        key = f"{done['id']}.webp"
        assert s3.exists(key) and not (tmp_path / key).exists()

        res = client.get(done["image_url"])
        assert res.status_code == 200 and res.content[8:12] == b"WEBP"
        assert res.headers["content-type"] == "image/webp"
        assert "immutable" in res.headers["cache-control"]
        assert client.get("/images/0123456789ab.webp").status_code == 404
        assert client.get("/health").json()["storage"] == "s3"


# --- 옮기기 스크립트 --------------------------------------------------------

def test_migrate_copies_everything_once(tmp_path, s3, db_target):
    src_db, src_dir = tmp_path / "src.db", LocalStorage(tmp_path / "outputs")
    jobs, presets = JobStore(src_db), PresetStore(src_db)
    jobs.save(job("aaaaaaaaaaaa", image_url="/images/aaaaaaaaaaaa.webp"))
    jobs.save(job("bbbbbbbbbbbb", image_url="/images/bbbbbbbbbbbb.png"))
    jobs.save(job("cccccccccccc", status="failed"))
    preset = presets.create(PresetIn(type="style", name="밤", positive=["night"]))
    jobs.close(), presets.close()
    src_dir.put("aaaaaaaaaaaa.webp", b"webp", "image/webp")  # bbbb 의 이미지는 일부러 없다.

    assert migrate(src_db, src_dir, db_target, s3, dry_run=True)["images"] == 1
    assert not s3.exists("aaaaaaaaaaaa.webp")

    stats = migrate(src_db, src_dir, db_target, s3)
    assert stats == {"jobs": 3, "presets": 1, "images": 1, "images_skipped": 0, "images_missing": 1}
    dst = JobStore(db_target)
    assert dst.count() == 3 and dst.get("aaaaaaaaaaaa").image_url == "/images/aaaaaaaaaaaa.webp"
    assert PresetStore(db_target).get(preset.id).created_at == preset.created_at
    assert s3.get("aaaaaaaaaaaa.webp") == b"webp"

    again = migrate(src_db, src_dir, db_target, s3)  # 다시 돌려도 중복되지 않는다.
    assert again["images"] == 0 and again["images_skipped"] == 1 and dst.count() == 3
