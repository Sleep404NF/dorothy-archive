from __future__ import annotations

from ..config import Settings
from .base import GeneratedImage, GenerationParams, ImageBackend
from .comfyui import ComfyUIBackend

# 새 백엔드(NAI, 원격 GPU 등)는 여기에 이름 → 생성 함수로 등록한다.
BACKENDS = {
    "comfyui": lambda s: ComfyUIBackend(s.comfyui_host, s.workflow_path, s.comfyui_checkpoint),
}


def create_backend(settings: Settings) -> ImageBackend:
    try:
        return BACKENDS[settings.image_backend](settings)
    except KeyError:
        raise ValueError(f"unknown image backend {settings.image_backend!r}; available: {sorted(BACKENDS)}") from None


__all__ = ["GeneratedImage", "GenerationParams", "ImageBackend", "create_backend"]
