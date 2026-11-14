from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


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
    output_dir: pathlib.Path = field(
        default_factory=lambda: pathlib.Path(os.getenv("DOROTHY_OUTPUT_DIR", REPO_ROOT / "outputs"))
    )
