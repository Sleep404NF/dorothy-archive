"""작업 큐(inline/celery), 이벤트 버스(메모리/Redis), SSE, Celery 워커, ComfyUI 진행률을 검증한다."""

import asyncio
import json
import socket
import threading
import time

import fakeredis
import httpx
import pytest
import uvicorn

from app import worker
from app.config import Settings
from app.events import InMemoryBus, RedisBus
from app.image.base import GeneratedImage, ImageBackend
from app.image.comfyui import ComfyUIBackend
from app.main import create_app
from app.pipeline import Job, JobRequest, Pipeline
from app.queue import CeleryQueue, JobQueue, QueueUnavailable
from app.store import JobStore
from app.tagging.ollama_tagger import TagResult


class StepBackend(ImageBackend):
    """그리는 동안 진행률을 steps 번 알리는 가짜 백엔드."""

    name = "step"

    def __init__(self, delay=0.0):
        self.delay = delay

    async def generate(self, params, on_progress=None):
        for step in range(1, params.steps + 1):
            await asyncio.sleep(self.delay)
            if on_progress:
                await on_progress(step, params.steps)
        return GeneratedImage(data=b"\x89PNG fake")

    async def health(self):
        return True


def tagger(text, keep_alive):
    return TagResult(request=text, tags={"subject": ["1girl"]})


def make_pipeline(tmp_path, **kwargs):
    return Pipeline(StepBackend(kwargs.pop("delay", 0.0)), tagger, tmp_path, JobStore(tmp_path / "t.db"), **kwargs)


def kinds(events):
    return [e["job"]["status"] if e["type"] == "job" else f"step{e['step']}" for e in events]


async def collect_until_done(sub, timeout=5.0):
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = await sub.get(timeout=0.5)
        if event:
            events.append(event)
            if event["type"] == "job" and event["job"]["status"] in ("done", "failed"):
                return events
    pytest.fail(f"no final event: {events}")


# --- 파이프라인 이벤트 (inline) ------------------------------------------------

def test_inline_pipeline_emits_status_and_progress(tmp_path):
    async def scenario():
        pipeline = make_pipeline(tmp_path)
        async with pipeline.events.subscribe() as sub:
            await pipeline.submit(JobRequest(request="소녀", steps=3, seed=1))
            return await collect_until_done(sub)

    events = asyncio.run(scenario())
    assert kinds(events) == ["queued", "tagging", "generating", "step1", "step2", "step3", "done"]
    assert events[3] == {"type": "progress", "id": events[0]["job"]["id"], "step": 1, "total": 3}


def test_execute_ignores_jobs_that_are_not_queued(tmp_path):
    async def scenario():
        pipeline = make_pipeline(tmp_path, queue=NullQueue())
        job = await pipeline.submit(JobRequest(prompt="1girl", steps=1))
        await pipeline.execute(job.id)
        await pipeline.execute(job.id)  # 같은 작업이 두 번 배달돼도 한 번만 그린다.
        await pipeline.execute("missing")
        return pipeline.store.get(job.id)

    assert asyncio.run(scenario()).status == "done"


class NullQueue(JobQueue):
    name = "null"

    def __init__(self):
        self.ids = []

    async def enqueue(self, job_id):
        self.ids.append(job_id)


class DownQueue(JobQueue):
    name = "down"

    async def enqueue(self, job_id):
        raise QueueUnavailable("could not reach the job queue: connection refused")


def test_queue_down_returns_503_and_marks_job_failed(tmp_path):
    from fastapi.testclient import TestClient

    settings = Settings(output_dir=tmp_path, db_path=tmp_path / "t.db", preset_seed_dir=None)
    with TestClient(create_app(settings, make_pipeline(tmp_path, queue=DownQueue()))) as client:
        res = client.post("/jobs", json={"prompt": "1girl"})
        assert res.status_code == 503
        jobs = client.get("/jobs").json()["items"]
        assert jobs[0]["status"] == "failed" and "job queue" in jobs[0]["error"]


def test_recover_modes(tmp_path):
    store = JobStore(tmp_path / "t.db")
    base = dict(created_at="2026-01-01T00:00:00.000+00:00", negative="", seed=1, width=8, height=8,
                steps=1, cfg=1.0, backend="x", positive="1girl")
    store.save(Job(id="q", status="queued", **base))
    store.save(Job(id="g", status="generating", **base))
    store.close()

    def statuses():
        s = JobStore(tmp_path / "t.db")
        return {j.id: j.status for j in s.list()}

    make_pipeline(tmp_path, recover="none")
    assert statuses() == {"q": "queued", "g": "generating"}
    make_pipeline(tmp_path, recover="running")  # 워커: 대기 중인 건 브로커에 남아 있으니 그대로 둔다.
    assert statuses() == {"q": "queued", "g": "failed"}
    make_pipeline(tmp_path)  # inline 기본값: 전부 정리
    assert statuses() == {"q": "failed", "g": "failed"}


# --- Celery 큐 / 워커 ----------------------------------------------------------

class FakeCelery:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send_task(self, name, args, retry):
        if self.fail:
            raise ConnectionRefusedError("redis down")
        self.sent.append((name, args, retry))


