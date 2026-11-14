"""이미지 백엔드 인터페이스.

파이프라인은 이 인터페이스만 안다. ComfyUI(로컬) 대신 NovelAI나 원격 GPU 서버를
쓰려면 ImageBackend 를 구현하고 app/image/__init__.py 의 BACKENDS 에 등록하면 된다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GenerationParams:
    positive: str
    negative: str
    seed: int
    width: int = 832
    height: int = 1216
    steps: int = 28
    cfg: float = 5.5


@dataclass
class GeneratedImage:
    data: bytes
    mime: str = "image/png"


class ImageBackend(ABC):
    name: str

    # True 면 이 머신의 메모리를 쓰는 백엔드다. 파이프라인이 LLM과 겹치지 않게
    # LLM을 즉시 내리고, LLM을 쓰기 전에 release() 를 부른다.
    # 원격 백엔드(NAI, GPU 서버)는 False 로 두면 LLM을 계속 올려둘 수 있다.
    uses_local_memory: bool = False

    @abstractmethod
    async def generate(self, params: GenerationParams) -> GeneratedImage: ...

    @abstractmethod
    async def health(self) -> bool: ...

    async def release(self) -> None:
        """로드된 모델을 메모리에서 내린다. 원격 백엔드는 할 일이 없다."""

    async def close(self) -> None:
        """서버 종료 시 정리."""
