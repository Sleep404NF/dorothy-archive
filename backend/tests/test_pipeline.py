"""가짜 이미지 백엔드로 파이프라인의 순서와 메모리 규칙을 검증한다. ComfyUI/Ollama 불필요."""

import contextlib
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.image.base import GeneratedImage, ImageBackend
from app.main import create_app
from app.pipeline import Pipeline
from app.store import JobStore
from app.tagging.ollama_tagger import TagResult


class FakeBackend(ImageBackend):
    name = "fake"

    def __init__(self, events, local=True, fail=False):
        self.events = events
        self.uses_local_memory = local
        self.fail = fail

    async def generate(self, params):
        if self.fail:
            raise RuntimeError("boom")
        self.events.append(("generate", params.positive, params.seed))
        return GeneratedImage(data=b"\x89PNG fake")

    async def health(self):
        return True

    async def release(self):
        self.events.append(("release",))


@contextlib.contextmanager
def make_client(tmp_path, events=None, **backend_kwargs):
    events = [] if events is None else events

    def tagger(text, keep_alive):
        events.append(("tag", text, keep_alive))
        return TagResult(request=text, tags={"subject": ["1girl", "solo"]})

    settings = Settings(output_dir=tmp_path, db_path=tmp_path / "test.db")
    pipeline = Pipeline(FakeBackend(events, **backend_kwargs), tagger, tmp_path, JobStore(settings.db_path))
    with TestClient(create_app(settings, pipeline)) as client:
        yield client, events


def wait_done(client, job_id):
    for _ in range(200):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.01)
    pytest.fail("job did not finish")


def test_korean_request_is_tagged_then_generated(tmp_path):
    with make_client(tmp_path) as (client, events):
        res = client.post("/jobs", json={"request": "은발 소녀", "seed": 1})
        assert res.status_code == 202
        job = wait_done(client, res.json()["id"])

        assert job["status"] == "done"
        assert job["positive"].endswith("1girl, solo")
        assert events == [("tag", "은발 소녀", 0), ("generate", job["positive"], 1)]
        assert client.get(job["image_url"]).content == b"\x89PNG fake"


def test_image_model_is_released_before_next_llm_call(tmp_path):
    with make_client(tmp_path) as (client, events):
        wait_done(client, client.post("/jobs", json={"request": "a"}).json()["id"])
        wait_done(client, client.post("/jobs", json={"request": "b"}).json()["id"])
        assert [e[0] for e in events] == ["tag", "generate", "release", "tag", "generate"]


def test_ready_prompt_skips_llm_and_keeps_image_model_loaded(tmp_path):
    with make_client(tmp_path) as (client, events):
        wait_done(client, client.post("/jobs", json={"prompt": "1girl", "seed": 5}).json()["id"])
        wait_done(client, client.post("/jobs", json={"prompt": "1boy", "seed": 6}).json()["id"])
        assert events == [("generate", "1girl", 5), ("generate", "1boy", 6)]


def test_remote_backend_keeps_llm_warm_and_never_releases(tmp_path):
    with make_client(tmp_path, local=False) as (client, events):
        wait_done(client, client.post("/jobs", json={"request": "a"}).json()["id"])
        wait_done(client, client.post("/jobs", json={"request": "b"}).json()["id"])
        assert [e[0] for e in events] == ["tag", "generate", "tag", "generate"]
        assert events[0][2] == "5m"


def test_backend_failure_is_reported_on_the_job(tmp_path):
    with make_client(tmp_path, fail=True) as (client, _):
        job = wait_done(client, client.post("/jobs", json={"prompt": "1girl"}).json()["id"])
        assert job["status"] == "failed"
        assert "boom" in job["error"]


def test_request_and_prompt_are_mutually_exclusive(tmp_path):
    with make_client(tmp_path) as (client, _):
        assert client.post("/jobs", json={}).status_code == 422
        assert client.post("/jobs", json={"request": "a", "prompt": "b"}).status_code == 422


def test_history_survives_restart_newest_first(tmp_path):
    with make_client(tmp_path) as (client, _):
        first = wait_done(client, client.post("/jobs", json={"request": "첫 번째", "seed": 1}).json()["id"])
        second = wait_done(client, client.post("/jobs", json={"prompt": "1boy", "seed": 2}).json()["id"])

    with make_client(tmp_path) as (client, _):
        page = client.get("/jobs").json()
        assert page["total"] == 2
        assert [j["id"] for j in page["items"]] == [second["id"], first["id"]]
        assert client.get(f"/jobs/{first['id']}").json() == first
        assert client.get("/jobs", params={"limit": 1, "offset": 1}).json()["items"][0]["id"] == first["id"]
        assert client.get("/jobs", params={"status": "failed"}).json() == {"total": 0, "items": []}


def test_rerun_reuses_prompt_and_seed_without_llm(tmp_path):
    with make_client(tmp_path) as (client, events):
        original = wait_done(client, client.post("/jobs", json={"request": "은발 소녀", "seed": 9}).json()["id"])
        events.clear()

        res = client.post(f"/jobs/{original['id']}/rerun")
        assert res.status_code == 202
        again = wait_done(client, res.json()["id"])

        assert events == [("generate", original["positive"], 9)]
        assert again["rerun_of"] == original["id"]
        assert (again["request"], again["tags"]) == (original["request"], original["tags"])
        assert again["id"] != original["id"]

        varied = wait_done(client, client.post(f"/jobs/{original['id']}/rerun?new_seed=true").json()["id"])
        assert varied["positive"] == original["positive"]
        assert client.post("/jobs/nope/rerun").status_code == 404


def test_jobs_cut_off_by_shutdown_are_marked_failed(tmp_path):
    store = JobStore(tmp_path / "test.db")
    with make_client(tmp_path) as (client, _):
        stuck = wait_done(client, client.post("/jobs", json={"prompt": "1girl"}).json()["id"])
    stuck = store.get(stuck["id"])
    stuck.status, stuck.image_url = "generating", None
    store.save(stuck)
    store.close()

    with make_client(tmp_path) as (client, _):
        job = client.get(f"/jobs/{stuck.id}").json()
        assert job["status"] == "failed"
        assert "interrupted" in job["error"]
        assert client.post(f"/jobs/{stuck.id}/rerun").status_code == 202
