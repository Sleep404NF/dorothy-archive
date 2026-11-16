"""생성된 이미지를 저장 형식으로 바꾼다.

ComfyUI는 PNG를 돌려주는데, 1장에 1MB 안팎이라 테스트로 계속 뽑으면 금방 쌓인다.
WebP(손실, 품질 90)로 바꾸면 눈으로는 거의 차이 없이 5~10배 작아진다.
변환에 실패하면(이미지가 아니거나 Pillow 가 없으면) 원본 PNG를 그대로 저장한다.
"""

from __future__ import annotations

import io
from typing import Literal

ImageFormat = Literal["webp", "png"]

MEDIA_TYPES = {"png": "image/png", "webp": "image/webp"}


def encode(data: bytes, fmt: ImageFormat = "webp", quality: int = 90) -> tuple[bytes, str]:
    """(저장할 바이트, 확장자) 를 돌려준다."""
    if fmt == "png":
        return data, "png"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            img.load()
            out = io.BytesIO()
            img.save(out, "WEBP", quality=quality, method=6)
        return out.getvalue(), "webp"
    except Exception:
        return data, "png"
