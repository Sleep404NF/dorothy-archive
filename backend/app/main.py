from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .config import Settings
from .events import RedisBus
from .factory import build_pipeline
from .image.encode import MEDIA_TYPES
from .pipeline import Job, JobRequest, Pipeline
from .presets import Composed, Preset, PresetConflict, PresetIn, PresetStore, PresetType, compose, split_tags
from .queue import CeleryQueue, QueueUnavailable
from .storage import LocalStorage
from .store import JobStore

# SSE 연결이 프록시나 브라우저에서 끊기지 않도록 이 간격마다 빈 주석을 보낸다.
SSE_PING_SECONDS = 15.0


class TagRequest(BaseModel):
    request: str


class JobPage(BaseModel):
    total: int
    items: list[Job]


class ComposeRequest(BaseModel):
    character_preset_id: str | None = None
    style_preset_id: str | None = None
    prompt: str | None = None


def create_app(
    settings: Settings | None = None,
    pipeline: Pipeline | None = None,
    presets: PresetStore | None = None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if pipeline is not None:
            app.state.pipeline = pipeline
        elif settings.queue == "celery":
            # 실행은 워커가 한다. API 는 작업을 넣고, 워커가 Redis 로 보내는 이벤트를 SSE 로 전달한다.
            from .worker import celery_app

            app.state.pipeline = build_pipeline(
                settings, queue=CeleryQueue(celery_app), events=RedisBus(settings.redis_url), recover="none"
            )
        else:
            app.state.pipeline = build_pipeline(settings)
        app.state.presets = presets or PresetStore(settings.database_target)
        app.state.presets.seed(settings.preset_seed_dir)
        yield
        p: Pipeline = app.state.pipeline
        await p.backend.close()
        await p.queue.close()
        await p.events.close()
        p.images.close()
        p.store.close()
        app.state.presets.close()

    app = FastAPI(title="DOROTHY", lifespan=lifespan)

    @app.get("/health")
    async def health():
        p: Pipeline = app.state.pipeline
        return {
            "image_backend": p.backend.name,
            "image_backend_ok": await p.backend.health(),
            "queue": p.queue.name,
            "database": p.store.dialect,
            "storage": p.images.name,
        }

    def resolve_presets(character_id: str | None, style_id: str | None) -> dict[str, Preset]:
        """프리셋 id 를 실제 프리셋으로 바꾼다. 없으면 404, 종류가 다르면 422."""
        found: dict[str, Preset] = {}
        for kind, preset_id in (("character", character_id), ("style", style_id)):
            if not preset_id:
                continue
            preset = app.state.presets.get(preset_id)
            if not preset:
                raise HTTPException(404, f"{kind} preset {preset_id!r} not found")
            if preset.type != kind:
                raise HTTPException(422, f"preset {preset_id!r} is a {preset.type} preset, not {kind}")
            found[kind] = preset
        return found

    @app.post("/jobs", status_code=202)
    async def create_job(req: JobRequest) -> Job:
        presets = resolve_presets(req.character_preset_id, req.style_preset_id)
        try:
            return await app.state.pipeline.submit(req, presets)
        except QueueUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.get("/jobs")
    async def list_jobs(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        status: str | None = None,
    ) -> JobPage:
        """생성 기록을 최신순으로 돌려준다."""
        store: JobStore = app.state.pipeline.store
        return JobPage(total=store.count(status), items=store.list(limit, offset, status))

    def find_job(job_id: str) -> Job:
        job = app.state.pipeline.store.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return job

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> Job:
        return find_job(job_id)

    @app.post("/jobs/{job_id}/rerun", status_code=202)
    async def rerun_job(job_id: str, new_seed: bool = False) -> Job:
        """저장된 프롬프트로 다시 생성한다. new_seed=true 면 시드만 바꾼 변주."""
        try:
            return await app.state.pipeline.rerun(find_job(job_id), new_seed=new_seed)
        except QueueUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/events")
    async def events(request: Request) -> StreamingResponse:
        """작업 상태 변화와 생성 진행률을 Server-Sent Events 로 흘려보낸다.

        event: job       data: {"type": "job", "job": {...}}
        event: progress  data: {"type": "progress", "id": "...", "step": 12, "total": 28}
        """
        bus = app.state.pipeline.events

        async def stream():
            yield ": connected\n\n"
            async with bus.subscribe() as sub:
                while not await request.is_disconnected():
                    event = await sub.get(timeout=SSE_PING_SECONDS)
                    if event is None:
                        yield ": ping\n\n"
                        continue
                    yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    @app.get("/images/{name}")
    async def get_image(name: str):
        """이미지 이름은 작업마다 고유하고 바뀌지 않아서 브라우저가 오래 캐시해도 된다."""
        if not re.fullmatch(r"[0-9a-f]{12}\.(png|webp)", name):
            raise HTTPException(404, "image not found")
        media_type = MEDIA_TYPES[name.rsplit(".", 1)[1]]
        headers = {"Cache-Control": "public, max-age=31536000, immutable"}
        images = app.state.pipeline.images
        if isinstance(images, LocalStorage):
            path = images.path(name)
            if not path.is_file():
                raise HTTPException(404, "image not found")
            return FileResponse(path, media_type=media_type, headers=headers)
        data = await asyncio.to_thread(images.get, name)
        if data is None:
            raise HTTPException(404, "image not found")
        return Response(data, media_type=media_type, headers=headers)

    @app.post("/tags")
    async def tags(req: TagRequest):
        result = await app.state.pipeline.convert(req.request)
        return {"tags": result.tags, "positive": result.positive, "negative": result.negative, "report": result.report}

    @app.get("/presets")
    async def list_presets(type: PresetType | None = None) -> list[Preset]:
        return app.state.presets.list(type)

    @app.post("/presets", status_code=201)
    async def create_preset(data: PresetIn) -> Preset:
        try:
            return app.state.presets.create(data)
        except PresetConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/presets/compose")
    async def compose_presets(req: ComposeRequest) -> Composed:
        """생성하지 않고 프리셋을 합친 결과만 미리 본다."""
        found = resolve_presets(req.character_preset_id, req.style_preset_id)
        return compose(found.get("character"), found.get("style"), split_tags(req.prompt))

    def find_preset(preset_id: str) -> Preset:
        preset = app.state.presets.get(preset_id)
        if not preset:
            raise HTTPException(404, "preset not found")
        return preset

    @app.get("/presets/{preset_id}")
    async def get_preset(preset_id: str) -> Preset:
        return find_preset(preset_id)

    @app.put("/presets/{preset_id}")
    async def update_preset(preset_id: str, data: PresetIn) -> Preset:
        find_preset(preset_id)
        try:
            return app.state.presets.update(preset_id, data)
        except PresetConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.delete("/presets/{preset_id}", status_code=204)
    async def delete_preset(preset_id: str) -> Response:
        if not app.state.presets.delete(preset_id):
            raise HTTPException(404, "preset not found")
        return Response(status_code=204)

    @app.post("/release", status_code=204)
    async def release():
        await app.state.pipeline.release()

    return app


app = create_app()