def test_celery_queue_sends_only_the_job_id():
    app = FakeCelery()
    asyncio.run(CeleryQueue(app).enqueue("abc"))
    assert app.sent == [("dorothy.generate", ["abc"], False)]
    with pytest.raises(QueueUnavailable):
        asyncio.run(CeleryQueue(FakeCelery(fail=True)).enqueue("abc"))


def test_worker_task_runs_the_job_and_publishes_to_redis(tmp_path, monkeypatch):
    loop = asyncio.new_event_loop()
    redis = fakeredis.aioredis.FakeRedis()
    queue = NullQueue()
    pipeline = make_pipeline(tmp_path, queue=queue, events=RedisBus(client=redis), recover="running")
    monkeypatch.setattr(worker, "_loop", loop)
    monkeypatch.setattr(worker, "_pipeline", pipeline)

    # API 쪽 구독자 역할: 워커가 Redis 로 보내는 이벤트를 받는다.
    from app.events import _RedisSubscription

    pubsub = redis.pubsub()
    loop.run_until_complete(pubsub.subscribe(RedisBus.CHANNEL))
    job = loop.run_until_complete(pipeline.submit(JobRequest(prompt="1girl", steps=2, seed=3)))
    assert queue.ids == [job.id]  # API 는 큐에 id 만 넣는다.

    worker.generate(job.id)  # Celery 워커가 부르는 것과 같은 동기 호출

    async def drain():
        sub, events = _RedisSubscription(pubsub), []
        while (event := await sub.get(timeout=0.3)) is not None:
            events.append(event)
        return events

    events = loop.run_until_complete(drain())
    loop.close()
    assert pipeline.store.get(job.id).status == "done"
    assert kinds(events) == ["queued", "generating", "step1", "step2", "done"]


def test_redis_bus_round_trip():
    async def scenario():
        bus = RedisBus(client=fakeredis.aioredis.FakeRedis())
        async with bus.subscribe() as sub:
            await bus.publish({"type": "progress", "id": "x", "step": 1, "total": 2})
            got = await sub.get(timeout=1)
            nothing = await sub.get(timeout=0.1)
        await bus.close()
        return got, nothing

    assert asyncio.run(scenario()) == ({"type": "progress", "id": "x", "step": 1, "total": 2}, None)


def test_memory_bus_drops_oldest_for_slow_subscribers():
    async def scenario():
        bus = InMemoryBus(maxsize=2)
        async with bus.subscribe() as sub:
            for i in range(3):
                await bus.publish({"i": i})
            return [await sub.get(0.1), await sub.get(0.1), await sub.get(0.1)]

    assert asyncio.run(scenario()) == [{"i": 1}, {"i": 2}, None]


# --- SSE (실제 서버) ------------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sse_streams_job_events_over_http(tmp_path):
    settings = Settings(output_dir=tmp_path, db_path=tmp_path / "t.db", preset_seed_dir=None)
    app = create_app(settings, make_pipeline(tmp_path, delay=0.05))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    try:
        events = []
        with httpx.Client(base_url=base, timeout=10) as client, client.stream("GET", "/events") as res:
            assert res.headers["content-type"].startswith("text/event-stream")
            lines = res.iter_lines()
            assert next(lines) == ": connected"
            job_id = httpx.post(base + "/jobs", json={"prompt": "1girl", "steps": 2}).json()["id"]
            name = None
            for line in lines:
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    events.append((name, data.get("job", {}).get("status") or data.get("step")))
                    if name == "job" and data["job"]["status"] == "done":
                        assert data["job"]["id"] == job_id
                        break
        assert events == [("job", "queued"), ("job", "generating"), ("progress", 1), ("progress", 2), ("job", "done")]
    finally:
        server.should_exit = True
        thread.join(5)


# --- ComfyUI 웹소켓 진행률 ------------------------------------------------------

class FakeWS:
    def __init__(self, messages):
        self.messages = list(messages)

    async def recv(self):
        return self.messages.pop(0)


def test_comfyui_watch_reports_only_this_prompt():
    seen = []

    async def on_progress(step, total):
        seen.append((step, total))

    msgs = [
        json.dumps({"type": "status", "data": {"status": {}}}),
        json.dumps({"type": "progress", "data": {"value": 1, "max": 9, "prompt_id": "other"}}),
        json.dumps({"type": "execution_cached", "data": {"prompt_id": "p1"}}),
        b"\x00binary preview",
        json.dumps({"type": "progress", "data": {"value": 1, "max": 2, "prompt_id": "p1"}}),
        json.dumps({"type": "progress", "data": {"value": 2, "max": 2}}),  # 예전 ComfyUI 는 prompt_id 가 없다.
        json.dumps({"type": "executing", "data": {"node": None, "prompt_id": "p1"}}),
        json.dumps({"type": "progress", "data": {"value": 99, "max": 99, "prompt_id": "p1"}}),
    ]
    asyncio.run(ComfyUIBackend._watch(FakeWS(msgs), "p1", on_progress, time.monotonic() + 5))
    assert seen == [(1, 2), (2, 2)]
