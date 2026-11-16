from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Settings
from .image import create_backend
from .image.encode import MEDIA_TYPES
from .pipeline import Job, JobRequest, Pipeline
from .presets import Composed, Preset, PresetConflict, PresetIn, PresetStore, PresetType, compose, split_tags
from .store import JobStore
from .tagging.ollama_tagger import to_tags
from .tagging.refine import load_refiner


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
        app.state.pipeline = pipeline or Pipeline(
            backend=create_backend(settings),
            tagger=lambda text, keep_alive: to_tags(
                text, model=settings.ollama_model, host=settings.ollama_host, keep_alive=keep_alive
            ),
            output_dir=settings.output_dir,
            store=JobStore(settings.db_path),
            image_format="png" if settings.image_format == "png" else "webp",
            webp_quality=settings.webp_quality,
            refiner=load_refiner(settings.tag_dictionary_path, settings.tag_extra_path, settings.glossary_path)
            if settings.tag_validation
            else None,
        )
        app.state.presets = presets or PresetStore(settings.db_path)
        app.state.presets.seed(settings.preset_seed_dir)
        yield
        await app.state.pipeline.backend.close()
        app.state.pipeline.store.close()
        app.state.presets.close()

    app = FastAPI(title="DOROTHY", lifespan=lifespan)

    @app.get("/health")
    async def health():
        p: Pipeline = app.state.pipeline
        return {"image_backend": p.backend.name, "image_backend_ok": await p.backend.health()}

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
        return app.state.pipeline.submit(req, presets)

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
            return app.state.pipeline.rerun(find_job(job_id), new_seed=new_seed)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/images/{name}")
    async def get_image(name: str):
        path = settings.output_dir / name
        if not re.fullmatch(r"[0-9a-f]{12}\.(png|webp)", name) or not path.is_file():
            raise HTTPException(404, "image not found")
        return FileResponse(path, media_type=MEDIA_TYPES[path.suffix[1:]])

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
