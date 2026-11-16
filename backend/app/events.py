"""작업 이벤트 버스: 상태 변화와 생성 진행률을 SSE 로 흘려보내는 통로.

- inline 모드: API 프로세스 안에서 그리므로 asyncio.Queue 로 나눈다 (InMemoryBus).
- celery 모드: 워커와 API 가 다른 프로세스라 Redis Pub/Sub 으로 나눈다 (RedisBus).

이벤트는 놓쳐도 되는 알림이다. 정확한 상태의 기준은 언제나 DB(작업 기록)다.
그래서 발행이 실패해도 작업은 계속 진행한다 (Pipeline._emit 참고).

이벤트 형식
    {"type": "job", "job": {...Job...}}                       상태가 바뀔 때
    {"type": "progress", "id": "...", "step": 12, "total": 28}  그리는 중
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol


class Subscription(Protocol):
    async def get(self, timeout: float) -> dict | None:
        """다음 이벤트. timeout 초 안에 없으면 None."""


class EventBus:
    async def publish(self, event: dict) -> None:
        raise NotImplementedError

    def subscribe(self) -> "AsyncIterator[Subscription]":
        """async with bus.subscribe() as sub: ... 형태로 쓴다."""
        raise NotImplementedError

    async def close(self) -> None:
        pass


class _QueueSubscription:
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    async def get(self, timeout: float) -> dict | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except asyncio.TimeoutError:
            return None


class InMemoryBus(EventBus):
    def __init__(self, maxsize: int = 1000):
        self._subscribers: set[asyncio.Queue] = set()
        self._maxsize = maxsize

    async def publish(self, event: dict) -> None:
        for queue in list(self._subscribers):
            if queue.full():  # 느린 구독자 때문에 막히지 않게 가장 오래된 것을 버린다.
                queue.get_nowait()
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue(self._maxsize)
        self._subscribers.add(queue)
        try:
            yield _QueueSubscription(queue)
        finally:
            self._subscribers.discard(queue)


class _RedisSubscription:
    def __init__(self, pubsub):
        self._pubsub = pubsub

    async def get(self, timeout: float) -> dict | None:
        # 구독 확인 메시지는 None 으로 돌아오므로, 실제 이벤트가 올 때까지 남은 시간 동안 다시 읽는다.
        deadline = asyncio.get_running_loop().time() + timeout
        while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=remaining)
            if message and message.get("type") == "message":
                return json.loads(message["data"])
        return None


class RedisBus(EventBus):
    CHANNEL = "dorothy:events"

    def __init__(self, url: str | None = None, client=None):
        if client is None:
            import redis.asyncio as aioredis

            client = aioredis.from_url(url)
        self._redis = client

    async def publish(self, event: dict) -> None:
        await self._redis.publish(self.CHANNEL, json.dumps(event, ensure_ascii=False))

    @asynccontextmanager
    async def subscribe(self):
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self.CHANNEL)
        try:
            yield _RedisSubscription(pubsub)
        finally:
            await pubsub.unsubscribe(self.CHANNEL)
            await pubsub.aclose()

    async def close(self) -> None:
        await self._redis.aclose()
