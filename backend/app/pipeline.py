"""요청 → (LLM 태그 변환) → 이미지 생성 파이프라인.

메모리 규칙: 한 번에 한 작업만 돌리고(_lock), 이미지 백엔드가 로컬 메모리를 쓰면
LLM과 SDXL이 동시에 올라가지 않게 한다.
- LLM은 keep_alive=0 으로 호출해 응답 직후 내려간다.
- SDXL은 생성 후 올려둔 채로 두고(연속 생성 시 재로딩 방지), 다음에 LLM이 필요해질 때 내린다.
"""

from __future__ import annotations

import asyncio
import datetime
import pathlib
import random
import time
import uuid
from typing import Callable, Literal

from pydantic import BaseModel, Field, model_validator

from .image import GenerationParams, ImageBackend
from .presets import Preset, compose, merge_negative, split_tags
from .store import JobStore
from .tagging.ollama_tagger import NEGATIVE_PROMPT, NSFW_NEGATIVE_TAG, TagResult
from .tagging.refine import TagRefiner

Tagger = Callable[[str, "int | str"], TagResult]


class JobRequest(BaseModel):
    request: str | None = Field(None, description="한국어 자연어 요청. LLM이 Danbooru 태그로 바꾼다.")
    prompt: str | None = Field(None, description="이미 완성된 태그 프롬프트. 주면 LLM을 건너뛴다.")
    character_preset_id: str | None = Field(None, description="캐릭터 프리셋. 태그 맨 앞에 합친다.")
    style_preset_id: str | None = Field(None, description="스타일 프리셋. 태그 맨 뒤에 합친다.")
    negative: str | None = None
    exclude_nsfw: bool = Field(True, description="True 면 제외 프롬프트 앞에 'nsfw' 를 붙인다.")
    seed: int | None = None
    width: int = Field(832, ge=256, le=2048, multiple_of=8)
    height: int = Field(1216, ge=256, le=2048, multiple_of=8)
    steps: int = Field(28, ge=1, le=100)
    cfg: float = Field(5.5, ge=1, le=20)

    @model_validator(mode="after")
    def _one_source(self):
        if self.request and self.prompt:
            raise ValueError("give either 'request' or 'prompt', not both")
        if not (self.request or self.prompt or self.character_preset_id or self.style_preset_id):
            raise ValueError("give 'request', 'prompt' or at least one preset")
        return self


def build_negative(req: JobRequest) -> str:
    negative = req.negative or NEGATIVE_PROMPT
    already = NSFW_NEGATIVE_TAG in [t.strip().lower() for t in negative.split(",")]
    return f"{NSFW_NEGATIVE_TAG}, {negative}" if req.exclude_nsfw and not already else negative


class Job(BaseModel):
    id: str
    created_at: str
    rerun_of: str | None = None
    status: Literal["queued", "tagging", "generating", "done", "failed"] = "queued"
    request: str | None = None
    tags: dict | None = None
    # 생성 당시 프리셋의 스냅샷. 나중에 프리셋을 고치거나 지워도 이 기록은 그대로다.
    presets: dict[str, Preset] | None = None
    # 태그 검증 보고서: 용어집 적용, 별칭 정리, 사전에 없어 뺀 태그.
    tag_report: dict | None = None
    positive: str | None = None
    negative: str
    seed: int
    width: int
    height: int
    steps: int
    cfg: float
    backend: str
    image_url: str | None = None
    error: str | None = None
    tagging_seconds: float | None = None
    generation_seconds: float | None = None


