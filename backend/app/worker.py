"""Celery 워커: 큐에서 작업 id 를 받아 파이프라인을 실행한다.

    cd backend && DOROTHY_QUEUE=celery celery -A app.worker worker --pool=solo --concurrency=1 --loglevel=info

GPU(맥에서는 통합 메모리)는 한 번에 한 장만 그려야 하므로 solo 풀, 동시성 1로 띄운다.
LLM 과 SDXL 을 번갈아 올리는 메모리 규칙도 이 한 프로세스 안에서 지켜진다.
진행률과 상태 변화는 Redis Pub/Sub 으로 보내고, API 가 받아서 SSE 로 내보낸다.
"""

from __future__ import annotations

import asyncio

from celery import Celery

from .config import Settings
from .queue import CeleryQueue

settings = Settings()

celery_app = Celery("dorothy", broker=settings.redis_url)
celery_app.conf.update(
    task_default_queue="dorothy",
    task_ignore_result=True,  # 결과는 DB 에 남기므로 결과 백엔드를 쓰지 않는다.
    worker_prefetch_multiplier=1,  # 한 장씩만 가져간다.
    broker_connection_retry_on_startup=True,
)

_loop: asyncio.AbstractEventLoop | None = None
_pipeline = None


def get_pipeline():
    """워커 프로세스마다 파이프라인 하나와 이벤트 루프 하나를 만들어 계속 쓴다."""
    global _loop, _pipeline
    if _pipeline is None:
        from .events import RedisBus
        from .factory import build_pipeline

        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _pipeline = build_pipeline(settings, events=RedisBus(settings.redis_url), recover="running")
    return _pipeline


@celery_app.task(name=CeleryQueue.TASK)
def generate(job_id: str) -> None:
    pipeline = get_pipeline()
    _loop.run_until_complete(pipeline.execute(job_id))
