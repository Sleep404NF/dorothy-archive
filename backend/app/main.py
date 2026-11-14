from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Settings
from .image import create_backend
from .pipeline import Job, JobRequest, Pipeline
from .store import JobStore
from .tagging.ollama_tagger import to_tags


class TagRequest(BaseModel):
    request: str


class JobPage(BaseModel):
    total: int
    items: list[Job]


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
            store=JobStore(settings.db_path),
        )
        yield
        await app.state.pipeline.backend.close()
        app.state.pipeline.store.close()

    app = FastAPI(title="DOROTHY", lifespan=lifespan)

    @app.get("/health")
    async def health():
        p: Pipeline = app.state.pipeline
        return {"image_backend": p.backend.name, "image_backend_ok": await p.backend.health()}

    @app.post("/jobs", status_code=202)
    async def create_job(req: JobRequest) -> Job:
        return app.state.pipeline.submit(req)

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
