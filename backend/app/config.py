from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# 저장소 루트의 .env 가 있으면 읽는다. 이미 설정된 환경 변수가 우선이다.
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:  # python-dotenv 가 없어도 환경 변수만으로 동작한다.
    pass


@dataclass
class Settings:
    image_backend: str = field(default_factory=lambda: os.getenv("DOROTHY_IMAGE_BACKEND", "comfyui"))
    comfyui_host: str = field(default_factory=lambda: os.getenv("DOROTHY_COMFYUI_HOST", "http://127.0.0.1:8188"))
    comfyui_checkpoint: str | None = field(default_factory=lambda: os.getenv("DOROTHY_COMFYUI_CHECKPOINT"))
    workflow_path: pathlib.Path = field(
        default_factory=lambda: pathlib.Path(
            os.getenv("DOROTHY_WORKFLOW", REPO_ROOT / "workflows" / "txt2img_sdxl.api.json")
        )
    )
    ollama_host: str = field(default_factory=lambda: os.getenv("DOROTHY_OLLAMA_HOST", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("DOROTHY_OLLAMA_MODEL", "gemma3:4b"))
    db_path: pathlib.Path = field(
        default_factory=lambda: pathlib.Path(os.getenv("DOROTHY_DB", REPO_ROOT / "data" / "dorothy.db"))
    )
    # 프리셋 저장소가 비어 있을 때 넣을 기본 프리셋 폴더. 없으면 건너뛴다.
    preset_seed_dir: pathlib.Path | None = field(
        default_factory=lambda: pathlib.Path(
            os.getenv("DOROTHY_PRESET_SEED_DIR", REPO_ROOT / "prompts" / "presets")
        )
    )
    # 태그 검증용 파일. 없으면 그 단계를 건너뛴다. DOROTHY_TAG_VALIDATION=0 이면 전부 끈다.
    tag_validation: bool = field(default_factory=lambda: os.getenv("DOROTHY_TAG_VALIDATION", "1") != "0")
    tag_dictionary_path: pathlib.Path = field(
        default_factory=lambda: pathlib.Path(
            os.getenv("DOROTHY_TAG_DICTIONARY", REPO_ROOT / "prompts" / "tags" / "danbooru_tags.csv.gz")
        )
    )
    tag_extra_path: pathlib.Path = REPO_ROOT / "prompts" / "tags" / "extra_tags.txt"
    glossary_path: pathlib.Path = field(
        default_factory=lambda: pathlib.Path(os.getenv("DOROTHY_GLOSSARY", REPO_ROOT / "prompts" / "glossary.ko.json"))
    )
    # 생성 이미지 저장 형식. webp 가 기본이고, 원본 PNG 그대로 두려면 png.
    image_format: str = field(default_factory=lambda: os.getenv("DOROTHY_IMAGE_FORMAT", "webp"))
    webp_quality: int = field(default_factory=lambda: int(os.getenv("DOROTHY_WEBP_QUALITY", "90")))
    # 작업 큐. inline: API 프로세스 안에서 바로 실행 (Redis 불필요)
    #          celery: Redis 브로커 + 별도 워커 (app/worker.py)
    queue: str = field(default_factory=lambda: os.getenv("DOROTHY_QUEUE", "inline"))
    redis_url: str = field(default_factory=lambda: os.getenv("DOROTHY_REDIS_URL", "redis://127.0.0.1:6379/0"))
    # DB. 비워 두면 db_path 의 SQLite, 주면 그 URL (예: postgresql+psycopg://dorothy:dorothy@127.0.0.1:5432/dorothy)
    database_url: str = field(default_factory=lambda: os.getenv("DOROTHY_DATABASE_URL", ""))
    # 이미지 저장소. local: output_dir 폴더 / s3: S3 호환 스토리지 (docker compose 의 RustFS, R2, B2, AWS S3)
    storage: str = field(default_factory=lambda: os.getenv("DOROTHY_STORAGE", "local"))
    s3_endpoint: str = field(default_factory=lambda: os.getenv("DOROTHY_S3_ENDPOINT", ""))
    s3_bucket: str = field(default_factory=lambda: os.getenv("DOROTHY_S3_BUCKET", "dorothy"))
    s3_access_key: str = field(default_factory=lambda: os.getenv("DOROTHY_S3_ACCESS_KEY", ""))
    s3_secret_key: str = field(default_factory=lambda: os.getenv("DOROTHY_S3_SECRET_KEY", ""))
    s3_region: str = field(default_factory=lambda: os.getenv("DOROTHY_S3_REGION", "us-east-1"))
    output_dir: pathlib.Path = field(
        default_factory=lambda: pathlib.Path(os.getenv("DOROTHY_OUTPUT_DIR", REPO_ROOT / "outputs"))
    )

    @property
    def database_target(self) -> str | pathlib.Path:
        """JobStore / PresetStore 에 넘길 값: DB URL 이 있으면 그것, 없으면 SQLite 파일 경로."""
        return self.database_url or self.db_path
