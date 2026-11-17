"""설정으로 파이프라인을 조립한다. API(main.py)와 Celery 워커(worker.py)가 같이 쓴다."""

from __future__ import annotations

from typing import Literal

from .config import Settings
from .events import EventBus
from .image import create_backend
from .pipeline import Pipeline
from .queue import JobQueue
from .storage import create_storage
from .store import JobStore
from .tagging.ollama_tagger import to_tags
from .tagging.refine import load_refiner


def build_pipeline(
    settings: Settings,
    queue: JobQueue | None = None,
    events: EventBus | None = None,
    recover: Literal["all", "running", "none"] = "all",
) -> Pipeline:
    return Pipeline(
        backend=create_backend(settings),
        tagger=lambda text, keep_alive: to_tags(
            text, model=settings.ollama_model, host=settings.ollama_host, keep_alive=keep_alive
        ),
        images=create_storage(settings),
        store=JobStore(settings.database_target),
        image_format="png" if settings.image_format == "png" else "webp",
        webp_quality=settings.webp_quality,
        refiner=load_refiner(settings.tag_dictionary_path, settings.tag_extra_path, settings.glossary_path)
        if settings.tag_validation
        else None,
        queue=queue,
        events=events,
        recover=recover,
    )
