from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Settings
from .image import create_backend
from .pipeline import Job, JobRequest, Pipeline
from .tagging.ollama_tagger import to_tags


class TagRequest(BaseModel):
    request: str


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pipeline = pipeline or Pipeline(
            backend=create_backend(settings),
            tagger=lambda text, keep_alive: to_tags(
                text, model=settings.ollama_model, host=settings.ollama_host, keep_alive=keep_alive
            ),
            output_dir=settings.output_dir,
        )
        yield
        await app.state.pipeline.backend.close()

    app = FastAPI(title="DOROTHY", lifespan=lifespan)

    @app.get("/health")
    async def health():
        p: Pipeline = app.state.pipeline
        return {"image_backend": p.backend.name, "image_backend_ok": await p.backend.health()}

    @app.post("/jobs", status_code=202)
    async def create_job(req: JobRequest) -> Job:
        return app.state.pipeline.submit(req)

    @app.get("/jobs")
    async def list_jobs() -> list[Job]:
        return list(app.state.pipeline.jobs.values())

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> Job:
        job = app.state.pipeline.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return job

    @app.get("/images/{name}")
    async def get_image(name: str):
        path = settings.output_dir / name
        if not re.fullmatch(r"[0-9a-f]{12}\.png", name) or not path.is_file():
            raise HTTPException(404, "image not found")
        return FileResponse(path, media_type="image/png")

    @app.post("/tags")
    async def tags(req: TagRequest):
        result = await app.state.pipeline.convert(req.request)
        return {"tags": result.tags, "positive": result.positive, "negative": result.negative}

    @app.post("/release", status_code=204)
    async def release():
        await app.state.pipeline.release()

    return app


app = create_app()
