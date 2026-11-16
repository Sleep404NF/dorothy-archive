"""작업 큐: 생성 요청을 어디서 실행할지 정한다.

- InlineQueue: API 프로세스 안에서 asyncio 태스크로 바로 실행한다. Redis 가 필요 없다.
  개발할 때나 테스트에서 쓴다.
- CeleryQueue: Redis 브로커에 작업 id 만 넣고, 별도의 Celery 워커(app/worker.py)가 실행한다.
  API 를 재시작해도 대기 중인 작업이 사라지지 않고, 워커만 GPU 서버로 옮길 수 있다.

큐에는 작업 전체가 아니라 id 만 넣는다. 작업 내용은 DB 에 먼저 저장하고,
실행하는 쪽(Pipeline.execute)이 DB 에서 꺼내 읽는다.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable


class QueueUnavailable(RuntimeError):
    """큐(브로커)에 작업을 넣지 못했다."""


class JobQueue:
    name: str

    async def enqueue(self, job_id: str) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class InlineQueue(JobQueue):
    name = "inline"

    def __init__(self, run: Callable[[str], Awaitable[None]]):
        self._run = run
        self._tasks: set[asyncio.Task] = set()

    async def enqueue(self, job_id: str) -> None:
        task = asyncio.create_task(self._run(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


class CeleryQueue(JobQueue):
    name = "celery"
    TASK = "dorothy.generate"

    def __init__(self, celery_app):
        self._app = celery_app

    async def enqueue(self, job_id: str) -> None:
        try:
            # retry=False: 브로커가 꺼져 있으면 오래 기다리지 않고 바로 실패를 알린다.
            await asyncio.to_thread(self._app.send_task, self.TASK, args=[job_id], retry=False)
        except Exception as exc:
            raise QueueUnavailable(f"could not reach the job queue: {exc}") from exc