class Pipeline:
    def __init__(
        self,
        backend: ImageBackend,
        tagger: Tagger,
        output_dir: pathlib.Path,
        store: JobStore,
        refiner: TagRefiner | None = None,
    ):
        self.backend = backend
        self.refiner = refiner
        self.store = store
        store.fail_unfinished("interrupted: the server stopped before this job finished")
        self._tagger = tagger
        self._output_dir = output_dir
        self._lock = asyncio.Lock()
        self._image_model_loaded = False
        self._tasks: set[asyncio.Task] = set()

    def submit(self, req: JobRequest, presets: dict[str, Preset] | None = None) -> Job:
        """presets 는 {"character": Preset, "style": Preset} 중 쓰는 것만 담는다 (조회는 호출한 쪽이 한다)."""
        return self._enqueue(self._new_job(req, presets or None))

    def rerun(self, original: Job, new_seed: bool = False) -> Job:
        """저장된 프롬프트로 다시 생성한다. LLM을 거치지 않으므로 같은 시드면 같은 그림이 나온다."""
        if not original.positive:
            raise ValueError("this job has no prompt to rerun (it failed before tagging finished)")
        job = self._new_job(
            JobRequest(
                prompt=original.positive,
                negative=original.negative,
                exclude_nsfw=False,  # 저장된 제외 프롬프트를 그대로 쓴다.
                seed=None if new_seed else original.seed,
                width=original.width,
                height=original.height,
                steps=original.steps,
                cfg=original.cfg,
            )
        )
        job.request, job.tags, job.rerun_of = original.request, original.tags, original.id
        job.tag_report = original.tag_report
        job.presets = original.presets  # 이미 합쳐진 프롬프트를 쓰므로 다시 합치지 않는다.
        return self._enqueue(job)

    def _new_job(self, req: JobRequest, presets: dict[str, Preset] | None = None) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"),
            request=req.request,
            positive=req.prompt,
            negative=build_negative(req),
            seed=req.seed if req.seed is not None else random.randrange(2**32),
            width=req.width,
            height=req.height,
            steps=req.steps,
            cfg=req.cfg,
            backend=self.backend.name,
        )
        if presets:
            job.presets = presets
            composed = compose(presets.get("character"), presets.get("style"), split_tags(req.prompt))
            job.negative = merge_negative(job.negative, composed.negative_tags)
            if not req.request:  # 요청이 있으면 태그 변환이 끝난 뒤 합친다.
                job.positive = composed.positive
        return job

    def _enqueue(self, job: Job) -> Job:
        self.store.save(job)
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def convert(self, request: str) -> TagResult:
        async with self._lock:
            return await self._tag(request)

    async def release(self) -> None:
        async with self._lock:
            await self.backend.release()
            self._image_model_loaded = False

    async def _tag(self, request: str) -> TagResult:
        local = self.backend.uses_local_memory
        if local and self._image_model_loaded:
            await self.backend.release()
            self._image_model_loaded = False
        if not self.refiner:
            return await asyncio.to_thread(self._tagger, request, 0 if local else "5m")
        # 용어집 힌트를 붙여 LLM에 보내고, 결과를 사전·용어집으로 다듬는다.
        raw = await asyncio.to_thread(self._tagger, request + self.refiner.hint(request), 0 if local else "5m")
        tags, report = self.refiner.refine(request, raw.tags)
        return TagResult(request=request, tags=tags, report=report)

    async def _run(self, job: Job) -> None:
        async with self._lock:
            try:
                if job.positive is None:
                    job.status = "tagging"
                    self.store.save(job)
                    started = time.monotonic()
                    result = await self._tag(job.request)
                    job.tags, job.positive, job.tag_report = result.tags, result.positive, result.report
                    if job.presets:
                        job.positive = compose(
                            job.presets.get("character"), job.presets.get("style"), split_tags(result.positive)
                        ).positive
                    job.tagging_seconds = round(time.monotonic() - started, 1)

                job.status = "generating"
                self.store.save(job)
                started = time.monotonic()
                self._image_model_loaded = True
                image = await self.backend.generate(
                    GenerationParams(
                        positive=job.positive,
                        negative=job.negative,
                        seed=job.seed,
                        width=job.width,
                        height=job.height,
                        steps=job.steps,
                        cfg=job.cfg,
                    )
                )
                job.generation_seconds = round(time.monotonic() - started, 1)

                self._output_dir.mkdir(parents=True, exist_ok=True)
                (self._output_dir / f"{job.id}.png").write_bytes(image.data)
                job.image_url = f"/images/{job.id}.png"
                job.status = "done"
            except Exception as exc:  # 작업 실패는 서버를 죽이지 않고 job 에 남긴다.
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
            self.store.save(job)
